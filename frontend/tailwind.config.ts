import type { Config } from "tailwindcss";

/**
 * Satyum design tokens — a "fintech security console" (CLAUDE.md §9):
 * deep blue / slate base, ONE accent (cyan), and three unmistakable verdict colours.
 * Colours chosen for WCAG AA contrast against the slate-950 canvas.
 */
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Base canvas + surfaces (deep slate/navy). `surface` lifts slightly off `canvas` and
        // `elevated` sits above it so the verdict hero can out-rank the metadata rail (a real
        // depth hierarchy instead of nine identical panels).
        canvas: "#080d18",
        surface: "#111a2c",
        "surface-2": "#1a2538",
        elevated: "#16213a",
        hairline: "#2a374f",
        "hairline-strong": "#3a4a68",
        // One accent
        accent: { DEFAULT: "#22d3ee", muted: "#0e7490", soft: "#0c2a33" },
        // Verdict semantics — unmistakable, never reused for chrome. `-soft` is a readable tint for
        // the hero (brighter than before so the verdict reads across a room / on a projector).
        verdict: {
          approved: "#22c55e",
          "approved-soft": "#10301f",
          review: "#f59e0b",
          "review-soft": "#352706",
          rejected: "#f43f5e",
          "rejected-soft": "#3a1018",
          pending: "#7c8aa5",
          "pending-soft": "#1b2638",
        },
      },
      fontFamily: {
        sans: ["Inter Variable", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-ring": {
          "0%, 100%": { opacity: "0.4" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.35s ease-out both",
        "pulse-ring": "pulse-ring 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
