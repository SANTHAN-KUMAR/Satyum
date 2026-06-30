import type { Config } from "tailwindcss";

/**
 * Satyum design tokens — "Banking Trust Console" (DESIGN.md)
 * Neutral near-black base, emerald accent, and three unmistakable verdict colours.
 */
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#0a0a0a",
        surface: "#141414",
        "surface-hover": "#1f1f1f",
        "surface-muted": "#0f0f0f",
        elevated: "#1a1a1a",
        accent: {
          DEFAULT: "#10b981", // Emerald
          hover: "#059669",
          muted: "#064e3b",
          fg: "#022c22",
        },
        text: {
          primary: "#f5f5f5",
          secondary: "#a3a3a3",
          tertiary: "#737373",
        },
        hairline: "#262626",
        "hairline-strong": "#404040",
        
        // Verdict semantics — locked for backend contract
        verdict: {
          approved: "#10b981",
          "approved-soft": "#064e3b",
          review: "#f59e0b",
          "review-soft": "#78350f",
          rejected: "#ef4444",
          "rejected-soft": "#7f1d1d",
          pending: "#737373",
          "pending-soft": "#262626",
        },
      },
      fontFamily: {
        sans: ["Geist", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["Geist Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: {
        none: "0px",
        sm: "4px",
        md: "8px",     // Controls/Inputs
        lg: "12px",    // Panels/Cards
        full: "9999px",
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
