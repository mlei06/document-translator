// Day/night meadow. The chosen theme is a local setting; "system" follows the computer.
import { useSyncExternalStore } from 'react'
import { reducedMotion } from './motion'
import { getSettings, type Theme } from './settings'

const darkQuery = matchMedia('(prefers-color-scheme: dark)')
const listeners = new Set<() => void>()
let animTimer = 0

export function isDark(): boolean {
  const t = document.documentElement.dataset.theme
  return t ? t === 'dark' : darkQuery.matches
}

export function applyTheme(theme: Theme, animate: boolean): void {
  const root = document.documentElement
  if (animate && !reducedMotion()) {
    root.classList.add('theme-anim')
    clearTimeout(animTimer)
    animTimer = window.setTimeout(() => root.classList.remove('theme-anim'), 700)
  }
  if (theme === 'light' || theme === 'dark') root.dataset.theme = theme
  else delete root.dataset.theme
  listeners.forEach((l) => l())
}

darkQuery.addEventListener('change', () => listeners.forEach((l) => l()))

export function useDark(): boolean {
  return useSyncExternalStore((l) => {
    listeners.add(l)
    return () => listeners.delete(l)
  }, isDark)
}

export function initTheme(): void {
  applyTheme(getSettings().theme, false)
}
