# Phase 1: Backend & Auth (Supabase)

> **Prerequisites:** Read `00-MIGRATION-OVERVIEW.md` first for full context.
>
> **This phase comes FIRST.** Both the desktop app (Phase 2) and web dashboard (Phase 3) depend on having the backend in place. The existing desktop app continues working unchanged while you build this — zero user-facing risk.

---

## Table of Contents

1. [Overview](#overview)
2. [Supabase Project Setup](#supabase-project-setup)
3. [Database Schema](#database-schema)
4. [Row Level Security Policies](#row-level-security-policies)
5. [Auth Configuration](#auth-configuration)
6. [Edge Functions](#edge-functions)
7. [Environment Variables](#environment-variables)
8. [Desktop App Auth Flow](#desktop-app-auth-flow)
9. [Website Integration](#website-integration)
10. [Subscription & Payment Flow](#subscription--payment-flow)
11. [Future-Proofing for Pricing Tiers](#future-proofing-for-pricing-tiers)
12. [Testing Checklist](#testing-checklist)
13. [Rollback Plan](#rollback-plan)

---

## Overview

This phase sets up the Supabase project that serves as the backend for both the desktop app and website. It includes:

- PostgreSQL database with all necessary tables
- Row Level Security (RLS) so users can only access their own data
- Auth with email/password and Google OAuth
- Edge Functions for Stripe webhook processing
- A foundation that supports the current $1.99 one-time payment AND future subscription tiers

**Estimated effort:** 1–2 days

**What you'll have at the end:** A fully functional backend that the desktop app can authenticate against, sync settings from, and push session data to. The web dashboard can read all this data.

---

## Supabase Project Setup

### Step 1: Create Supabase Project

1. Go to [supabase.com](https://supabase.com) and sign in (or create an account)
2. Click "New Project"
3. Project name: `braindock`
4. Database password: Generate a strong password and **save it securely**
5. Region: Choose closest to your primary user base (e.g., `ap-southeast-2` for Australia)
6. Plan: Free tier (upgrade to Pro at $25/month when needed)

### Step 2: Note Your Project Credentials

After creation, go to **Settings → API** and note:
- **Project URL:** `https://<project-id>.supabase.co`
- **Anon (public) key:** Used in website and desktop app for client-side operations
- **Service role key:** Used ONLY in Edge Functions (server-side, never expose to clients)

### Step 3: Enable Required Auth Providers

Go to **Authentication → Providers**:
- **Email:** Already enabled by default. Ensure "Confirm email" is ON for production (disable for development/testing)
- **Google:** Enable and configure (see [Auth Configuration](#auth-configuration) below)

---

## Database Schema

Run this SQL in **Supabase → SQL Editor → New Query**. Execute each section in order.

### Users Profile Table

```sql
-- Extends Supabase auth.users with app-specific profile data
-- Supabase Auth already handles email, password hashing, OAuth tokens
CREATE TABLE public.profiles (
    id UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
    email TEXT NOT NULL,
    display_name TEXT,
    avatar_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-create profile when user signs up
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, display_name, avatar_url)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name', split_part(NEW.email, '@', 1)),
        NEW.raw_user_meta_data->>'avatar_url'
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
```

### Subscription Tiers Table (Future-Proof)

> **IMPORTANT: This table MUST be created BEFORE the `subscriptions` table below, because `subscriptions` has a foreign key referencing `subscription_tiers(id)`.**

```sql
-- Defines available pricing tiers
-- Start with one tier (the current $1.99 one-time), add more later
CREATE TABLE public.subscription_tiers (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,              -- e.g., 'starter', 'pro', 'unlimited'
    display_name TEXT NOT NULL,      -- e.g., 'Starter Plan', 'Pro Plan'
    price_cents INTEGER NOT NULL,    -- Price in cents (199 = $1.99)
    currency TEXT NOT NULL DEFAULT 'aud',
    billing_interval TEXT,           -- 'one_time', 'monthly', 'yearly', NULL for free
    stripe_price_id TEXT,            -- Stripe Price ID for this tier
    
    -- Feature flags (what this tier unlocks)
    features JSONB DEFAULT '{}',
    -- Example: {"max_sessions_per_day": 10, "screen_monitoring": true, "camera_monitoring": true}
    
    is_active BOOLEAN DEFAULT TRUE,  -- Can be purchased (set false to retire a tier)
    sort_order INTEGER DEFAULT 0,    -- Display ordering
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed with current pricing (one-time $1.99 AUD)
INSERT INTO public.subscription_tiers (name, display_name, price_cents, currency, billing_interval, stripe_price_id, features, sort_order)
VALUES (
    'starter',
    'BrainDock Starter',
    199,
    'aud',
    'one_time',
    NULL,  -- Set this to your actual Stripe Price ID
    '{"camera_monitoring": true, "screen_monitoring": true, "pdf_reports": true, "max_daily_hours": 2}',
    1
);
```

### Subscriptions Table

```sql
-- Tracks user payment/subscription status
-- Supports current one-time payment AND future subscription tiers
CREATE TABLE public.subscriptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
    
    -- Current tier (references subscription_tiers table)
    tier_id UUID REFERENCES public.subscription_tiers(id),
    
    -- Stripe identifiers
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,  -- NULL for one-time payments
    stripe_payment_intent TEXT,   -- For one-time payments
    stripe_session_id TEXT,       -- Checkout session ID
    
    -- Status: 'active', 'cancelled', 'past_due', 'trialing', 'expired'
    status TEXT NOT NULL DEFAULT 'active',
    
    -- For subscription tiers (NULL for one-time payments)
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id)  -- One active subscription per user
);
```

### Devices Table

```sql
-- Tracks which desktop apps are linked to which user accounts
CREATE TABLE public.devices (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
    machine_id TEXT NOT NULL,       -- SHA256 of hardware identifiers (from existing license_manager.py logic)
    device_name TEXT,               -- e.g., "John's MacBook Pro"
    os TEXT,                        -- 'darwin', 'win32', 'linux'
    app_version TEXT,               -- e.g., '1.1.0'
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id, machine_id)    -- One entry per device per user
);
```

### User Settings Table

```sql
-- User preferences synced to the desktop app on session start
CREATE TABLE public.user_settings (
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE PRIMARY KEY,
    
    -- Monitoring defaults
    monitoring_mode TEXT DEFAULT 'camera_only',  -- 'camera_only', 'screen_only', 'both'
    
    -- Gadget detection preferences (which gadgets count as distractions)
    -- Matches config.py GADGET_PRESETS keys
    enabled_gadgets JSONB DEFAULT '["phone"]',
    
    -- Vision provider preference
    vision_provider TEXT DEFAULT 'gemini',  -- 'gemini' or 'openai'
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-create settings when profile is created
CREATE OR REPLACE FUNCTION public.handle_new_profile()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.user_settings (user_id) VALUES (NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_profile_created
    AFTER INSERT ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_profile();
```

### Blocklist Configuration Table

```sql
-- User's blocklist settings (which sites/apps to block)
-- Synced to desktop app on session start
CREATE TABLE public.blocklist_configs (
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE PRIMARY KEY,
    
    -- Quick-toggle sites (matches screen/blocklist.py QUICK_SITES)
    quick_blocks JSONB DEFAULT '{}',
    -- Example: {"instagram": true, "youtube": false, "netflix": true, ...}
    
    -- Category toggles (matches screen/blocklist.py PRESET_CATEGORIES)
    categories JSONB DEFAULT '{}',
    -- Example: {"social_media": true, "video_streaming": false, ...}
    
    -- Custom URLs and apps added by user
    custom_urls JSONB DEFAULT '[]',    -- ["example.com", "timewaster.io"]
    custom_apps JSONB DEFAULT '[]',    -- ["Discord", "Steam"]
    
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-create blocklist config when profile is created
CREATE OR REPLACE FUNCTION public.handle_new_blocklist()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.blocklist_configs (user_id) VALUES (NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_profile_created_blocklist
    AFTER INSERT ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_blocklist();
```

### Sessions Table

```sql
-- Session data pushed from desktop app after session ends
CREATE TABLE public.sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
    device_id UUID REFERENCES public.devices(id) ON DELETE SET NULL,
    
    -- Session identifiers
    session_name TEXT,              -- Human-readable ID (e.g., "BrainDock Monday 2.45PM")
    
    -- Timing
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    duration_seconds INTEGER NOT NULL,
    active_seconds INTEGER NOT NULL,  -- Excluding paused time
    paused_seconds INTEGER DEFAULT 0,
    
    -- Mode used
    monitoring_mode TEXT NOT NULL,  -- 'camera_only', 'screen_only', 'both'
    
    -- Summary statistics (computed by tracking/analytics.py on the client)
    summary_stats JSONB DEFAULT '{}',
    -- Example: {
    --   "present_seconds": 1200,
    --   "away_seconds": 300,
    --   "gadget_seconds": 60,
    --   "screen_distraction_seconds": 120,
    --   "paused_seconds": 180,
    --   "focus_percentage": 78.5,
    --   "gadget_count": 3,
    --   "screen_distraction_count": 5
    -- }
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for efficient user session queries
CREATE INDEX idx_sessions_user_id ON public.sessions(user_id);
CREATE INDEX idx_sessions_start_time ON public.sessions(start_time DESC);
```

### Session Events Table

```sql
-- Individual events within a session (optional — for detailed history on web dashboard)
CREATE TABLE public.session_events (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id UUID REFERENCES public.sessions(id) ON DELETE CASCADE NOT NULL,
    
    event_type TEXT NOT NULL,  -- 'present', 'away', 'gadget_suspected', 'screen_distraction', 'paused'
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    duration_seconds FLOAT,
    
    -- Optional metadata
    metadata JSONB DEFAULT '{}'
    -- For screen_distraction: {"source": "youtube.com", "app": "Chrome"}
    -- For gadget_suspected: {"type": "phone", "confidence": 0.85}
);

-- Index for efficient session event queries
CREATE INDEX idx_session_events_session_id ON public.session_events(session_id);
```

### Updated At Trigger

```sql
-- Generic trigger to auto-update updated_at columns
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply to tables with updated_at
CREATE TRIGGER update_profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER update_subscriptions_updated_at
    BEFORE UPDATE ON public.subscriptions
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER update_user_settings_updated_at
    BEFORE UPDATE ON public.user_settings
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER update_blocklist_configs_updated_at
    BEFORE UPDATE ON public.blocklist_configs
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
```

---

## Row Level Security Policies

**Critical:** Enable RLS on ALL tables. Without it, any authenticated user can read/modify any user's data.

```sql
-- Enable RLS on all tables
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscription_tiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.blocklist_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.session_events ENABLE ROW LEVEL SECURITY;

-- Profiles: Users can read/update their own profile
CREATE POLICY "Users can read own profile" ON public.profiles
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can update own profile" ON public.profiles
    FOR UPDATE USING (auth.uid() = id);

-- Subscriptions: Users can read their own subscription
CREATE POLICY "Users can read own subscription" ON public.subscriptions
    FOR SELECT USING (auth.uid() = user_id);

-- Subscription tiers: Readable by all roles (pricing is public info)
-- This intentionally allows both anon and authenticated access.
-- If you want to restrict to authenticated users only, add: TO authenticated
CREATE POLICY "Anyone can read active tiers" ON public.subscription_tiers
    FOR SELECT USING (is_active = TRUE);

-- Devices: Users can manage their own devices
CREATE POLICY "Users can read own devices" ON public.devices
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own devices" ON public.devices
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own devices" ON public.devices
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own devices" ON public.devices
    FOR DELETE USING (auth.uid() = user_id);

-- User Settings: Users can manage their own settings
CREATE POLICY "Users can read own settings" ON public.user_settings
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can update own settings" ON public.user_settings
    FOR UPDATE USING (auth.uid() = user_id);

-- Blocklist: Users can manage their own blocklist
CREATE POLICY "Users can read own blocklist" ON public.blocklist_configs
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can update own blocklist" ON public.blocklist_configs
    FOR UPDATE USING (auth.uid() = user_id);

-- Sessions: Users can read and insert their own sessions
CREATE POLICY "Users can read own sessions" ON public.sessions
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own sessions" ON public.sessions
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Session Events: Users can read and insert events for their sessions
CREATE POLICY "Users can read own session events" ON public.session_events
    FOR SELECT USING (
        session_id IN (SELECT id FROM public.sessions WHERE user_id = auth.uid())
    );

CREATE POLICY "Users can insert own session events" ON public.session_events
    FOR INSERT WITH CHECK (
        session_id IN (SELECT id FROM public.sessions WHERE user_id = auth.uid())
    );
```

---

## Auth Configuration

### Email/Password Auth

Supabase email auth is enabled by default. Configuration:

1. **Supabase Dashboard → Authentication → Email Templates**
   - Customize the confirmation email with BrainDock branding
   - Customize the password reset email

2. **Supabase Dashboard → Authentication → URL Configuration**
   - Set **Site URL** to your website URL (e.g., `https://braindock.com`)
   - Add **Redirect URLs**: `https://braindock.com/auth/callback`, `https://braindock.com/dashboard`

### Google OAuth Setup

1. **Google Cloud Console** → Create a new project (or use existing)
2. **APIs & Services → OAuth consent screen**
   - App name: BrainDock
   - Support email: your email
   - Authorized domains: your website domain
3. **APIs & Services → Credentials → Create OAuth 2.0 Client ID**
   - Application type: Web application
   - Authorized redirect URIs: `https://<your-project-id>.supabase.co/auth/v1/callback`
   - Note the **Client ID** and **Client Secret**
4. **Supabase Dashboard → Authentication → Providers → Google**
   - Enable Google provider
   - Paste Client ID and Client Secret
   - Save

### Auth Flow for Desktop App

The desktop app authenticates via a **manual code entry** flow (recommended for simplicity and security):

1. User clicks "Log In" in the menu bar app
2. App opens `https://braindock.com/auth/login?source=desktop` in default browser
3. User logs in on the website (email/password or Google)
4. Website displays a short-lived linking code (e.g., "ABCD-1234")
5. User enters the code in the desktop app's "Enter login code" prompt
6. Desktop app exchanges the code for Supabase session tokens via a secure API call
7. Tokens stored securely in user data directory (platform-specific, via `config.USER_DATA_DIR / "auth.json"`)
8. Supabase Python client handles automatic token refresh

This approach is similar to how Spotify, Netflix, and smart TV apps handle device linking. It's the most reliable (no custom URL schemes, no localhost servers, no firewall issues) and the most secure (tokens never pass through URLs where they could be logged in browser history).

**Alternative (simpler but limited):** The desktop app has a minimal email/password form. User types credentials, the Supabase Python client authenticates directly. No browser redirect needed. This is simpler to implement but doesn't support Google OAuth from the desktop. Users who signed up with Google would need to set a password first.

**Recommended approach for Phase 2:** Start with the manual code entry flow. It supports all auth methods, is the most secure, and requires zero platform-specific configuration. See `03-WEB-DASHBOARD-MIGRATION.md` → "Desktop App Deep Linking" for all three options evaluated.

### Linking Code Infrastructure (Required for Manual Code Entry)

The manual code entry flow requires a server-side mechanism to generate and validate short-lived codes. Add this table and Edge Function:

```sql
-- Temporary linking codes for desktop app authentication
-- Codes expire after 5 minutes and are single-use
CREATE TABLE public.linking_codes (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    code TEXT NOT NULL UNIQUE,          -- Short code like "ABCD-1234"
    access_token TEXT NOT NULL,         -- Supabase session access token
    refresh_token TEXT NOT NULL,        -- Supabase session refresh token
    expires_at TIMESTAMPTZ NOT NULL,    -- Auto-expire after 5 minutes
    used BOOLEAN DEFAULT FALSE,         -- Single-use: mark used after exchange
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS: No client-side access — only Edge Functions use this table via service role
ALTER TABLE public.linking_codes ENABLE ROW LEVEL SECURITY;
-- No SELECT/INSERT policies for anon/authenticated roles (intentional)
-- Only the service role key (Edge Functions) can read/write this table

-- Cleanup: Delete expired or used codes older than 1 hour
-- Run this periodically (manually, or via pg_cron if on Supabase Pro)
CREATE OR REPLACE FUNCTION public.cleanup_expired_linking_codes()
RETURNS void AS $$
BEGIN
    DELETE FROM public.linking_codes
    WHERE used = TRUE
       OR expires_at < NOW() - INTERVAL '1 hour';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- To run manually: SELECT public.cleanup_expired_linking_codes();
-- To schedule on Supabase Pro (pg_cron): 
--   SELECT cron.schedule('cleanup-linking-codes', '0 * * * *', 'SELECT public.cleanup_expired_linking_codes()');
```

**Edge Function: Generate linking code** (called by the website after login with `?source=desktop`):

> **Note:** This function is called from the website (browser), so it needs CORS headers to handle preflight requests. It also requires a valid Supabase JWT — deploy WITHOUT `--no-verify-jwt`.

```typescript
// supabase/functions/generate-linking-code/index.ts
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req) => {
  // Handle CORS preflight (browsers send OPTIONS before POST)
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  const { access_token, refresh_token } = await req.json();
  
  // Verify the token is valid
  const userClient = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_ANON_KEY")!
  );
  const { data: { user }, error } = await userClient.auth.getUser(access_token);
  if (error || !user) {
    return new Response(JSON.stringify({ error: "Invalid token" }), {
      status: 401,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
  
  // Generate a short, human-friendly code
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // No 0/O/1/I to avoid confusion
  let code = "";
  for (let i = 0; i < 8; i++) {
    code += chars[Math.floor(Math.random() * chars.length)];
    if (i === 3) code += "-"; // Format: ABCD-1234
  }
  
  const adminClient = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );
  
  // Store the code (expires in 5 minutes)
  await adminClient.from("linking_codes").insert({
    user_id: user.id,
    code,
    access_token,
    refresh_token,
    expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
  });
  
  return new Response(JSON.stringify({ code }), {
    status: 200,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
});
```

**Edge Function: Exchange linking code** (called by the desktop app):

> **Note:** This function is called by the desktop app which has NO auth token yet (that's what it's trying to get). Deploy with `--no-verify-jwt`. CORS headers included for consistency, though the Python desktop client doesn't require them.

```typescript
// supabase/functions/exchange-linking-code/index.ts
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req) => {
  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  const { code } = await req.json();
  
  const adminClient = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );
  
  // Find valid, unused, non-expired code
  const { data, error } = await adminClient
    .from("linking_codes")
    .select("access_token, refresh_token, user_id")
    .eq("code", code.toUpperCase().trim())
    .eq("used", false)
    .gt("expires_at", new Date().toISOString())
    .single();
  
  if (error || !data) {
    return new Response(
      JSON.stringify({ error: "Invalid or expired code" }),
      { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
  
  // Mark code as used (single-use)
  await adminClient
    .from("linking_codes")
    .update({ used: true })
    .eq("code", code.toUpperCase().trim());
  
  return new Response(JSON.stringify({
    access_token: data.access_token,
    refresh_token: data.refresh_token,
  }), {
    status: 200,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
});
```

Deploy both:
```bash
# generate-linking-code: called by authenticated website users (JWT verified by Supabase)
supabase functions deploy generate-linking-code

# exchange-linking-code: called by desktop app with NO token yet — must skip JWT verification
supabase functions deploy exchange-linking-code --no-verify-jwt
```

---

## Edge Functions

### Stripe Webhook Handler

This Edge Function receives Stripe webhook events and updates the `subscriptions` table.

**Create:** `supabase/functions/stripe-webhook/index.ts`

> **Note:** This function is called server-to-server by Stripe (no browser, no Supabase JWT). Deploy with `--no-verify-jwt`. No CORS headers needed.

```typescript
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import Stripe from "https://esm.sh/stripe@14?target=deno";

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY")!, { apiVersion: "2023-10-16" });
const endpointSecret = Deno.env.get("STRIPE_WEBHOOK_SECRET")!;

Deno.serve(async (req) => {
  const signature = req.headers.get("stripe-signature")!;
  const body = await req.text();

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(body, signature, endpointSecret);
  } catch (err) {
    return new Response(`Webhook Error: ${err.message}`, { status: 400 });
  }

  // Create Supabase admin client (bypasses RLS)
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );

  switch (event.type) {
    case "checkout.session.completed": {
      const session = event.data.object as Stripe.Checkout.Session;
      const email = session.customer_email || session.customer_details?.email;

      if (!email) break;

      // Find user by email
      const { data: profile } = await supabase
        .from("profiles")
        .select("id")
        .eq("email", email)
        .single();

      if (!profile) break;

      // Get the starter tier
      const { data: tier } = await supabase
        .from("subscription_tiers")
        .select("id")
        .eq("name", "starter")
        .single();

      // Upsert subscription
      await supabase.from("subscriptions").upsert({
        user_id: profile.id,
        tier_id: tier?.id,
        stripe_customer_id: session.customer as string,
        stripe_session_id: session.id,
        stripe_payment_intent: session.payment_intent as string,
        status: "active",
      }, { onConflict: "user_id" });

      break;
    }

    // Future: handle subscription events
    // case "customer.subscription.updated":
    // case "customer.subscription.deleted":
    // case "invoice.payment_failed":
  }

  return new Response(JSON.stringify({ received: true }), { status: 200 });
});
```

### Session Sync Endpoint (Optional)

If you want a server-side endpoint for session upload instead of direct client writes:

```typescript
// supabase/functions/sync-session/index.ts
// For now, direct client writes via Supabase Python client are sufficient.
// This Edge Function is only needed if you want server-side validation
// of session data before it's stored.
// SKIP THIS for initial implementation — add later if needed.
```

### Deploying Edge Functions

```bash
# Install Supabase CLI (macOS — use npm on other platforms: npm install -g supabase)
brew install supabase/tap/supabase

# Login
supabase login

# Initialize Supabase in the repo (creates supabase/ directory)
supabase init

# Link to your project
supabase link --project-ref <your-project-id>

# Set secrets (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are auto-available)
supabase secrets set STRIPE_SECRET_KEY=sk_live_...
supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_...

# Deploy all three functions
# stripe-webhook: Stripe calls this server-to-server (no Supabase JWT)
supabase functions deploy stripe-webhook --no-verify-jwt

# generate-linking-code: called by authenticated website users (JWT verified)
supabase functions deploy generate-linking-code

# exchange-linking-code: desktop app has no token yet (that's what it's getting)
supabase functions deploy exchange-linking-code --no-verify-jwt
```

> **Why `--no-verify-jwt`?** By default, Supabase Edge Functions reject requests without a valid Supabase JWT in the `Authorization` header. `stripe-webhook` is called by Stripe (no JWT), and `exchange-linking-code` is called by the desktop app before it has a token. `generate-linking-code` is called by an already-authenticated website user, so it keeps JWT verification enabled.

### Configure Stripe Webhook

1. Go to **Stripe Dashboard → Developers → Webhooks**
2. Add endpoint: `https://<your-project-id>.supabase.co/functions/v1/stripe-webhook`
3. Select events: `checkout.session.completed` (add more later for subscriptions)
4. Note the **Signing secret** (`whsec_...`) and set it as `STRIPE_WEBHOOK_SECRET`

---

## Environment Variables

### Supabase Dashboard Secrets (Edge Functions)

Set via `supabase secrets set`:

| Variable | Value | Where |
|----------|-------|-------|
| `STRIPE_SECRET_KEY` | `sk_live_...` | Stripe Dashboard → API Keys |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` | Stripe Dashboard → Webhooks → Signing secret |

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are automatically available in Edge Functions.

### Desktop App `.env` (or bundled config)

| Variable | Value | Purpose |
|----------|-------|---------|
| `SUPABASE_URL` | `https://<project-id>.supabase.co` | Supabase API endpoint |
| `SUPABASE_ANON_KEY` | `eyJ...` | Public anon key (safe to embed in app) |
| `GEMINI_API_KEY` | `AI...` | Vision API (unchanged) |
| `OPENAI_API_KEY` | `sk-...` | Vision API (unchanged) |

**Note:** The Supabase anon key is safe to embed in the desktop app. It only grants access that RLS policies allow (user's own data). The service role key is NEVER used in the desktop app.

### Website `.env`

> **Note:** The variable names below use `NEXT_PUBLIC_` prefix (Next.js convention for client-exposed vars). If your website uses a different framework, adjust the prefix accordingly — e.g., `VITE_` for Vite/SvelteKit, `NUXT_PUBLIC_` for Nuxt, or no prefix for server-only variables. The actual values are the same regardless of framework.

| Variable | Value | Purpose |
|----------|-------|---------|
| `NEXT_PUBLIC_SUPABASE_URL` (or your framework's equivalent) | `https://<project-id>.supabase.co` | Client-side Supabase |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` (or equivalent) | `eyJ...` | Client-side auth |
| `STRIPE_SECRET_KEY` | `sk_live_...` | Server-side Stripe (for creating checkout sessions) |
| `STRIPE_PUBLISHABLE_KEY` | `pk_live_...` | Client-side Stripe.js |

---

## Desktop App Auth Flow

This describes how the desktop app will authenticate — implemented in Phase 2, but the backend (this phase) must support it.

### Flow (Manual Code Entry — Recommended)

```
User clicks "Log In" in menu bar
    ↓
App opens browser to: https://braindock.com/auth/login?source=desktop
    ↓
User logs in (email/password or Google OAuth)
    ↓
Website generates a short-lived linking code (e.g., "ABCD-1234")
    ↓
Website displays: "Enter this code in BrainDock: ABCD-1234"
    ↓
User types the code into the desktop app's prompt
    ↓
Desktop app sends code to Supabase Edge Function → receives session tokens
    ↓
App stores tokens in config.USER_DATA_DIR / "auth.json"
    ↓
App initializes Supabase Python client with stored tokens
    ↓
On subsequent launches: app reads stored tokens, Supabase client auto-refreshes
```

### Token Storage Format

```json
{
    "access_token": "eyJ...",
    "refresh_token": "eyJ...",
    "user_id": "uuid-here",
    "email": "user@example.com",
    "expires_at": 1700000000
}
```

### Checking Subscription Status

The desktop app checks if the user has an active subscription:

```python
# Pseudocode for Phase 2 implementation
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
supabase.auth.set_session(access_token, refresh_token)

# Check subscription — no need to filter by user_id explicitly.
# Supabase RLS automatically scopes queries to the authenticated user
# via auth.uid(). Adding .eq("user_id", user_id) would be redundant.
result = supabase.table("subscriptions") \
    .select("status, subscription_tiers(name, features)") \
    .eq("status", "active") \
    .single() \
    .execute()

is_paid = result.data is not None
```

> **Note for agents:** All Supabase client queries from the desktop app are automatically scoped to the authenticated user by Row Level Security (RLS) policies. You do NOT need to manually filter by `user_id` in client-side queries — RLS does this via `auth.uid()`. The service role key (used only in Edge Functions) bypasses RLS and must filter explicitly.

---

## Website Integration

The website (separate repo) connects to the same Supabase project:

### JavaScript Client Setup

```javascript
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
)
```

### Key Operations the Website Performs

| Operation | Supabase Call | Table |
|-----------|-------------|-------|
| Sign up | `supabase.auth.signUp()` | `auth.users` → triggers `profiles` creation |
| Log in | `supabase.auth.signInWithPassword()` | `auth.users` |
| Google OAuth | `supabase.auth.signInWithOAuth({ provider: 'google' })` | `auth.users` |
| Read settings | `supabase.from('user_settings').select()` | `user_settings` |
| Update blocklist | `supabase.from('blocklist_configs').update(...)` | `blocklist_configs` |
| View sessions | `supabase.from('sessions').select().order('start_time', { ascending: false })` | `sessions` |
| View subscription | `supabase.from('subscriptions').select('*, subscription_tiers(*)')` | `subscriptions` + `subscription_tiers` |
| Manage devices | `supabase.from('devices').select()` / `.delete()` | `devices` |

---

## Subscription & Payment Flow

### Current Flow (One-Time $1.99)

```
User signs up on website → No subscription yet
    ↓
User clicks "Pay $1.99" → Website creates Stripe Checkout session
    ↓
User completes payment on Stripe
    ↓
Stripe sends webhook → Edge Function updates subscriptions table (status: 'active')
    ↓
Desktop app checks subscription → sees 'active' → unlocks full access
```

### How It Maps to Existing Licensing

Currently, `licensing/license_manager.py` stores a local `license.json` with machine-bound licensing. In the new model:

- **License validation moves to Supabase.** The desktop app checks `subscriptions` table instead of local `license.json`
- **Machine binding becomes device registration.** The `devices` table links machines to user accounts
- **The 2-hour MVP usage limit stays.** `tracking/usage_limiter.py` continues working locally — it doesn't need to know about cloud subscriptions. It just limits time per day regardless of subscription status
- **The unlock password flow stays.** Same local behavior, unchanged

### Checking Access in Desktop App

```python
def check_user_access(supabase_client, user_id: str) -> dict:
    """
    Check if user has access to the app.
    
    Returns:
        {"has_access": bool, "tier": str, "reason": str}
    """
    result = supabase_client.table("subscriptions") \
        .select("status, subscription_tiers(name, features)") \
        .eq("user_id", user_id) \
        .single() \
        .execute()
    
    if not result.data:
        return {"has_access": False, "tier": "free", "reason": "no_subscription"}
    
    if result.data["status"] != "active":
        return {"has_access": False, "tier": "expired", "reason": f"status_{result.data['status']}"}
    
    tier = result.data.get("subscription_tiers", {})
    return {"has_access": True, "tier": tier.get("name", "starter"), "reason": "active"}
```

---

## Future-Proofing for Pricing Tiers

The `subscription_tiers` table is designed so adding new pricing tiers requires **zero code changes** in the desktop app:

### Adding a New Tier (Example: Monthly Pro)

```sql
INSERT INTO public.subscription_tiers (name, display_name, price_cents, currency, billing_interval, stripe_price_id, features, sort_order)
VALUES (
    'pro',
    'BrainDock Pro',
    999,
    'aud',
    'monthly',
    'price_abc123',  -- Create this in Stripe Dashboard first
    '{"camera_monitoring": true, "screen_monitoring": true, "pdf_reports": true, "max_daily_hours": null, "priority_support": true}',
    2
);
```

### Adding a Free Tier

```sql
INSERT INTO public.subscription_tiers (name, display_name, price_cents, currency, billing_interval, features, sort_order)
VALUES (
    'free',
    'BrainDock Free',
    0,
    'aud',
    NULL,  -- No billing
    '{"camera_monitoring": true, "screen_monitoring": false, "pdf_reports": false, "max_daily_hours": 1}',
    0
);
```

The desktop app reads `features` from the user's active tier and enforces limits locally. The website reads `subscription_tiers` to display pricing page. No code changes needed — just database rows.

### Handling Subscription Lifecycle (Future)

When you add recurring subscriptions, add these Stripe webhook events to the Edge Function:

- `customer.subscription.updated` → Update `subscriptions.status` and `current_period_end`
- `customer.subscription.deleted` → Set `subscriptions.status = 'cancelled'`
- `invoice.payment_failed` → Set `subscriptions.status = 'past_due'`

The Edge Function switch statement already has placeholder comments for these.

---

## Testing Checklist

### Auth

- [ ] Create account with email/password — profile auto-created in `profiles` table
- [ ] Create account with Google OAuth — profile auto-created with name and avatar
- [ ] Log in with email/password — returns valid session tokens
- [ ] Log in with Google — returns valid session tokens
- [ ] Password reset email sends correctly
- [ ] Token refresh works (wait for access token expiry, verify refresh succeeds)

### Database & RLS

- [ ] User A cannot read User B's profile, settings, sessions, or subscription
- [ ] User can read their own data from all tables
- [ ] User can update their own settings and blocklist
- [ ] User can insert their own sessions and events
- [ ] User cannot modify their own subscription (only Edge Functions can, via service role)
- [ ] Subscription tiers are readable by all authenticated users

### Stripe Integration

- [ ] Stripe webhook endpoint receives events correctly
- [ ] `checkout.session.completed` creates/updates subscription in database
- [ ] Subscription status is 'active' after successful payment
- [ ] Desktop app can query subscription status and get correct result

### Edge Functions

- [ ] `stripe-webhook` deploys successfully
- [ ] Stripe test webhook (from Stripe Dashboard → Test webhook) is processed correctly
- [ ] Invalid webhook signature is rejected (returns 400)

---

## Rollback Plan

This phase adds new infrastructure alongside the existing app. Nothing is removed or broken.

**If something goes wrong:**
1. The existing desktop app continues working exactly as before (local licensing, no Supabase dependency)
2. Supabase project can be deleted/recreated without affecting any existing users
3. Stripe webhook can be disabled in Stripe Dashboard without affecting existing payment flow

**There is no rollback needed for this phase** because it's purely additive. The existing app is not modified.
