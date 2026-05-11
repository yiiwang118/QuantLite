/**
 * 主题变量直写：用 JS setProperty 把 CSS variables 写到 documentElement.style。
 * 优先级高于任何 CSS 规则（inline style 永远赢），杜绝 class race / cache 问题。
 */

type Vars = Record<string, string>

export const LIGHT_VARS: Vars = {
  '--bg-base': '#f5f6fb',
  '--bg-mesh-1': 'rgba(124, 58, 237, 0.07)',
  '--bg-mesh-2': 'rgba(6, 182, 212, 0.05)',
  '--bg-mesh-3': 'rgba(236, 72, 153, 0.04)',

  '--card-bg': '#ffffff',
  '--card-elev-bg': '#ffffff',

  '--surface-1': '#f8f9fd',
  '--surface-2': '#eef1f8',
  '--surface-3': '#e2e7f1',
  '--surface-deep': '#15182c',

  '--text-primary': '#0f172a',
  '--text-secondary': '#334155',
  '--text-muted': '#94a3b8',
  '--text-on-deep': '#e2e8f0',
  '--text-on-accent': '#ffffff',

  '--border-soft': 'rgba(15, 23, 42, 0.08)',
  '--border-strong': 'rgba(15, 23, 42, 0.18)',
  '--border-accent': 'rgba(124, 58, 237, 0.40)',

  '--brand': '#7c3aed',
  '--brand-grad': 'linear-gradient(135deg, #7c3aed 0%, #4f46e5 50%, #0891b2 100%)',
  '--accent': '#6d28d9',
  '--accent-bg-soft': 'rgba(124, 58, 237, 0.08)',
  '--accent-bg-hover': 'rgba(124, 58, 237, 0.16)',
  '--user-bubble-bg': 'linear-gradient(135deg, rgba(124, 58, 237, 0.14) 0%, rgba(6, 182, 212, 0.08) 100%)',
  '--user-bubble-border': 'rgba(124, 58, 237, 0.28)',

  '--success': '#059669',
  '--danger': '#dc2626',
  '--warning': '#d97706',
  '--info': '#2563eb',
  '--success-bg': 'rgba(16, 185, 129, 0.10)',
  '--danger-bg': 'rgba(239, 68, 68, 0.08)',
  '--warning-bg': 'rgba(245, 158, 11, 0.10)',

  '--shadow-sm': '0 1px 2px rgba(15, 23, 42, 0.06)',
  '--shadow-md': '0 2px 6px rgba(15, 23, 42, 0.06), 0 8px 24px rgba(15, 23, 42, 0.06)',
  '--shadow-lg': '0 4px 12px rgba(15, 23, 42, 0.08), 0 16px 40px rgba(15, 23, 42, 0.10)',
  '--shadow-glow': '0 0 0 1px rgba(124, 58, 237, 0.20), 0 8px 28px rgba(124, 58, 237, 0.14)',
  '--focus-ring': '0 0 0 3px rgba(124, 58, 237, 0.20)',

  '--chart-axis-label': '#64748b',
  '--chart-axis-line': 'rgba(15, 23, 42, 0.18)',
  '--chart-split-line': 'rgba(15, 23, 42, 0.06)',
  '--chart-tooltip-bg': 'rgba(15, 23, 42, 0.94)',
  '--chart-tooltip-text': '#f8fafc',
  '--chart-tooltip-border': 'rgba(15, 23, 42, 0.10)',
}

export const DARK_VARS: Vars = {
  '--bg-base': '#07081a',
  '--bg-mesh-1': 'rgba(124, 58, 237, 0.16)',
  '--bg-mesh-2': 'rgba(6, 182, 212, 0.11)',
  '--bg-mesh-3': 'rgba(236, 72, 153, 0.06)',

  '--card-bg': '#0e1124',
  '--card-elev-bg': '#161a37',

  '--surface-1': 'rgba(255, 255, 255, 0.025)',
  '--surface-2': 'rgba(255, 255, 255, 0.05)',
  '--surface-3': 'rgba(255, 255, 255, 0.08)',
  '--surface-deep': 'rgba(0, 0, 0, 0.40)',

  '--text-primary': '#f8fafc',
  '--text-secondary': '#cbd5e1',
  '--text-muted': '#94a3b8',
  '--text-on-deep': '#e2e8f0',
  '--text-on-accent': '#ffffff',

  '--border-soft': 'rgba(255, 255, 255, 0.07)',
  '--border-strong': 'rgba(255, 255, 255, 0.14)',
  '--border-accent': 'rgba(124, 58, 237, 0.35)',

  '--brand': '#7c3aed',
  '--brand-grad': 'linear-gradient(135deg, #8b5cf6 0%, #6366f1 50%, #06b6d4 100%)',
  '--accent': '#a78bfa',
  '--accent-bg-soft': 'rgba(167, 139, 250, 0.14)',
  '--accent-bg-hover': 'rgba(167, 139, 250, 0.22)',
  '--user-bubble-bg': 'linear-gradient(135deg, rgba(124, 58, 237, 0.32) 0%, rgba(6, 182, 212, 0.18) 100%)',
  '--user-bubble-border': 'rgba(124, 58, 237, 0.40)',

  '--success': '#10b981',
  '--danger': '#ef4444',
  '--warning': '#f59e0b',
  '--info': '#3b82f6',
  '--success-bg': 'rgba(16, 185, 129, 0.12)',
  '--danger-bg': 'rgba(239, 68, 68, 0.12)',
  '--warning-bg': 'rgba(245, 158, 11, 0.12)',

  '--shadow-sm': '0 1px 2px rgba(0, 0, 0, 0.25)',
  '--shadow-md': '0 4px 14px rgba(0, 0, 0, 0.30), 0 1px 3px rgba(0, 0, 0, 0.20)',
  '--shadow-lg': '0 12px 32px rgba(0, 0, 0, 0.45), 0 2px 6px rgba(0, 0, 0, 0.30)',
  '--shadow-glow': '0 0 0 1px rgba(124, 58, 237, 0.30), 0 8px 28px rgba(124, 58, 237, 0.22)',
  '--focus-ring': '0 0 0 3px rgba(124, 58, 237, 0.25)',

  '--chart-axis-label': '#94a3b8',
  '--chart-axis-line': 'rgba(255, 255, 255, 0.10)',
  '--chart-split-line': 'rgba(255, 255, 255, 0.05)',
  '--chart-tooltip-bg': 'rgba(15, 17, 36, 0.96)',
  '--chart-tooltip-text': '#f8fafc',
  '--chart-tooltip-border': 'rgba(255, 255, 255, 0.10)',
}

export function applyTheme(isDark: boolean) {
  const root = document.documentElement
  const vars = isDark ? DARK_VARS : LIGHT_VARS
  for (const [k, v] of Object.entries(vars)) {
    root.style.setProperty(k, v)
  }
  root.classList.toggle('dark', isDark)
  root.style.colorScheme = isDark ? 'dark' : 'light'
}
