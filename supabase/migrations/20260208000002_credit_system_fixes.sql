-- Fix: atomic increment RPC for purchased seconds (prevents race conditions)
CREATE OR REPLACE FUNCTION public.add_purchased_seconds(p_user_id UUID, p_seconds BIGINT)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    UPDATE public.user_credits
    SET total_purchased_seconds = total_purchased_seconds + p_seconds,
        updated_at = NOW()
    WHERE user_id = p_user_id;
END;
$$;

GRANT EXECUTE ON FUNCTION public.add_purchased_seconds(UUID, BIGINT) TO service_role;

-- Fix: unique constraint on stripe_session_id for idempotent webhook processing
CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_purchases_stripe_session
ON public.credit_purchases(stripe_session_id)
WHERE stripe_session_id IS NOT NULL;

-- Fix: drop redundant index (UNIQUE constraint on user_id already creates one)
DROP INDEX IF EXISTS idx_user_credits_user_id;
