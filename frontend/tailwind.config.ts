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
        // Base canvas + surfaces (deep slate/navy)
        canvas: "#0a0f1c",
        surface: "#111827",
        "surface-2": "#1a2335",
        hairline: "#27324a",
        // One accent
        accent: { DEFAULT: "#22d3ee", muted: "#0e7490" },
        // Verdict semantics — unmistakable, never reused for chrome
        verdict: {
          approved: "#16a34a",
          "approved-soft": "#0d3320",
          review: "#d97706",
          "review-soft": "#3a2a08",
          rejected: "#dc2626",
          "rejected-soft": "#3a1212",
          pending: "#64748b",
          "pending-soft": "#1e2636",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
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
