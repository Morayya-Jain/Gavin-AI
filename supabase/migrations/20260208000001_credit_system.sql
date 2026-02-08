-- Credit/hours-based pricing: credit_packages, user_credits, credit_purchases
-- After creating Stripe products, update credit_packages.stripe_price_id via Dashboard or:
--   UPDATE credit_packages SET stripe_price_id = 'price_xxx' WHERE name = '1_hour';

-- 1. Credit packages (product catalog for hour packs)
CREATE TABLE public.credit_packages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    hours INTEGER NOT NULL,
    price_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'aud',
    stripe_price_id TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Per-user credit balance (source of truth; only service role / RPC writes)
CREATE TABLE public.user_credits (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL UNIQUE,
    total_purchased_seconds BIGINT NOT NULL DEFAULT 0,
    total_used_seconds BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_user_credits_user_id ON public.user_credits(user_id);

-- 3. Purchase history log
CREATE TABLE public.credit_purchases (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
    package_id UUID REFERENCES public.credit_packages(id) ON DELETE SET NULL,
    stripe_session_id TEXT,
    stripe_payment_intent TEXT,
    seconds_added INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    purchased_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_credit_purchases_user_id ON public.credit_purchases(user_id);

-- Seed credit packages (stripe_price_id can be set later via Stripe Dashboard or UPDATE)
INSERT INTO public.credit_packages (name, display_name, hours, price_cents, currency, stripe_price_id, sort_order)
VALUES
    ('1_hour', '1 Hour', 1, 199, 'aud', NULL, 1),
    ('10_hours', '10 Hours', 10, 1499, 'aud', NULL, 2),
    ('30_hours', '30 Hours', 30, 3499, 'aud', NULL, 3);

-- Auto-create user_credits when a new profile is created
CREATE OR REPLACE FUNCTION public.handle_new_user_credits()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.user_credits (user_id)
    VALUES (NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_profile_created_credits
    AFTER INSERT ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user_credits();

-- Backfill user_credits for existing profiles that don't have a row (e.g. created before this migration)
INSERT INTO public.user_credits (user_id)
SELECT p.id FROM public.profiles p
WHERE NOT EXISTS (SELECT 1 FROM public.user_credits uc WHERE uc.user_id = p.id)
ON CONFLICT (user_id) DO NOTHING;

-- Migrate existing paid users: give 2 hours (7200 seconds) to anyone with active subscription
UPDATE public.user_credits uc
SET total_purchased_seconds = uc.total_purchased_seconds + 7200,
    updated_at = NOW()
FROM public.subscriptions s
WHERE s.user_id = uc.user_id AND s.status = 'active';

-- Deprecate old starter tier (keep table for legacy)
UPDATE public.subscription_tiers SET is_active = FALSE WHERE name = 'starter';

-- updated_at trigger for user_credits
CREATE TRIGGER update_user_credits_updated_at
    BEFORE UPDATE ON public.user_credits
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- RLS
ALTER TABLE public.credit_packages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_credits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.credit_purchases ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can read active credit packages" ON public.credit_packages
    FOR SELECT USING (is_active = TRUE);

CREATE POLICY "Users can read own user_credits" ON public.user_credits
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can read own credit_purchases" ON public.credit_purchases
    FOR SELECT USING (auth.uid() = user_id);

-- RPC: record session usage (called by desktop app with JWT; increments total_used_seconds)
CREATE OR REPLACE FUNCTION public.record_session_usage(p_seconds BIGINT)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF p_seconds IS NULL OR p_seconds < 0 THEN
        RETURN;
    END IF;
    UPDATE public.user_credits
    SET total_used_seconds = total_used_seconds + p_seconds,
        updated_at = NOW()
    WHERE user_id = auth.uid();
END;
$$;

-- Allow authenticated users to call the RPC
GRANT EXECUTE ON FUNCTION public.record_session_usage(BIGINT) TO authenticated;
GRANT EXECUTE ON FUNCTION public.record_session_usage(BIGINT) TO service_role;
