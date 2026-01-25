# BrainDock Landing Page - Deployment Guide

A summary of the approach to create and deploy a landing page for BrainDock.

---

## Overview

- **Goal:** Create a landing page with download links for macOS, Windows, and Linux
- **Hosting:** Netlify (free tier)
- **Domain:** Custom domain via Porkbun
- **Cost:** $0 (domain already owned)

---

## Architecture Decision

**Separate repository** for the website (not in the main `gavin-ai` repo):
- Clean separation between product code and marketing site
- Different deployment cycles
- Keeps main repo focused on application code

---

## Website Content

The landing page will include:
- Hero section with logo and tagline
- Product description (what BrainDock does)
- Features list (AI detection, privacy-first, PDF reports, real-time tracking)
- How it works section
- Download buttons (macOS / Windows / Linux) - placeholder links for now
- Pricing section
- Footer with Privacy Policy and Terms of Service links
- Contact/support information

**Not included:** Demo video, screenshots (can be added later)

---

## Design Guidelines

Following the "Seraphic Focus" design language from `planning/design_guidelines.json`:

| Element | Value |
|---------|-------|
| Background | `#F9F8F4` (warm paper) |
| Text | `#1C1C1E` (near-black) |
| Accent | `#D4A373` (warm gold) |
| Button BG | `#1C1C1E` |
| Button Text | `#FFFFFF` |
| Headings | Serif font (Georgia/Playfair Display) |
| Body text | Sans-serif (Inter) |
| Style | Generous whitespace, rounded buttons, minimal borders |

---

## New Repository Structure

Create a new repo (e.g., `braindock-website`) with this structure:

```
braindock-website/
├── index.html              # Main landing page
├── privacy.html            # Privacy policy page
├── terms.html              # Terms of service page
├── css/
│   └── style.css           # Styles (Seraphic Focus design)
├── assets/
│   ├── logo_icon.png       # Copy from gavin-ai/assets/
│   └── logo_with_text.png  # Copy from gavin-ai/assets/
└── context/                # Reference files (optional)
    └── design_guidelines.json
```

---

## Context Files to Copy

From `gavin-ai` to the new website repo:

| Source | Destination | Purpose |
|--------|-------------|---------|
| `assets/logo_icon.png` | `assets/logo_icon.png` | Favicon, icons |
| `assets/logo_with_text.png` | `assets/logo_with_text.png` | Hero section |
| `legal/PRIVACY_POLICY.md` | Convert to `privacy.html` | Legal page |
| `legal/TERMS_AND_CONDITIONS.md` | Convert to `terms.html` | Legal page |
| `planning/design_guidelines.json` | `context/` (optional) | Design reference |

---

## Deployment Steps

### 1. Create the Website Repo

```bash
# Create new repo on GitHub: braindock-website
git clone https://github.com/yourusername/braindock-website.git
cd braindock-website
```

### 2. Build the Website

Open the new repo in Cursor and ask the AI to build the landing page with the design guidelines and content requirements.

### 3. Deploy to Netlify

1. Go to [netlify.com](https://netlify.com) and sign up (free)
2. Click "Add new site" > "Import an existing project"
3. Connect your GitHub account
4. Select the `braindock-website` repo
5. Deploy settings: Leave defaults (Netlify auto-detects static sites)
6. Click "Deploy"

Your site is now live at `random-name.netlify.app`

### 4. Connect Custom Domain

**In Netlify:**
1. Go to Site settings > Domain management
2. Click "Add custom domain"
3. Enter your domain (e.g., `braindock.app`)
4. Netlify will show DNS records to add

**In Porkbun:**
1. Go to your domain > DNS
2. Delete existing A/CNAME records for @ and www (if any)
3. Add these records:

| Type | Host | Answer |
|------|------|--------|
| A | (blank) | `75.2.60.5` |
| CNAME | www | `your-site.netlify.app` |

4. Wait 5-30 minutes for DNS propagation

**Back in Netlify:**
1. Netlify will auto-verify the domain
2. SSL certificate is provisioned automatically
3. Your site is now live at your custom domain

---

## Why Netlify is Free

Netlify's free tier includes:
- 100 GB bandwidth/month (landing page uses ~50KB/visit = 2M visits possible)
- Unlimited sites
- Custom domains
- Automatic HTTPS/SSL
- No forced branding

Business model: Free for individuals, paid plans ($19+/month) for teams and enterprises.

---

## Future Updates

When the app is packaged:
1. Upload installers to GitHub Releases or cloud storage
2. Get direct download URLs
3. Update download buttons in `index.html` with actual links

---

## Quick Reference

| Item | Value |
|------|-------|
| Website repo | `braindock-website` (separate from main app) |
| Hosting | Netlify (free) |
| Domain registrar | Porkbun |
| Total cost | $0 (domain already owned) |
| Netlify A record | `75.2.60.5` |
| Tech stack | Static HTML/CSS |
