import { defineTheme } from '@astryxdesign/core/theme';

// Astryx owns component behaviour, focus and interaction states; these tokens repaint it as the
// reading card: graphite controls on card stock, soft rounded corners, two quiet shadow tiers.
// The duochrome evidence pair lives only in styles/tokens.css and never reaches a control.
const ink: [string, string] = ['#16191d', '#e6eaec'];
const ground: [string, string] = ['#eef1f0', '#11161a'];
const card: [string, string] = ['#fcfdfc', '#182025'];
const muted: [string, string] = ['#5f666e', '#949da4'];

export const squintTheme = defineTheme({
  name: 'squint',
  tokens: {
    '--color-accent': ink,
    '--color-accent-muted': ['#e3e7e5', '#273137'],
    '--color-on-accent': card,
    '--color-text-accent': ink,
    '--color-icon-accent': ink,
    '--color-background-body': ground,
    '--color-background-surface': ground,
    '--color-background-card': card,
    '--color-background-popover': card,
    '--color-background-muted': ['#f4f6f5', '#141b1f'],
    '--color-text-primary': ink,
    '--color-text-secondary': ['#454b53', '#b8c0c6'],
    '--color-text-disabled': muted,
    '--color-icon-primary': ink,
    '--color-icon-secondary': ['#454b53', '#b8c0c6'],
    '--color-icon-disabled': muted,
    '--color-border': ['#b4bcb9', '#3b464d'],
    '--color-border-emphasized': ink,
    '--color-tint-hover': ['rgba(22, 25, 29, 0.05)', 'rgba(230, 234, 236, 0.07)'],
    '--color-overlay-hover': ['rgba(22, 25, 29, 0.05)', 'rgba(230, 234, 236, 0.07)'],
    '--color-overlay-pressed': ['rgba(22, 25, 29, 0.1)', 'rgba(230, 234, 236, 0.12)'],
    '--color-track': ['#dbe0de', '#273137'],
    // Errors speak in ink with an icon and words: no alarm colour on a page about people.
    '--color-error': ink,
    '--color-error-muted': ['#f4f6f5', '#141b1f'],
    '--color-on-error': card,
    '--font-family-body': '"Archivo Variable", "Archivo", ui-sans-serif, system-ui, sans-serif',
    '--font-family-heading': '"Archivo Variable", "Archivo", ui-sans-serif, system-ui, sans-serif',
    '--font-family-code': 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    '--radius-element': '10px',
    '--radius-container': '16px',
    '--radius-inner': '6px',
    '--radius-page': '0px',
    '--shadow-low': '0 1px 2px rgba(20, 30, 34, 0.06)',
    '--shadow-med': '0 18px 40px -12px rgba(20, 30, 34, 0.22)',
    '--shadow-high': '0 18px 40px -12px rgba(20, 30, 34, 0.22)',
  },
});
