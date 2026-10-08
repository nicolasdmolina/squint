import { defineTheme } from '@astryxdesign/core/theme';

// Astryx owns component behaviour, focus and interaction states; these tokens repaint it as
// Squint's instrument: chart paper, pen-ink controls, square corners, hairlines, no shadows.
// Signal colours (cobalt, amber) live only in styles/tokens.css and never reach controls.
const ink: [string, string] = ['#141b24', '#e7ecf0'];
const paper: [string, string] = ['#f8fcfd', '#13181d'];
const panel: [string, string] = ['#ffffff', '#191f25'];

export const squintTheme = defineTheme({
  name: 'squint',
  tokens: {
    '--color-accent': ink,
    '--color-accent-muted': ['#e3ebee', '#252e35'],
    '--color-on-accent': paper,
    '--color-text-accent': ink,
    '--color-icon-accent': ink,
    '--color-background-body': paper,
    '--color-background-surface': paper,
    '--color-background-card': panel,
    '--color-background-popover': panel,
    '--color-background-muted': ['#eef5f7', '#1b2228'],
    '--color-text-primary': ink,
    '--color-text-secondary': ['#4b535e', '#b8bfc5'],
    '--color-text-disabled': ['#7b8890', '#78848c'],
    '--color-icon-primary': ink,
    '--color-icon-secondary': ['#4b535e', '#b8bfc5'],
    '--color-icon-disabled': ['#7b8890', '#78848c'],
    '--color-border': ['#7b8890', '#66737c'],
    '--color-border-emphasized': ink,
    '--color-tint-hover': ['rgba(20, 27, 36, 0.06)', 'rgba(231, 236, 240, 0.08)'],
    '--color-overlay-hover': ['rgba(20, 27, 36, 0.06)', 'rgba(231, 236, 240, 0.08)'],
    '--color-overlay-pressed': ['rgba(20, 27, 36, 0.12)', 'rgba(231, 236, 240, 0.14)'],
    '--color-track': ['#d9e3e7', '#2b363e'],
    // Errors stay in pen ink with an icon and words: no alarm colour on a page about people.
    '--color-error': ink,
    '--color-error-muted': ['#eef5f7', '#1b2228'],
    '--color-on-error': paper,
    '--font-family-body': '"Archivo Variable", "Archivo", ui-sans-serif, system-ui, sans-serif',
    '--font-family-heading': '"Archivo Variable", "Archivo", ui-sans-serif, system-ui, sans-serif',
    '--font-family-code': 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    '--radius-element': '0px',
    '--radius-container': '0px',
    '--radius-inner': '0px',
    '--radius-page': '0px',
    '--shadow-low': 'none',
    '--shadow-med': 'none',
    '--shadow-high': 'none',
  },
});
