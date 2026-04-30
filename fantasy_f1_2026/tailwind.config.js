/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        f1red: '#E10600',
        f1dark: '#0F0F0F',
        f1card: '#1A1A1A',
        f1border: '#2A2A2A',
        f1muted: '#6B7280',
      },
    },
  },
  plugins: [],
}

