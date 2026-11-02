"""Tailwind configuration — theme tokens (colors, fonts, shadows) used by the UI."""

# --- embedded Tailwind theme config ---
TAILWIND_CONFIG_JS = r'''tailwind.config = {
  theme: { extend: {
    colors: {
      paper:'rgb(var(--c-paper) / <alpha-value>)', card:'rgb(var(--c-card) / <alpha-value>)', ink:'rgb(var(--c-ink) / <alpha-value>)', muted:'rgb(var(--c-muted) / <alpha-value>)', line:'rgb(var(--c-line) / <alpha-value>)',
      rust:{DEFAULT:'rgb(var(--c-rust) / <alpha-value>)', deep:'rgb(var(--c-rust-deep) / <alpha-value>)', tint:'rgb(var(--c-rust-tint) / <alpha-value>)'},
      sage:{DEFAULT:'rgb(var(--c-sage) / <alpha-value>)', deep:'rgb(var(--c-sage-deep) / <alpha-value>)', tint:'rgb(var(--c-sage-tint) / <alpha-value>)'},
    },
    fontFamily: {
      display:['Fraunces','Georgia','serif'],
      sans:['"Instrument Sans"','ui-sans-serif','sans-serif'],
    },
    boxShadow: {
      soft:'0 1px 2px rgba(38,34,27,.04), 0 10px 30px -12px rgba(38,34,27,.15)',
      pop:'0 4px 10px rgba(38,34,27,.08), 0 24px 60px -20px rgba(38,34,27,.35)',
    },
  }}
}'''
