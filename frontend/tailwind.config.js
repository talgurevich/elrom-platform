/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Assistant"', '"Heebo"', "system-ui", "sans-serif"],
      },
      colors: {
        accent: "#2a4b59",
        ink: "#1a2932",
        "ink-soft": "#5a6c75",
      },
    },
  },
  plugins: [],
};
