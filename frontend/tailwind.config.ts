import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

/**
 * Satyum design tokens — monochrome-first (white major, near-black ink), the StartGlobal-style premium
 * onboarding language. The Indian-flag colours (saffron · navy · India-green) are NO LONGER a base
 * palette: they appear ONLY as a **linear gradient for highlights** (see index.css `.gradient-*`) and
 * frosted **glassmorphism** marks emphasis. To keep the whole app monochrome with minimal churn, the
 * old brand tokens (`navy` / `saffron` / `india`) and `slate` are remapped here to neutral greys — so
 * any existing utility renders monochrome; colour comes back only through the gradient/glass utilities.
 */
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Canvas + surfaces — white major.
        canvas: "#FFFFFF",
        surface: "#FFFFFF",
        "surface-2": "#F5F5F6",
        "surface-muted": "#F4F4F5", // light-theme equivalent of main's dark muted panel surface
        "surface-hover": "#EFEFF1", // hover state for rows/cards in main's console (light theme)
        hairline: "#E6E6E9",
        ink: "#0A0A0A",

        // Text scale consumed by main's evidence-console components (text-text-primary/secondary/tertiary).
        // Remapped from main's dark values to light-theme greys so the console reads correctly on white.
        text: {
          primary: "#0A0A0A", // headings / strong ink
          secondary: "#3F3F46", // body
          tertiary: "#71717A", // muted (labels, captions)
        },

        // The real flag colours kept ONLY for the gradient utilities (referenced as literals there).
        // Exposed here too in case a one-off needs a single stop, but components should prefer .gradient-*.
        grad: { saffron: "#FF9933", navy: "#000080", green: "#138808" },

        // --- Brand tokens REMAPPED to monochrome (so legacy utilities go grey, not flag-coloured) ---
        navy: { DEFAULT: "#0A0A0A", 600: "#27272A", soft: "#F2F2F4" },
        saffron: { DEFAULT: "#A1A1AA", deep: "#52525B", soft: "#F2F2F4" },
        india: { green: "#18181B", "green-text": "#3F3F46", soft: "#F2F2F4" },
        accent: { DEFAULT: "#0A0A0A", muted: "#52525B" },

        // Verdict semantics — monochrome + the two universally-understood state colours (red/amber),
        // always paired with icon + label in the UI (never colour alone). APPROVED is treated with the
        // gradient in components, so its token is a neutral dark (no green).
        verdict: {
          approved: "#18181B",
          "approved-soft": "#F2F2F4",
          review: "#B45309",
          "review-soft": "#FBF3E8",
          rejected: "#B91C1C",
          "rejected-soft": "#FBEAEA",
          pending: "#52525B",
          "pending-soft": "#F2F2F4",
        },

        // `slate-*` remapped to a clean neutral grey scale (text-first).
        slate: {
          50: "#FAFAFA",
          100: "#0A0A0A", // heading ink
          200: "#18181B",
          300: "#3F3F46", // body
          400: "#52525B", // muted (~7:1 on white)
          500: "#71717A", // secondary muted
          600: "#71717A",
          700: "#52525B",
          800: "#27272A",
          900: "#18181B",
          950: "#0A0A0A",
        },
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
        display: ['"Plus Jakarta Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(10,10,20,0.04), 0 8px 28px rgba(10,10,20,0.06)",
        lift: "0 8px 24px rgba(10,10,20,0.08), 0 24px 60px rgba(10,10,20,0.10)",
        glass: "0 8px 32px rgba(17,17,26,0.08)",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
        "pulse-ring": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.55", transform: "scale(1.12)" },
        },
        // Directional nudges for the live-capture challenge overlay (ChallengeOverlay.tsx): the icon
        // physically moves the way the server is asking the user to tilt the document, instead of
        // just pulsing in place — a plain-language substitute for "tilt 22 degrees" (CLAUDE.md §9).
        "nudge-up": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-7px)" },
        },
        "nudge-down": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(7px)" },
        },
        "nudge-left": {
          "0%, 100%": { transform: "translateX(0)" },
          "50%": { transform: "translateX(-7px)" },
        },
        "nudge-right": {
          "0%, 100%": { transform: "translateX(0)" },
          "50%": { transform: "translateX(7px)" },
        },
        "nudge-rotate-cw": {
          "0%, 100%": { transform: "rotate(0deg)" },
          "50%": { transform: "rotate(18deg)" },
        },
        "nudge-rotate-ccw": {
          "0%, 100%": { transform: "rotate(0deg)" },
          "50%": { transform: "rotate(-18deg)" },
        },
        "nudge-zoom-in": {
          "0%, 100%": { transform: "scale(1)" },
          "50%": { transform: "scale(1.25)" },
        },
        "nudge-zoom-out": {
          "0%, 100%": { transform: "scale(1)" },
          "50%": { transform: "scale(0.8)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.4s ease-out both",
        float: "float 8s ease-in-out infinite",
        "pulse-ring": "pulse-ring 1.4s ease-in-out infinite",
        "nudge-up": "nudge-up 1.1s ease-in-out infinite",
        "nudge-down": "nudge-down 1.1s ease-in-out infinite",
        "nudge-left": "nudge-left 1.1s ease-in-out infinite",
        "nudge-right": "nudge-right 1.1s ease-in-out infinite",
        "nudge-rotate-cw": "nudge-rotate-cw 1.1s ease-in-out infinite",
        "nudge-rotate-ccw": "nudge-rotate-ccw 1.1s ease-in-out infinite",
        "nudge-zoom-in": "nudge-zoom-in 1.1s ease-in-out infinite",
        "nudge-zoom-out": "nudge-zoom-out 1.1s ease-in-out infinite",
      },
    },
  },
  plugins: [typography],
};

export default config;
