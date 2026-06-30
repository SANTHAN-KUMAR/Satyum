---
name: Satyum Trust Console
description: A regulated fintech verification console for bank underwriting teams. Trust-first, data-dense professional language, leaning toward Tailwind v3 utilities + Geist font family + restrained motion.
colors:
  canvas: "#0a0a0a"       # Neutral near-black
  surface: "#141414"      # Warm dark
  surface-hover: "#1f1f1f"
  surface-muted: "#0f0f0f"
  accent: "#10b981"       # Emerald green (trust)
  accent-hover: "#059669"
  accent-muted: "#064e3b" # Emerald 900
  accent-fg: "#022c22"    # Emerald 950
  hairline: "#262626"     # Neutral 800
  hairline-strong: "#404040" # Neutral 700
  text-primary: "#f5f5f5" # Neutral 100
  text-secondary: "#a3a3a3" # Neutral 400
  text-tertiary: "#737373" # Neutral 500
  
  # Semantic States (Do not change - locked for backend contract)
  status-approved: "#10b981" # Emerald 500
  status-review: "#f59e0b"   # Amber 500
  status-rejected: "#ef4444" # Red 500
  
typography:
  headline-display:
    fontFamily: Geist, sans-serif
    fontSize: 48px
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist, sans-serif
    fontSize: 32px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Geist, sans-serif
    fontSize: 24px
    fontWeight: 500
    lineHeight: 1.3
  body-lg:
    fontFamily: Geist, sans-serif
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.6
  body-md:
    fontFamily: Geist, sans-serif
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
  label-mono:
    fontFamily: "Geist Mono", monospace
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0.05em
    
rounded:
  none: 0px
  sm: 4px
  md: 8px     # Controls/Inputs
  lg: 12px    # Panels/Cards
  full: 9999px
  
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
---

# Satyum Trust Console

## Overview
Satyum is a regulated fintech verification console used by Canara Bank underwriting teams. 
It must communicate absolute trust, security, and precision. 
It should look like a modern Bloomberg Terminal or institutional banking software, not a consumer startup or an AI-generated dark mode dashboard.

**Design Read:** Regulated fintech verification console for bank underwriting teams, with a trust-first, data-dense professional language, leaning toward Tailwind utilities + Geist font family + restrained motion.

## Colors
- **Canvas (#0a0a0a):** Neutral near-black. No blue tints, no AI-cyan.
- **Surface (#141414):** A subtle lift from the canvas. Used for panels and cards.
- **Accent (#10b981 - Emerald):** The color of banking, approval, and trust. Used sparingly for primary actions and focus states. Avoid cyan or purple entirely.
- **Hairlines (#262626):** Crisp, subtle dividers to separate data density.

## Typography
- **Geist:** Primary sans-serif for UI and readability. Professional, neutral, Swiss-inspired. (Replaces Inter).
- **Geist Mono:** Used for strict data, IDs, hashes, and measurements.
- **No Eyebrow Spam:** Avoid the AI-cliché of placing tiny uppercase mono tracking text above every headline. Use hierarchy and space instead.

## Layout
- **Dashboard Structure:** Left sidebar navigation on desktop (mode switching) to maximize horizontal space for data display.
- **Asymmetric Density:** The Evidence Console uses a 2-column or 3-column asymmetric layout where the primary verdict dominates, and supporting data is densely packed but cleanly divided.

## Shapes & Geometry
- **Consistent Radii:** 12px (`rounded-xl` in TW if adjusted, or explicit `rounded-[12px]`) for structural panels. 8px (`rounded-lg` or `md`) for interactive controls. No mixing sharp and round randomly.

## Do's and Don'ts
- **DO** use human-focused, clear banking language (see `lib/copy.ts`).
- **DON'T** use engineer jargon like "verification waterfall", "fail-closed", or "treated as hostile" in user-facing copy.
- **DO** use emerald for the primary focus/accent to evoke financial trust.
- **DON'T** use cyan, purple, or neon glows (the "AI dashboard" traps).
- **DO** maintain strict data alignment.
- **DON'T** use standard 50/50 splits or generic 3-card bento grids. Force asymmetry and density appropriate for a forensic tool.
