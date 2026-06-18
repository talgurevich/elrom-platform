/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Assistant"', '"Heebo"', "system-ui", "sans-serif"],
        display: ['"Heebo"', '"Assistant"', "system-ui", "sans-serif"],
      },
      colors: {
        accent: {
          DEFAULT: "#2a4b59",
          dark: "#1a3340",
          light: "#3d6373",
        },
        gold: "#c8a55b",
        ink: "#1a2932",
        "ink-soft": "#5a6c75",
        surface: "#fbfaf7",
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #1a3340 0%, #2a4b59 50%, #3d6373 100%)",
        "surface-soft":
          "radial-gradient(1200px 600px at 50% -100px, rgba(42, 75, 89, 0.08), transparent 60%), radial-gradient(800px 400px at 90% 10%, rgba(200, 165, 91, 0.06), transparent 60%)",
      },
      boxShadow: {
        soft: "0 1px 2px rgba(26, 41, 50, 0.04), 0 4px 16px rgba(26, 41, 50, 0.04)",
        lift: "0 2px 4px rgba(26, 41, 50, 0.06), 0 12px 32px rgba(26, 41, 50, 0.08)",
        glow: "0 0 0 4px rgba(42, 75, 89, 0.12)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.4s ease-out",
        shimmer: "shimmer 1.6s linear infinite",
      },
    },
  },
  plugins: [],
};
