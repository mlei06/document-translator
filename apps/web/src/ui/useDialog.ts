// Modal dialog behaviour: Escape closes, Tab stays inside, focus returns to where it was.
import { useEffect, useEffectEvent, type RefObject } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function useDialog(ref: RefObject<HTMLElement | null>, onClose: () => void): void {
  const close = useEffectEvent(onClose)
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null
    const onKey = (e: KeyboardEvent) => {
      const root = ref.current
      if (!root) return
      // Only the topmost dialog handles keys.
      const dialogs = [...document.querySelectorAll('[role=dialog][aria-modal=true]')]
      if (dialogs[dialogs.length - 1] !== root) return
      if (e.key === 'Escape') {
        e.preventDefault()
        close()
        return
      }
      if (e.key !== 'Tab') return
      const items = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (el) => el.offsetParent !== null,
      )
      if (!items.length) return
      const first = items[0]!
      const last = items[items.length - 1]!
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    addEventListener('keydown', onKey)
    return () => {
      removeEventListener('keydown', onKey)
      if (before && document.contains(before)) before.focus()
    }
  }, [ref])
}
