/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: 'class',
  theme: {
    extend: {
      keyframes: {
        'progress-shimmer': {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
        // Per-digit entrance for live timers: a brief upward slide + scale up
        // from a blurred slightly-smaller state. Triggered by remounting the
        // changed character via a key change.
        'digit-tick': {
          '0%': {
            transform: 'translateY(0.4em) scale(0.9)',
            opacity: '0',
            filter: 'blur(4px)',
          },
          '100%': {
            transform: 'translateY(0) scale(1)',
            opacity: '1',
            filter: 'blur(0)',
          },
        },
      },
      animation: {
        'progress-shimmer': 'progress-shimmer 2.4s linear infinite',
        'digit-tick': 'digit-tick 0.35s cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
    },
  },
  plugins: [],
};
