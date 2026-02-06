# Phase 3: Web Dashboard Migration

> **Prerequisites:**
> - Read `00-MIGRATION-OVERVIEW.md` for full context
> - Phase 1 (Backend & Auth) must be **complete and tested**
> - Phase 2 (Desktop App) should ideally be **complete** (or at least the engine extraction done) so that session data is flowing to Supabase
>
> **This phase is the LOWEST-RISK piece.** It's purely additive — building new web pages that read from the Supabase database. Nothing in the desktop app or backend is modified.

---

## Table of Contents

1. [Overview](#overview)
2. [What's Being Moved from Desktop to Web](#whats-being-moved-from-desktop-to-web)
3. [Design Guidelines](#design-guidelines)
4. [Pages to Build](#pages-to-build)
5. [Supabase Client Integration](#supabase-client-integration)
6. [Auth Pages](#auth-pages)
7. [Dashboard Page](#dashboard-page)
8. [Settings Pages](#settings-pages)
9. [Session History Page](#session-history-page)
10. [Subscription & Payment Page](#subscription--payment-page)
11. [Device Management](#device-management)
12. [How to Use / Tutorial Page](#how-to-use--tutorial-page)
13. [Desktop App Deep Linking](#desktop-app-deep-linking)
14. [Testing Checklist](#testing-checklist)

---

## Overview

This phase builds the web dashboard that replaces the desktop app's UI for everything beyond starting/stopping sessions. The website is in a **separate repo** and connects to the same Supabase backend as the desktop app.

**What this phase creates:**
- Account signup/login pages (email + Google OAuth)
- Dashboard with daily/weekly stats (replaces the 3 stat cards removed from desktop)
- Settings pages for blocklist, gadget preferences, monitoring mode
- Session history with detail views
- Subscription management and payment page
- Device management (linked desktop apps)
- Tutorial/How-to-use page

**Estimated effort:** 2–3 days (with existing website infrastructure)

**What you'll have at the end:** A complete web experience where users manage everything about BrainDock except the actual tracking (which runs on their local machine).

---

## What's Being Moved from Desktop to Web

### From gui/app.py (6,681 lines)

| Desktop Feature | Desktop Lines | Web Page | Notes |
|----------------|---------------|----------|-------|
| Daily stats cards (Focus, Distractions, Focus Rate) | ~200 lines (cards + update logic) | **Dashboard** | Enhanced: show history, trends, weekly view |
| Settings popup (blocklist management) | ~600 lines | **Settings → Blocklist** | Same functionality, better UI |
| Gadget detection preferences | ~100 lines (within settings) | **Settings → Detection** | Toggle which gadgets count |
| Tutorial popup | ~275 lines | **How to Use** page | Static content, can be richer on web |
| Mode selector (Camera/Screen/Both) | ~80 lines | **Settings → General** | Default mode (overridable from menu bar) |

### From gui/payment_screen.py (1,456 lines)

| Desktop Feature | Desktop Lines | Web Page | Notes |
|----------------|---------------|----------|-------|
| Payment screen | ~1,000 lines (UI) | **Pricing / Subscribe** page | Standard Stripe Checkout on web |
| Local payment server | ~200 lines | **DELETE** | No longer needed — web-native payment |
| Payment polling | ~150 lines | **DELETE** | Stripe webhook → Supabase handles this |

### From gui/ui_components.py (1,396 lines)

| Desktop Feature | Web Equivalent |
|----------------|---------------|
| `ScalingManager` | CSS responsive design (native) |
| `RoundedButton` | CSS button styles |
| `Card` | CSS card component |
| `StyledEntry` | HTML `<input>` with CSS |
| `NaturalScroller` | Native browser scrolling |
| Color constants (`COLORS` dict) | CSS variables |
| Font constants (`FONTS` dict) | CSS `@font-face` + variables |

---

## Design Guidelines

The website should follow the same **"Seraphic Focus"** design language defined in `planning/design_guidelines.json`. Here's the reference:

### Color Palette (CSS Variables)

```css
:root {
    /* Backgrounds */
    --bg-primary: #F9F8F4;
    --bg-secondary: #F2F0EB;
    --bg-surface: #FFFFFF;
    --bg-overlay: rgba(255, 255, 255, 0.9);
    
    /* Text */
    --text-primary: #1C1C1E;
    --text-secondary: rgba(60, 60, 67, 0.6);  /* #3C3C4399 */
    --text-tertiary: rgba(60, 60, 67, 0.3);   /* #3C3C434D */
    --text-inverse: #FFFFFF;
    
    /* Accents */
    --accent-primary: #2C3E50;
    --accent-highlight: #D4A373;
    --accent-success: #34C759;
    --accent-warning: #FF9500;
    --accent-error: #FF3B30;
    
    /* Borders */
    --border-subtle: #E5E5EA;
    --border-focus: #1C1C1E;
    
    /* Status colors (from desktop app) */
    --status-focused: #059669;     /* Emerald green */
    --status-away: #C4841D;        /* Warm amber */
    --status-gadget: #DC2626;      /* Clear red */
    --status-screen: #7C3AED;      /* Purple */
    --status-paused: #6B7280;      /* Neutral grey */
    --status-idle: #9CA3AF;        /* Light grey */
}
```

### Typography

```css
/* Display font: Serif for headings, stats, focus statements */
--font-display: 'Lora', Georgia, 'Times New Roman', serif;

/* Interface font: Sans-serif for buttons, labels, data */
--font-interface: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
```

| Level | Size | Weight | Font | Usage |
|-------|------|--------|------|-------|
| h1 | 32px | 700 | Display (Serif) | Page titles |
| h2 | 24px | 600 | Display | Section headings |
| h3 | 20px | 600 | Interface (Sans) | Card titles |
| body-large | 18px | 400 | Display | Focus statements, summaries |
| body | 16px | 400 | Interface | General text |
| caption | 13px | 500 | Interface | Labels, metadata (uppercase, letter-spacing: 0.05em) |

### Component Styles

```css
/* Buttons */
.btn-primary {
    background: #1C1C1E;
    color: #FFFFFF;
    border-radius: 30px;
    padding: 16px 32px;
    font-family: var(--font-interface);
    font-weight: 600;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.btn-secondary {
    background: transparent;
    color: #1C1C1E;
    border: 2px solid #E5E5EA;
    border-radius: 30px;
    padding: 14px 30px;
}

/* Cards */
.card {
    background: #FFFFFF;
    border-radius: 20px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.04);
    padding: 24px;
    border: 1px solid rgba(0, 0, 0, 0.02);
}

/* Inputs */
.input {
    background: #F2F0EB;
    border-radius: 12px;
    border: none;
    padding: 16px;
    color: #1C1C1E;
}

/* Modals */
.modal-overlay { background: rgba(0, 0, 0, 0.4); }
.modal {
    background: #FFFFFF;
    border-radius: 24px;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
}
```

### Design Principles

From `design_guidelines.json`:
- **"A calm, intellectual and airy interface that mimics the clarity of a printed page"**
- Use whitespace to group elements (not lines or boxes)
- Generous spacing: base unit 4px, scale: 4/8/16/24/32/48px
- Max content width: 1200px, text width: 680px
- Icons: Line/stroke style, 2px weight, rounded
- No gamification clutter
- Minimalist, typographic, paper-like, distraction-free

---

## Pages to Build

### Site Map

```
braindock.com/
├── /                           # Landing page (already exists)
├── /auth/
│   ├── /login                  # Email/password + Google OAuth login
│   ├── /signup                 # Account creation
│   ├── /forgot-password        # Password reset
│   └── /callback               # OAuth callback handler
├── /dashboard                  # Main dashboard (daily stats, recent sessions)
├── /sessions/
│   ├── /                       # Session history list
│   └── /[id]                   # Individual session detail
├── /settings/
│   ├── /                       # General settings (mode, vision provider)
│   ├── /blocklist              # Blocklist configuration
│   ├── /detection              # Gadget detection preferences
│   └── /devices                # Linked devices management
├── /account/
│   ├── /                       # Profile settings
│   └── /subscription           # Subscription status + payment
├── /pricing                    # Pricing page (current + future tiers)
├── /how-to-use                 # Tutorial / getting started guide
└── /download                   # Download page for desktop app
```

---

## Supabase Client Integration

### Setup

```javascript
// lib/supabase.js (or wherever your client config lives)
import { createClient } from '@supabase/supabase-js'

export const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
)
```

### Auth Helpers

```javascript
// Sign up
const { data, error } = await supabase.auth.signUp({
    email: 'user@example.com',
    password: 'securepassword',
    options: {
        data: { full_name: 'John Doe' }  // Stored in raw_user_meta_data
    }
})

// Sign in with email/password
const { data, error } = await supabase.auth.signInWithPassword({
    email: 'user@example.com',
    password: 'securepassword'
})

// Sign in with Google
const { data, error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: {
        redirectTo: `${window.location.origin}/auth/callback`
    }
})

// Get current user
const { data: { user } } = await supabase.auth.getUser()

// Sign out
await supabase.auth.signOut()
```

### Data Access Patterns

```javascript
// Read user settings
const { data: settings } = await supabase
    .from('user_settings')
    .select('*')
    .single()

// Update blocklist
await supabase
    .from('blocklist_configs')
    .update({
        quick_blocks: { instagram: true, youtube: false, ... },
        categories: { social_media: true, ... },
        custom_urls: ['example.com'],
        custom_apps: ['Discord']
    })
    .eq('user_id', user.id)

// Read sessions (paginated, newest first)
const { data: sessions } = await supabase
    .from('sessions')
    .select('*')
    .order('start_time', { ascending: false })
    .range(0, 19)  // First 20 sessions

// Read session with events
const { data: session } = await supabase
    .from('sessions')
    .select('*, session_events(*)')
    .eq('id', sessionId)
    .single()

// Read subscription with tier info
const { data: subscription } = await supabase
    .from('subscriptions')
    .select('*, subscription_tiers(*)')
    .single()

// Read devices
const { data: devices } = await supabase
    .from('devices')
    .select('*')
    .order('last_seen', { ascending: false })
```

---

## Auth Pages

### /auth/login

- Email + password form
- "Sign in with Google" button (Supabase OAuth)
- "Forgot password?" link
- "Don't have an account? Sign up" link
- `?source=desktop` query param: after login, redirect to a page that sends auth tokens back to the desktop app

### /auth/signup

- Full name, email, password fields
- "Sign up with Google" button
- Terms of Service checkbox
- After signup, redirect to `/dashboard`

### /auth/callback

- Handles OAuth redirect from Google
- Processes auth tokens from URL hash
- If `source=desktop`, generates a token exchange for the desktop app
- Redirects to `/dashboard`

### /auth/forgot-password

- Email input
- Sends password reset email via Supabase
- Shows confirmation message

---

## Dashboard Page

### /dashboard

This is the main page users see after login. It replaces the three stat cards from the desktop app AND adds session history.

**Layout:**

```
┌─────────────────────────────────────────────────────────┐
│  BrainDock Dashboard                     [Settings ⚙]   │
│                                                         │
│  Welcome back, John                  Today, Feb 7 2026  │
│                                                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐       │
│  │   TODAY'S    │ │   TODAY'S   │ │   FOCUS     │       │
│  │   FOCUS      │ │ DISTRACTIONS│ │   RATE      │       │
│  │             │ │             │ │             │       │
│  │   2h 15m    │ │     7       │ │   84%       │       │
│  │  +30m vs    │ │  -2 vs     │ │  +5% vs     │       │
│  │  yesterday  │ │  yesterday  │ │  yesterday  │       │
│  └─────────────┘ └─────────────┘ └─────────────┘       │
│                                                         │
│  Recent Sessions                         [View All →]   │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Monday 2:45 PM  │ Camera  │ 45 min │ 92% focus │    │
│  │ Monday 10:00 AM │ Both    │ 1h 20m │ 78% focus │    │
│  │ Sunday 3:00 PM  │ Screen  │ 30 min │ 85% focus │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  This Week                                              │
│  [Simple bar chart showing daily focus hours]            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Data sources:**
- Today's stats: Aggregate from `sessions` table where `start_time` is today
- Recent sessions: `sessions` table, ordered by `start_time DESC`, limit 5
- Weekly chart: Aggregate `sessions` by day for last 7 days

**Calculations (from tracking/analytics.py — replicate in JS):**
- Focus time: `summary_stats.present_seconds` summed across today's sessions
- Distractions: `summary_stats.gadget_count + summary_stats.screen_distraction_count`
- Focus rate: `summary_stats.focus_percentage` averaged (weighted by session duration)

---

## Settings Pages

### /settings/ (General)

- **Default monitoring mode:** Radio buttons (Camera / Screen / Both)
  - This sets the default for the desktop app. Users can still override from the menu bar.
- **Vision provider:** Dropdown (Gemini / OpenAI)
  - With cost note: "Gemini is recommended (cheaper). OpenAI provides slightly different detection."
- **Save** button → updates `user_settings` table

### /settings/blocklist

Port the blocklist configuration from the desktop app's settings popup (~600 lines of tkinter) to a proper web page.

**Sections:**

1. **Quick Block** — Toggle switches for the 6 most common sites:
   - Instagram, YouTube, Netflix, Reddit, TikTok, Twitter/X
   - Each is a simple on/off toggle
   - Maps to `blocklist_configs.quick_blocks` JSON

2. **Categories** — Expandable sections for preset categories:
   - Social Media (Instagram, Facebook, Twitter, TikTok, Snapchat, etc.)
   - Video Streaming (YouTube, Netflix, Disney+, Twitch, etc.)
   - Gaming (Steam, Epic Games, Roblox, etc.)
   - Messaging (Discord, WhatsApp Web, Telegram, etc.)
   - News & Entertainment (Reddit, BuzzFeed, 9GAG, etc.)
   - Each category is a toggle. When expanded, shows all sites in the category.
   - Maps to `blocklist_configs.categories` JSON
   - **Reference:** The full site lists are in `screen/blocklist.py` → `PRESET_CATEGORIES`

3. **Custom URLs** — Text input to add custom domains:
   - Add/remove custom URLs
   - Validate format (must be a valid domain)
   - Maps to `blocklist_configs.custom_urls` JSON array

4. **Custom Apps** — Text input to add app names:
   - Add/remove app names to block
   - Maps to `blocklist_configs.custom_apps` JSON array

**Save behavior:** Each change auto-saves (debounced) OR explicit "Save Changes" button. The desktop app fetches this on next session start.

### /settings/detection

Gadget detection preferences — which gadget types count as distractions:

- Phone (default: ON)
- Tablet / iPad (default: OFF)
- Game Controller (default: OFF)
- TV / TV Remote (default: OFF)
- Nintendo Switch (default: OFF)
- Smartwatch (default: OFF)

Each is a toggle with description text. Maps to `user_settings.enabled_gadgets` JSON array.

**Reference:** Gadget types defined in `config.py` → `GADGET_PRESETS`

---

## Session History Page

### /sessions/

List of all past sessions, paginated.

```
┌─────────────────────────────────────────────────────────┐
│  Session History                          [Filter ▼]    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 📅 February 7, 2026                             │    │
│  │                                                 │    │
│  │ BrainDock Monday 2:45 PM                        │    │
│  │ Camera Only  •  45 min active  •  92% focus     │    │
│  │ 0 gadgets  •  2 screen distractions             │    │
│  │                                    [View →]     │    │
│  ├─────────────────────────────────────────────────┤    │
│  │ BrainDock Monday 10:00 AM                       │    │
│  │ Camera + Screen  •  1h 20m active  •  78% focus │    │
│  │ 3 gadgets  •  5 screen distractions             │    │
│  │                                    [View →]     │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ← Previous  Page 1 of 5  Next →                        │
└─────────────────────────────────────────────────────────┘
```

**Data:** `sessions` table, paginated (20 per page), newest first.

### /sessions/[id]

Detailed view of a single session.

```
┌─────────────────────────────────────────────────────────┐
│  ← Back to Sessions                                     │
│                                                         │
│  BrainDock Monday 2:45 PM                               │
│  February 7, 2026  •  Camera Only                       │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │  FOCUS   │ │  AWAY    │ │ GADGETS  │ │  PAUSED  │   │
│  │ 38m 20s  │ │  4m 10s  │ │  1m 30s  │ │  1m 00s  │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│                                                         │
│  Focus Rate: 85%                                        │
│  [Simple gauge/progress bar visualization]               │
│                                                         │
│  Timeline                                               │
│  [Horizontal bar showing event types over time]          │
│  ████████████░░░████░████████████████░░████████          │
│  (green=focused, grey=away, red=gadget, purple=screen)  │
│                                                         │
│  Event Log                                              │
│  2:45:00 PM  →  3:02:20 PM  │  Focussed     │  17m 20s │
│  3:02:20 PM  →  3:04:30 PM  │  Away          │   2m 10s │
│  3:04:30 PM  →  3:06:00 PM  │  Gadget (Phone)│   1m 30s │
│  ...                                                    │
└─────────────────────────────────────────────────────────┘
```

**Data:** `sessions` table + `session_events` for the timeline and event log.

---

## Subscription & Payment Page

### /pricing

Public page (no auth required) showing available plans:

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│              Simple, Transparent Pricing                 │
│                                                         │
│  ┌────────────────────┐                                 │
│  │     BrainDock      │                                 │
│  │     Starter        │                                 │
│  │                    │                                 │
│  │     $1.99 AUD      │                                 │
│  │   One-Time Payment │                                 │
│  │                    │                                 │
│  │  ✓ Camera tracking │                                 │
│  │  ✓ Screen tracking │                                 │
│  │  ✓ PDF reports     │                                 │
│  │  ✓ 2hr daily limit │                                 │
│  │                    │                                 │
│  │  [Get Started]     │                                 │
│  └────────────────────┘                                 │
│                                                         │
│  (More plans coming soon)                               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Stripe integration:** "Get Started" creates a Stripe Checkout session (server-side) and redirects to Stripe. On success, the Stripe webhook updates the `subscriptions` table. The page polls or listens for the subscription status change.

### /account/subscription

For authenticated users — shows their current subscription status:

- Current plan name and status
- Payment date and method
- "Manage Subscription" (link to Stripe Customer Portal if using subscriptions)
- "Upgrade" button (when free tier or expired)

---

## Device Management

### /settings/devices

Shows all desktop apps linked to the user's account:

```
┌─────────────────────────────────────────────────────────┐
│  Linked Devices                                         │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 💻 John's MacBook Pro                           │    │
│  │ macOS  •  Last active: 2 hours ago               │    │
│  │ App version: 2.0.0                               │    │
│  │                                     [Unlink]    │    │
│  ├─────────────────────────────────────────────────┤    │
│  │ 🖥 DESKTOP-ABC123                               │    │
│  │ Windows  •  Last active: 3 days ago              │    │
│  │ App version: 2.0.0                               │    │
│  │                                     [Unlink]    │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  To link a new device, download BrainDock and sign in.  │
│  [Download BrainDock →]                                 │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Data:** `devices` table. "Unlink" deletes the device row (desktop app will need to re-authenticate).

---

## How to Use / Tutorial Page

### /how-to-use

Replaces the 275-line tutorial popup from the desktop app. Should cover:

1. **Getting Started**
   - Download the desktop app
   - Create an account / sign in
   - Link your device

2. **Starting a Session**
   - Click the menu bar icon
   - Choose your mode (Camera / Screen / Both)
   - Click "Start Session"

3. **Monitoring Modes Explained**
   - Camera: Detects presence, gadget usage via AI
   - Screen: Monitors active windows/URLs against blocklist
   - Both: Combined monitoring with priority resolution

4. **Configuring Your Blocklist**
   - Quick blocks for common sites
   - Category-based blocking
   - Custom URLs and apps

5. **Understanding Your Reports**
   - Focus time breakdown
   - What each event type means
   - How focus rate is calculated

6. **FAQ**
   - Privacy: "What does BrainDock see?" → Frames are analyzed by AI and never stored
   - Cost: "How much does the AI detection cost?" → ~$0.01-0.03/min with Gemini
   - Accuracy: "Why was X detected/not detected?"
   - Offline: "What happens without internet?"

This page is static content — no Supabase calls needed. Use the design guidelines for styling.

---

## Desktop App Deep Linking

The website needs to communicate with the desktop app in two scenarios:

### 1. Auth Token Transfer (Login from Web → Desktop)

When a user logs in on the web with `?source=desktop`:

**Option A: Custom URL scheme (`braindock://`)**
```
braindock://auth/callback?access_token=...&refresh_token=...
```
- Requires registering `braindock://` URL scheme in the macOS app bundle and Windows registry
- Good UX but requires extra build configuration
- **SECURITY RISK:** Auth tokens are passed in the URL. URLs can be logged in browser history, proxy logs, and crash reports. If using this approach, use a short-lived exchange code in the URL instead of raw tokens.

**Option B: Localhost callback**
```
http://localhost:5678/auth/callback?code=SHORT_LIVED_CODE
```
- Desktop app runs a temporary HTTP server (similar to current payment flow)
- No URL scheme registration needed
- May conflict with firewalls or antivirus software on Windows
- **SECURITY RISK (if passing tokens directly):** Same URL logging concern as Option A. Always use a short-lived exchange code, never raw tokens in URLs.

**Option C: Manual code entry (RECOMMENDED)**
```
Website shows: "Enter this code in BrainDock: ABCD-1234"
Desktop app has: "Enter login code: [____]"
```
- Most reliable, zero configuration
- Most secure — tokens never pass through URLs, browser history, or proxy logs
- Slightly worse UX (user types a short code)
- Similar to how Spotify, Netflix, and smart TV apps link devices

**Recommendation:** Start with Option C (manual code) for simplicity AND security. It's the most reliable across all platforms and avoids the token-in-URL security concern entirely. Upgrade to Option A (custom URL scheme with exchange codes, not raw tokens) later if UX demands it.

### 2. "Open in App" Links

The web dashboard may want to trigger actions in the desktop app:
- "Start a session" → opens the app and starts tracking
- Not critical for initial implementation

---

## Testing Checklist

### Auth Pages
- [ ] Sign up with email/password creates account and profile in Supabase
- [ ] Sign up with Google creates account with name and avatar
- [ ] Login with email/password works and redirects to dashboard
- [ ] Login with Google works and redirects to dashboard
- [ ] Password reset email sends and works
- [ ] Unauthenticated users are redirected to login
- [ ] Auth callback handles tokens correctly

### Dashboard
- [ ] Shows correct daily stats (aggregated from sessions)
- [ ] Recent sessions list shows latest sessions
- [ ] Weekly chart renders with correct data
- [ ] Shows "No sessions yet" for new users
- [ ] Comparison with yesterday ("+30m vs yesterday") is accurate

### Settings
- [ ] Monitoring mode saves and persists on reload
- [ ] Blocklist quick toggles save correctly
- [ ] Blocklist categories expand/collapse and save
- [ ] Custom URL add/remove works with validation
- [ ] Custom app add/remove works
- [ ] Gadget detection toggles save correctly
- [ ] Desktop app picks up changed settings on next session start

### Session History
- [ ] Sessions list shows all sessions, paginated
- [ ] Session detail page shows correct stats
- [ ] Timeline visualization renders correctly
- [ ] Event log shows all events with correct times
- [ ] Empty state for users with no sessions

### Subscription
- [ ] Pricing page displays current tier correctly
- [ ] "Get Started" creates Stripe Checkout and redirects
- [ ] After payment, subscription status updates on page
- [ ] Account page shows correct subscription status
- [ ] Desktop app recognizes active subscription after web payment

### Device Management
- [ ] Shows all linked devices with correct info
- [ ] "Unlink" removes device
- [ ] Desktop app requires re-auth after unlink

### General
- [ ] All pages follow design guidelines (colors, typography, spacing)
- [ ] Responsive design works on mobile (tablet, phone)
- [ ] Dark mode not needed for now (light theme matches desktop app)
- [ ] Loading states shown while fetching data
- [ ] Error states handled gracefully (network errors, empty data)
- [ ] Navigation between pages works correctly
- [ ] All Supabase queries respect RLS (user only sees own data)
