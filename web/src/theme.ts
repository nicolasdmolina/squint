import { defineTheme } from '@astryxdesign/core/theme';

// Astryx owns component behaviour, focus and interaction states; these tokens repaint it as the
// galley proof: graphite controls on white proof stock, square-cut corners, no resting shadows.
// The two evidence pencils live only in styles/tokens.css and never reach a control.
const ink: [string, string] = ['#17191c', '#e7eaec'];
const ground: [string, string] = ['#eef0ed', '#0e1114'];
const card: [string, string] = ['#ffffff', '#161a1e'];
const muted: [string, string] = ['#5b6269', '#8f989f'];

export const squintTheme = defineTheme({
  name: 'squint',
  tokens: {
    '--color-accent': ink,
    '--color-accent-muted': ['#e4e7e3', '#262c32'],
    '--color-on-accent': card,
    '--color-text-accent': ink,
    '--color-icon-accent': ink,
    '--color-background-body': ground,
    '--color-background-surface': ground,
    '--color-background-card': card,
    '--color-background-popover': card,
    '--color-background-muted': ['#f5f6f4', '#12161a'],
    '--color-text-primary': ink,
    '--color-text-secondary': ['#40464d', '#bac1c7'],
    '--color-text-disabled': muted,
    '--color-icon-primary': ink,
    '--color-icon-secondary': ['#40464d', '#bac1c7'],
    '--color-icon-disabled': muted,
    '--color-border': ['#b9beb9', '#3a424a'],
    '--color-border-emphasized': ink,
    '--color-tint-hover': ['rgba(22, 25, 29, 0.05)', 'rgba(230, 234, 236, 0.07)'],
    '--color-overlay-hover': ['rgba(22, 25, 29, 0.05)', 'rgba(230, 234, 236, 0.07)'],
    '--color-overlay-pressed': ['rgba(22, 25, 29, 0.1)', 'rgba(230, 234, 236, 0.12)'],
    '--color-track': ['#dcdfdb', '#262c32'],
    // Errors speak in ink with an icon and words: no alarm colour on a page about people.
    '--color-error': ink,
    '--color-error-muted': ['#f5f6f4', '#12161a'],
    '--color-on-error': card,
    '--font-family-body': '"Archivo Variable", "Archivo", ui-sans-serif, system-ui, sans-serif',
    '--font-family-heading': '"Archivo Variable", "Archivo", ui-sans-serif, system-ui, sans-serif',
    '--font-family-code': 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    '--radius-element': '4px',
    '--radius-container': '2px',
    '--radius-inner': '2px',
    '--radius-page': '0px',
    '--shadow-low': 'none',
    '--shadow-med': '0 14px 36px -10px rgba(15, 22, 30, 0.28)',
    '--shadow-high': '0 14px 36px -10px rgba(15, 22, 30, 0.28)',
  },
});
