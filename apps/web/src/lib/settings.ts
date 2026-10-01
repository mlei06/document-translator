// Lenny settings: harmless per-browser preferences (P6 plan). Never user data or credentials.
import { useSyncExternalStore } from 'react'

export type Theme = 'system' | 'light' | 'dark'

export interface Settings {
  hue: number
  sprout: boolean
  /** Default target language code; '' asks every time. */
  lang: string
  follow: boolean
  playful: boolean
  theme: Theme
}

export const DEFAULTS: Settings = {
  hue: 162,
  sprout: true,
  lang: '',
  follow: true,
  playful: true,
  theme: 'system',
}

export const SWATCHES: [string, number][] = [
  ['Mint', 162],
  ['Sky', 205],
  ['Lilac', 262],
  ['Rose', 340],
  ['Peach', 22],
  ['Sunny', 45],
]

const KEY = 'lenny.settings'
const listeners = new Set<() => void>()

function load(): Settings {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEY) ?? '{}')
    if (raw && typeof raw === 'object') {
      const merged = { ...DEFAULTS }
      for (const k of Object.keys(DEFAULTS) as (keyof Settings)[]) {
        const v = (raw as Record<string, unknown>)[k]
        if (typeof v === typeof DEFAULTS[k]) (merged as Record<string, unknown>)[k] = v
      }
      return merged
    }
  } catch {
    // unreadable or blocked storage: defaults
  }
  return { ...DEFAULTS }
}

let current = load()

export function getSettings(): Settings {
  return current
}

export function updateSettings(patch: Partial<Settings>): void {
  current = { ...current, ...patch }
  try {
    localStorage.setItem(KEY, JSON.stringify(current))
  } catch {
    // private window or blocked storage: keep for this page only
  }
  applyLook(current)
  listeners.forEach((l) => l())
}

export function resetSettings(): void {
  updateSettings({ ...DEFAULTS })
}

export function useSettings(): Settings {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => current,
  )
}

/** Lenny's colour and sprout live in CSS custom properties, as in the mock. */
export function applyLook(s: Settings): void {
  const r = document.documentElement.style
  const h = s.hue
  r.setProperty('--lb0', `hsl(${h} 90% 95%)`)
  r.setProperty('--lb1', `hsl(${h} 62% 78%)`)
  r.setProperty('--lb2', `hsl(${h} 46% 54%)`)
  r.setProperty('--lb3', `hsl(${h} 54% 35%)`)
  r.setProperty('--lshade', `hsl(${h} 58% 26%)`)
  r.setProperty('--lenny-deep', `hsl(${h} 54% 38%)`)
  document.body.classList.toggle('no-sprout', !s.sprout)
}
