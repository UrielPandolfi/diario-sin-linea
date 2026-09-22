import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./features/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        nav: "var(--nav)",
        surface: {
          DEFAULT: "var(--surface)",
          secondary: "var(--surface-secondary)",
        },
        border: "var(--border)",
        primary: "var(--text-primary)",
        secondary: "var(--text-secondary)",
        accent: {
          DEFAULT: "var(--accent)",
          petrol: "var(--accent-petrol)",
          blue: "var(--accent-blue)",
          ochre: "var(--accent-ochre)",
        },
        action: "var(--action)",
        "on-action": "var(--on-action)",
        amber: {
          bg: "var(--amber-bg)",
          fg: "var(--amber-fg)",
        },
        bronze: "var(--bronze)",
        hover: "var(--hover)",
        muted: "var(--muted)",
        focus: "var(--focus)",
      },
      fontFamily: {
        heading: ["var(--font-heading)", "Newsreader", "Georgia", "Times New Roman", "serif"],
        serif: ["var(--font-heading)", "Newsreader", "Georgia", "Times New Roman", "serif"],
        sans: ["var(--font-sans)", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      maxWidth: {
        measure: "42.5rem",
        article: "72rem",
      },
      boxShadow: {
        float: "0 12px 32px var(--shadow)",
      },
    },
  },
  plugins: [],
};

export default config;
