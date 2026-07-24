/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        fluvius: {
          50: '#effaf6',
          100: '#d9f4e9',
          500: '#21a179',
          600: '#16856a',
          700: '#116b57',
          800: '#0b5446',
          900: '#083f36',
        },
      },
    },
  },
  plugins: [],
}
