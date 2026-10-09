/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { 50: "#eef4ff", 100: "#dbe6fe", 500: "#3b6ef6", 600: "#2557e8", 700: "#1d44c4", 900: "#172b6b" },
      },
    },
  },
  plugins: [],
};
