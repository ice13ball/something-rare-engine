/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    fontFamily: {
      sans: ['"Barlow"', 'system-ui', 'sans-serif'],
      mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
    },
    extend: {
      zIndex: {
        panel: "var(--z-panel)",
        "tutorial-ring": "var(--z-tutorial-ring)",
        overlay: "var(--z-overlay)",
        "tutorial-bar": "var(--z-tutorial-bar)",
        tooltip: "var(--z-tooltip)",
        toast: "var(--z-toast)",
        "skip-nav": "var(--z-skip-nav)",
      },
      colors: {
        surface: {
          primary: "var(--surface-primary)",
          overlay: "var(--surface-overlay)",
          dim: "var(--surface-dim)",
          scrim: "var(--surface-scrim)",
        },
        page: {
          bg: "var(--page-bg)",
        },
      },
      borderColor: {
        subtle: "var(--border-subtle)",
        muted: "var(--border-muted)",
      },
      textColor: {
        primary: "var(--text-primary)",
        secondary: "var(--text-secondary)",
        tertiary: "var(--text-tertiary)",
        muted: "var(--text-muted)",
        faint: "var(--text-faint)",
      },
    },
  },
  plugins: [],
};
