// Menu keyboard and outside-click behaviour shared by Lenny's menu and the account menu.
import { useEffect, useEffectEvent, type KeyboardEvent, type RefObject } from 'react'

export function menuKeys(e: KeyboardEvent<HTMLElement>, close: (refocus: boolean) => void): void {
  const items = [...e.currentTarget.querySelectorAll<HTMLElement>('.mi')]
  const i = items.indexOf(document.activeElement as HTMLElement)
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus()
  } else if (e.key === 'Home' || e.key === 'End') {
    e.preventDefault()
    items[e.key === 'Home' ? 0 : items.length - 1]?.focus()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    close(true)
  } else if (e.key === 'Tab') close(false)
}

/** Close when clicking anywhere outside the menu and its anchor. */
export function useOutsideClose(
  open: boolean,
  refs: RefObject<HTMLElement | null>[],
  close: (refocus: boolean) => void,
): void {
  const onDown = useEffectEvent((e: PointerEvent) => {
    if (refs.some((r) => r.current?.contains(e.target as Node))) return
    close(false)
  })
  useEffect(() => {
    if (!open) return
    addEventListener('pointerdown', onDown)
    return () => removeEventListener('pointerdown', onDown)
  }, [open])
}
