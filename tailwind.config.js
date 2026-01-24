/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/templates/**/*.html", "./src/**/*.py"],
  theme: {
    extend: {
      colors: {
        primary: {
          50: "#ecfdfb",
          100: "#d1faf4",
          200: "#a7f3ea",
          300: "#5eead4",
          400: "#2dd4bf",
          500: "#14b8a6",
          600: "#0d9488",
          700: "#0f766e",
          800: "#115e59",
          900: "#134e4a",
        },
      },
    },
  },
  plugins: [],
};
