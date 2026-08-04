/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Heebo"', '"Assistant"', "system-ui", "sans-serif"],
        display: ['"Heebo"', '"Assistant"', "system-ui", "sans-serif"],
        // Klaser DS — Rubik for display/H*/Caption/Small; Heebo for Body/Body 2.
        // Started on the marketing site (Landing.tsx); now also used for the
        // in-app Search header, which follows the same DS type scale.
        rubik: ['"Rubik"', '"Heebo"', "system-ui", "sans-serif"],
      },
      colors: {
        // Modernist palette — one strong accent, near-black ink, warm off-white
        // surface. No second decorative color. Borders carry the weight that
        // soft shadows used to.
        // The accent was clay red (#b8412b) until the Klaser rebrand; it now
        // matches the DS teal, so `accent` and `turquoise` are the same color.
        accent: {
          DEFAULT: "#19819A", // teal — same value as `turquoise`
          dark: "#166b80", // hover pair, matches turquoise.dark
          light: "#d96a52", // unused — still the old clay tint
        },
        ink: "#171717",
        "ink-soft": "#525252",
        surface: "#fafaf9",
        line: "#e7e5e4", // hairline border, replaces shadow-as-separator
        "line-strong": "#d6d3d1",
        // Klaser DS turquoise. Kept as its own token for DS-explicit markup,
        // though `accent` now resolves to the same teal app-wide.
        turquoise: {
          DEFAULT: "#19819a",
          dark: "#166b80",
        },
      },
      backgroundImage: {
        // Solid wash — kept the token name for compat but it's no longer a
        // 3-stop gradient. One color, end of story.
        "brand-gradient": "linear-gradient(180deg, #19819A 0%, #166b80 100%)",
      },
      boxShadow: {
        // Used sparingly — modernist relies on borders + whitespace, not depth.
        soft: "0 1px 0 rgba(23, 23, 23, 0.04)",
        lift: "0 2px 0 rgba(23, 23, 23, 0.06)",
        glow: "0 0 0 3px rgba(25, 129, 154, 0.18)",
      },
      borderRadius: {
        // Sharper everything. The old default 2xl/full was the SaaS-template look.
        DEFAULT: "0.125rem",
        sm: "0.125rem",
        md: "0.25rem",
        lg: "0.375rem",
        xl: "0.5rem",
        "2xl": "0.5rem",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.35s ease-out",
        shimmer: "shimmer 1.6s linear infinite",
      },
    },
  },
  plugins: [],
};
