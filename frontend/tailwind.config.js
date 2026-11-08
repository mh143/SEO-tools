/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'Inter Variable'", "Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        brand: {
          50: "#f1f3ff", 100: "#e4e7ff", 200: "#cdd2ff", 300: "#a9b0ff", 400: "#8083fd",
          500: "#625cf7", 600: "#523deb", 700: "#462fd0", 800: "#3a29a8", 900: "#322885", 950: "#1e174d",
        },
        ink: {
          50: "#f8f9fb", 100: "#f1f3f7", 200: "#e4e7ee", 300: "#cfd4df", 400: "#9aa3b5",
          500: "#6b7489", 600: "#4d566b", 700: "#363e52", 800: "#1f2537", 900: "#121626", 950: "#0a0d18",
        },
      },
      boxShadow: {
        card: "0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)",
        lift: "0 12px 32px -12px rgba(30,23,77,.18), 0 4px 10px -4px rgba(16,24,40,.06)",
        glow: "0 0 0 1px rgba(98,92,247,.12), 0 20px 60px -20px rgba(98,92,247,.45)",
      },
      borderRadius: { xl: "0.875rem", "2xl": "1.125rem" },
      keyframes: {
        "fade-up": { "0%": { opacity: 0, transform: "translateY(8px)" }, "100%": { opacity: 1, transform: "none" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: { "fade-up": "fade-up .45s ease-out both", shimmer: "shimmer 1.6s infinite" },
    },
  },
  plugins: [],
};
