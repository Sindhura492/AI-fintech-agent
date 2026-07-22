/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: 'var(--ink-950)',
          900: 'var(--ink-900)',
          800: 'var(--ink-800)',
          700: 'var(--ink-700)',
          500: 'var(--ink-500)',
          300: 'var(--ink-300)',
          100: 'var(--ink-100)',
        },
        teal: {
          accent: 'var(--teal-accent)',
          muted: 'var(--teal-muted)',
          soft: 'var(--teal-soft)',
        },
        paper: {
          DEFAULT: 'var(--paper)',
          warm: 'var(--paper-warm)',
          edge: 'var(--paper-edge)',
        },
        gate: {
          approve: 'var(--gate-approve)',
          deny: 'var(--gate-deny)',
          escalate: 'var(--gate-escalate)',
        },
      },
      fontFamily: {
        display: ['"Fraunces"', 'Georgia', 'serif'],
        sans: ['"Source Sans 3"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 0 rgba(255,255,255,0.04) inset, 0 12px 40px rgba(0,0,0,0.35)',
      },
      keyframes: {
        pulseDot: {
          '0%': { boxShadow: '0 0 0 0 rgba(45, 212, 168, 0.55)' },
          '70%': { boxShadow: '0 0 0 8px rgba(45, 212, 168, 0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(45, 212, 168, 0)' },
        },
        rise: {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        typing: {
          '0%, 60%, 100%': { opacity: '0.35', transform: 'translateY(0)' },
          '30%': { opacity: '1', transform: 'translateY(-3px)' },
        },
      },
      animation: {
        pulseDot: 'pulseDot 1.6s ease-out infinite',
        rise: 'rise 0.3s ease-out',
        typing: 'typing 1.2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
