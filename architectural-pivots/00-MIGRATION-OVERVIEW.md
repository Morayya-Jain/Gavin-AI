# BrainDock Architectural Pivot — Master Plan

> **Read this document first.** It provides the full context, ordering, technology decisions, and cost breakdown that all three phase documents reference.

---

## Table of Contents

1. [What Is Changing](#what-is-changing)
2. [What Is NOT Changing](#what-is-not-changing)
3. [Target Architecture](#target-architecture)
4. [Programming Language Decision](#programming-language-decision)
5. [Technology Stack](#technology-stack)
6. [Phase Ordering](#phase-ordering)
7. [What Stays in App vs Moves to Web](#what-stays-in-app-vs-moves-to-web)
8. [Menu Bar App Design](#menu-bar-app-design)
9. [Cost Breakdown](#cost-breakdown)
10. [Current Codebase Map](#current-codebase-map)
11. [Risk Assessment](#risk-assessment)
12. [Key Principles](#key-principles)

---

## What Is Changing

BrainDock is pivoting from a **full desktop GUI application** (CustomTkinter, 6,681-line monolithic `gui/app.py`) to a **thin menu bar agent** paired with a **web dashboard** (separate repo).

**Before:** One fat desktop app that does everything — UI, detection, settings, payments, reports, onboarding.

**After:** Three systems working together:
1. **Menu bar desktop agent** — starts/stops sessions, runs detection, generates PDFs locally
2. **Web dashboard** (separate repo) — account management, settings, session history, payments, onboarding
3. **Supabase backend** — authentication, database, settings sync, session storage, Stripe webhooks

The desktop app becomes a quiet background worker with a minimal menu bar interface. The website becomes the primary way users interact with BrainDock for anything beyond starting and stopping sessions.

---

## What Is NOT Changing

These core modules remain **untouched** in functionality:

| Module | Lines | What It Does | Status |
|--------|-------|-------------|--------|
| `camera/capture.py` | 667 | OpenCV webcam management | **Keep as-is** |
| `camera/vision_detector.py` | 461 | OpenAI Vision API detection | **Keep as-is** |
| `camera/gemini_detector.py` | 466 | Gemini Vision API detection | **Keep as-is** |
| `camera/base_detector.py` | 311 | Shared detection infrastructure | **Keep as-is** |
| `camera/__init__.py` | 79 | Factory + event type resolver | **Keep as-is** |
| `tracking/session.py` | 199 | Session lifecycle & event logging | **Keep as-is** |
| `tracking/analytics.py` | 365 | Statistics computation & formatting | **Keep as-is** |
| `tracking/usage_limiter.py` | 464 | MVP time-limit enforcement | **Keep as-is** |
| `tracking/daily_stats.py` | 242 | Daily cumulative stats | **Keep as-is** |
| `screen/blocklist.py` | 936 | Blocklist data model & patterns | **Keep as-is** |
| `screen/window_detector.py` | 977 | Active window/URL detection | **Keep as-is** |
| `reporting/pdf_report.py` | 1,093 | PDF generation (ReportLab) | **Keep as-is** |
| `config.py` | 324 | Configuration & env loading | **Minor updates** (remove GUI-specific settings) |

**Total untouched code: ~6,260 lines** — the entire detection, tracking, and reporting pipeline.

---

## Target Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     SUPABASE (Cloud)                     │
│                                                          │
│  ┌──────────┐  ┌────────────┐  ┌───────────────────────┐│
│  │   Auth   │  │ PostgreSQL │  │    Edge Functions     ││
│  │          │  │            │  │                       ││
│  │- Email/  │  │- users     │  │- stripe-webhook       ││
│  │  password│  │- sessions  │  │  (payment events)     ││
│  │- Google  │  │- settings  │  │                       ││
│  │  OAuth   │  │- subs      │  │- sync-session         ││
│  │          │  │- blocklist │  │  (receive session     ││
│  │          │  │- devices   │  │   data from app)      ││
│  └──────────┘  └────────────┘  └───────────────────────┘│
└─────────┬────────────┬──────────────────┬────────────────┘
          │            │                  │
     ┌────▼────┐  ┌────▼──────┐    ┌─────▼──────┐
     │ Desktop │  │  Website  │    │   Stripe   │
     │  App    │  │ (Separate │    │  (Payments) │
     │(Menu Bar│  │   Repo)   │    │            │
     │  Agent) │  │           │    └────────────┘
     └─────────┘  └───────────┘

Desktop App (Python):           Website (Separate Repo):
- Menu bar icon                 - Account signup/login
- Start/Stop/Pause session      - Subscription management
- Mode toggle (cam/screen/both) - Blocklist configuration
- Camera detection (background)  - Gadget preferences
- Screen monitoring (background) - Session history & analytics
- PDF report generation          - Daily stats dashboard
- Auth token storage             - Tutorial / How to use
- Settings sync (on session      - Device management
  start, from Supabase)
- Session upload (on session
  end, to Supabase)
```

---

## Programming Language Decision

### Recommendation: Stay with Python for the Desktop App

The detection code is BrainDock's core value — ~5,000+ lines of working, tested Python across `camera/`, `screen/`, and `tracking/`. Here's the honest comparison:

| Language/Framework | Bundle Size | Menu Bar UX | Detection Code | Migration Effort | Verdict |
|---|---|---|---|---|---|
| **Python + rumps/pystray** | ~50-70MB (smaller than current ~99MB) | Good (native on macOS via rumps) | **Zero rewrite** — import existing modules directly | **Low** — only replace GUI layer | **RECOMMENDED** |
| **Swift (macOS) + C# (Windows)** | ~5-10MB | Perfect (fully native) | Must rewrite ALL detection code OR run Python as sidecar | **Very high** — two codebases, full rewrite | Not worth it |
| **Tauri (Rust + web UI)** | ~10-20MB | Good (native tray) | Must run Python as sidecar process | **High** — new Rust/TS stack, sidecar complexity | Overkill for this |
| **Electron** | ~100MB+ | Okay (heavy) | Must run Python as sidecar | **Medium** — familiar web tech but heavy | Defeats the purpose |
| **Go + systray** | ~15-30MB | Good | No OpenCV/Vision SDK support — must use Python sidecar | **High** — Go has poor camera/ML library support | Not practical |

### Why Python Wins

1. **Zero rewrite risk.** The detection modules (`camera/`, `screen/`, `tracking/`) import directly. No sidecar process, no IPC, no serialization overhead.
2. **The libraries are Python-first.** `opencv-python`, `openai`, `google-generativeai`, `pyobjc`, `pywinauto` — all Python-native. Equivalent Rust/Swift/Go libraries are either immature or non-existent.
3. **Bundle size actually shrinks.** Removing `customtkinter` and all GUI dependencies cuts ~30MB from the bundle. The menu bar libraries (`rumps`, `pystray`) are tiny.
4. **The UI is a dropdown menu.** For a menu bar dropdown, the language of the UI doesn't matter for user experience. Users won't know or care that it's Python underneath.
5. **`rumps`** (Ridiculously Uncomplicated macOS Python Statusbar) is purpose-built for exactly this use case — lightweight macOS menu bar apps. It has 3,300+ GitHub stars and exposes native macOS menu bar APIs through simple Python decorators.
6. **`pystray`** handles Windows system tray with the same simplicity.

### The Only Scenario Where Python Isn't Ideal

If you later want the app under ~10MB bundle size (e.g., for fast downloads), you'd need to:
- Build a thin Swift/C# wrapper that calls a Python backend running as a local service
- Or rewrite detection in Rust/Swift (not recommended unless you have months to spare)

**For now and the foreseeable future, Python is the right choice.** Revisit only if bundle size becomes a user acquisition bottleneck.

### Backend Language

Supabase handles the backend. The only custom code is Edge Functions (TypeScript/Deno) — roughly 50-100 lines total for Stripe webhooks and session sync. This is not a language choice; it's a Supabase constraint.

### Website Language

Already exists in a separate repo. Whatever framework is there stays. The web dashboard will use the Supabase JavaScript client for data access.

---

## Technology Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| **Desktop app (macOS)** | Python + `rumps` | Native macOS menu bar with zero detection code changes |
| **Desktop app (Windows)** | Python + `pystray` | Cross-platform system tray, same codebase |
| **Backend** | Supabase (PostgreSQL + Auth + Edge Functions) | Managed, generous free tier, built-in Google OAuth, auto-generated REST API |
| **Database** | PostgreSQL (via Supabase) | Relational data (users → subscriptions → sessions → events), perfect for pricing tiers |
| **Auth** | Supabase Auth | Email/password + Google OAuth out of the box, Python client for desktop app |
| **Payments** | Stripe (via Supabase Edge Functions) | Keep existing Stripe account, webhook → Edge Function → update DB |
| **Website** | Existing separate repo | Uses Supabase JS client for all data operations |
| **PDF generation** | ReportLab (local, Python) | Stays local, works offline, no server load |
| **Detection** | OpenAI Vision / Gemini Vision (Python SDKs) | Unchanged |
| **Camera** | OpenCV (Python) | Unchanged |
| **Screen monitoring** | pyobjc (macOS) / pywinauto (Windows) | Unchanged |

### New Dependencies (Desktop App)

**Add:**
- `rumps` — macOS menu bar (replaces entire CustomTkinter GUI)
- `pystray` — Windows system tray
- `supabase` — Python client for Supabase (auth, data sync)

**Remove:**
- `customtkinter` — entire GUI framework
- `stripe` — payments move to web/Supabase Edge Functions (no longer needed in desktop app)

---

## Phase Ordering

### Phase 1: Backend & Auth (Supabase) → `01-BACKEND-AND-AUTH.md`

**Do this FIRST.** Both the desktop app and website depend on having the backend in place. This phase creates:
- Supabase project with database schema
- Auth configuration (email/password, Google OAuth)
- Edge Functions for Stripe webhooks
- License validation endpoint

**Why first:** You can test the backend independently. The existing desktop app continues working unchanged while you build this. No user-facing risk.

### Phase 2: Desktop App Migration → `02-DESKTOP-APP-MIGRATION.md`

**Do this SECOND.** This is the highest-risk phase:
- Extract business logic from `gui/app.py` into `core/engine.py`
- Build the menu bar app (replaces entire `gui/` folder)
- Add auth flow (login via browser, store token)
- Add settings sync (fetch from Supabase on session start)
- Add session upload (push to Supabase on session end)

**CRITICAL: Before deleting ANY GUI code, extract the detection orchestration logic into a separate `core/engine.py` module first.** The current `gui/app.py` has ~2,000 lines of business logic (detection loops, pause/resume state, alert tracking, usage limiting, report generation) tangled with ~4,600 lines of UI code. The menu bar app should be able to simply call `engine.start_session()` and `engine.stop_session()` without untangling what's UI and what's logic from inside the monolith.

**Why second:** The backend must exist first (for auth and settings sync). Doing this before the web dashboard means you can test the full desktop-to-cloud pipeline end-to-end before building the web UI.

### Phase 3: Web Dashboard → `03-WEB-DASHBOARD-MIGRATION.md`

**Do this LAST.** This is the lowest-risk phase — it's additive, not destructive:
- Build account management pages
- Build blocklist/settings configuration pages
- Build session history dashboard
- Build subscription management
- Port the tutorial/how-to-use content

**Why last:** This is a new web app reading from/writing to a database that already exists (Phase 1) and already has data flowing in (Phase 2). Lowest technical risk, most visible to users.

---

## What Stays in App vs Moves to Web

| Feature | Currently | New Location | Why |
|---------|-----------|-------------|-----|
| Start/Stop/Pause session | App (GUI) | **App (menu bar)** | Must be instant, local, one-click |
| Mode toggle (cam/screen/both) | App (GUI) | **App (menu bar)** | Quick toggle during use |
| Timer display | App (GUI) | **App (menu bar)** | Need to see at a glance |
| Session status | App (GUI) | **App (menu bar)** | Core feedback loop |
| Camera detection | App (background thread) | **App (background)** | Needs local camera hardware |
| Screen monitoring | App (background thread) | **App (background)** | Needs local window access |
| PDF generation | App (local) | **App (local)** | Works offline, no server cost |
| Download Report | App (button) | **App (menu bar item)** | Triggers local PDF save to Downloads |
| Login | Not in app | **App (one-time, via browser)** | Link app to user account |
| Blocklist settings | App (600-line settings popup) | **Website** | Complex UI, configure once |
| Gadget type preferences | App (settings popup) | **Website** | Configure once, sync to app |
| Daily stats cards | App (3 cards: focus, distractions, rate) | **Website** | Dashboard content |
| Session history | Not available | **Website** | New feature enabled by cloud sync |
| Tutorial / How to use | App (275-line popup) | **Website** | Static content |
| Payment / Subscription | App (1,456-line payment screen) | **Website** | Standard web checkout |
| Account management | Not available | **Website** | Sign up, profile, devices |
| Device management | Not available | **Website** | Link/unlink desktop apps |

---

## Menu Bar App Design

### macOS Menu Bar (idle state)

```
┌─────────────────────────────┐
│  🧠 BrainDock               │
│                             │
│  ● Ready to start           │
│                             │
│  [▶ Start Session]          │
│                             │
│  Mode:                      │
│  (●) Camera  (○) Screen     │
│  (○) Both                   │
│                             │
│  ─────────────────────────  │
│  Open Dashboard →           │
│  Download Last Report       │
│  ─────────────────────────  │
│  user@email.com             │
│  Log Out     Quit BrainDock │
└─────────────────────────────┘
```

### Active session state

```
┌─────────────────────────────┐
│  🧠 BrainDock               │
│                             │
│  ● Tracking  (Camera)       │
│  ⏱ 00:14:32                 │
│                             │
│  [⏸ Pause]  [■ Stop]        │
│                             │
│  ─────────────────────────  │
│  Open Dashboard →           │
│  ─────────────────────────  │
│  user@email.com             │
│  Quit BrainDock             │
└─────────────────────────────┘
```

### Behaviour
- **Menu bar icon:** Small BrainDock logo in the macOS menu bar (top-right) or Windows system tray (bottom-right)
- **Click icon:** Shows the dropdown menu above
- **Open from Applications/Dock:** Activates the menu bar icon (same dropdown appears). No separate window. No dock icon on macOS (LSUIElement = true in Info.plist)
- **"Open Dashboard":** Opens the BrainDock website in default browser
- **"Download Last Report":** Generates/saves PDF for the most recent completed session
- **Start/Stop/Pause:** Instant — same behavior as current GUI buttons
- **Mode toggle:** Radio buttons that persist between sessions. On app launch, the default mode is fetched from Supabase (`user_settings.monitoring_mode`). If the user changes the mode in the menu bar, the change applies immediately to the current/next session and is saved locally. It does NOT write back to Supabase — the web dashboard is the source of truth for defaults. Local overrides persist until the next app launch, when the Supabase default is re-fetched.
- **Status updates:** Menu bar icon can change color/badge to indicate state (green = tracking, yellow = paused, grey = idle)

---

## Cost Breakdown

### Current Costs (What You Pay Now)

| Item | Cost |
|------|------|
| Domain (website hosting) | ~$10-15/year |
| OpenAI API (per user session) | ~$0.06-0.12/min at 0.33 FPS |
| Gemini API (per user session, default) | ~$0.01-0.03/min (cheaper) |
| Stripe transaction fees | 2.9% + $0.30 per transaction |
| **Total fixed monthly** | **~$1/month** (domain only) |

### New Additional Costs After Pivot

| Item | Free Tier | When Paid Tier Needed | Paid Cost |
|------|-----------|----------------------|-----------|
| **Supabase** (DB + Auth + API + Edge Functions) | 500MB DB, 50K auth users, 1GB file storage, 500K Edge Function invocations/month | ~500+ active users or >500MB data | **$25/month** (Pro) |
| **Auth emails** (password reset, signup confirmation) | Supabase built-in (rate-limited ~4/hr) | When you need reliable delivery | Resend: **$0/month** (100 emails/day free) |
| **Stripe** | Same as now | Same | Same (2.9% + $0.30) |
| **Vision APIs** | Same as now | Same | Same per-minute rate |

### Cost by Scale

| User Scale | Additional Monthly Cost | Notes |
|------------|------------------------|-------|
| 0–100 users | **$0/month** | Supabase free tier |
| 100–500 users | **$0/month** | Still within free tier |
| 500–1,000 users | **$25/month** | Supabase Pro tier |
| 1,000–5,000 users | **$25–50/month** | Pro + potential storage overage |
| 5,000+ users | **$25–75/month** | Depends on session data volume |

**Key insight:** The free tier supports hundreds of active users. You pay $0 additional until you have real traction. The $25/month Pro tier is the first breakpoint.

### One-Time Costs

| Item | Cost | Notes |
|------|------|-------|
| Apple Developer Program | $99/year | Optional — eliminates "right-click to open" Gatekeeper issue |
| Everything else | $0 | Supabase, rumps, pystray, Stripe are free/open-source |

---

## Current Codebase Map

Understanding what exists today and what happens to each file:

### Files to DELETE (after extraction)

| File | Lines | Why |
|------|-------|-----|
| `gui/app.py` | 6,681 | Replaced by menu bar app + core engine |
| `gui/ui_components.py` | 1,396 | CustomTkinter components — no longer needed |
| `gui/payment_screen.py` | 1,456 | Payments move to website |
| `gui/font_loader.py` | 248 | GUI font loading — not needed for menu bar |
| `licensing/stripe_integration.py` | 860 | Stripe moves to Supabase Edge Functions |

**Total removed: ~10,641 lines**

### Files to CREATE

| File | Purpose |
|------|---------|
| `core/engine.py` | Detection orchestration extracted from `gui/app.py` |
| `core/__init__.py` | Package init |
| `menubar/app.py` | Menu bar application (macOS: rumps, Windows: pystray) |
| `menubar/__init__.py` | Package init |
| `sync/supabase_client.py` | Supabase client wrapper (auth, settings fetch, session upload) |
| `sync/__init__.py` | Package init |

### Files to MODIFY

| File | Change |
|------|--------|
| `main.py` | Entry point now launches menu bar app instead of GUI |
| `config.py` | Remove GUI-specific settings, add Supabase config |
| `licensing/license_manager.py` | Update to validate against Supabase (instead of local-only) |
| `requirements.txt` | Add rumps/pystray/supabase, remove customtkinter/stripe |
| `build/braindock.spec` | Update PyInstaller spec for menu bar app |
| `build/build_macos.sh` | Update for LSUIElement (no dock icon), smaller bundle |

### Files UNCHANGED

All of `camera/`, `screen/`, `tracking/`, `reporting/`, `data/`, `tests/`.

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| **Business logic tangled in GUI** | HIGH | Extract `core/engine.py` BEFORE deleting any GUI code. Phase 2 documents this in detail. |
| **Broken detection after refactor** | MEDIUM | Detection modules (`camera/`, `screen/`) are untouched. Only the orchestration layer moves. Run existing tests after extraction. |
| **Auth token management** | LOW | Supabase Python client handles token refresh automatically. Store refresh token in user data directory. |
| **Offline degradation** | LOW | Screen-only mode works fully offline. Camera modes need internet for Vision API (already the case). Settings cached locally after first sync. |
| **Supabase vendor lock-in** | LOW | Supabase uses standard PostgreSQL. Data is exportable. Auth is standard JWT. You could self-host Supabase or migrate to any PostgreSQL host. |
| **Two codebases to maintain** | MEDIUM | The desktop app becomes simpler (~2,000 lines for engine + ~300 lines for menu bar vs. current 10,000+ lines of GUI). Net reduction in complexity. |

---

## Key Principles

1. **Extract before you delete.** Never remove GUI code until the business logic it contains has been cleanly separated into `core/engine.py` and tested independently.
2. **Detection code is sacred.** The `camera/`, `screen/`, and `tracking/` modules are the product's core value. They should not be modified during this migration — only called from a different place.
3. **Backend before client.** Build Supabase schema and auth before touching the desktop app or web dashboard. Both depend on it.
4. **Test at each phase boundary.** Phase 1 → verify auth works. Phase 2 → verify sessions run end-to-end. Phase 3 → verify web reads correct data.
5. **Settings sync is lazy.** Fetch from Supabase on session start, not continuously. Push session data on session end, not in real-time. This keeps costs zero and complexity low.
6. **The menu bar app is thin.** It should be under 500 lines total (excluding the engine). If it's growing beyond that, something that should be on the website is creeping in.
7. **Keep the one-time $1.99 payment working.** The subscription model is future work. The current payment flow just moves from in-app Stripe to web Stripe, but the price and licensing behavior stay the same.
8. **A web account is always required.** Even for the $1.99 one-time payment, users must create an account first. The account links to their desktop app via auth token.
