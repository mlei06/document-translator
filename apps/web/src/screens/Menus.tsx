// Lenny's menu and the account menu: keyboard navigable (arrows, Home/End, Escape, Tab closes).
import { useLayoutEffect, useRef, type RefObject } from 'react'
import { menuKeys, useOutsideClose } from '../ui/menu'
import { Icon, type IconName } from '../ui/icons'

export interface MenuItem {
  act: string
  icon: IconName
  label: string
  run: () => void
}

export function LennyMenu({
  open,
  anchor,
  head,
  sub,
  items,
  onClose,
  onSettings,
}: {
  open: boolean
  anchor: RefObject<HTMLElement | null>
  head: string
  sub: string
  items: MenuItem[]
  onClose: (refocus: boolean) => void
  onSettings: () => void
}) {
  const menu = useRef<HTMLDivElement>(null)
  useOutsideClose(open, [menu, anchor], onClose)

  useLayoutEffect(() => {
    const m = menu.current
    const a = anchor.current
    if (!open || !m || !a) return
    const place = () => {
      const r = a.getBoundingClientRect()
      const mw = m.offsetWidth
      const mh = m.offsetHeight
      let x: number
      let y: number
      let origin: string
      if (r.right + 4 + mw < innerWidth - 12) {
        x = r.right - r.width * 0.06
        y = r.top + r.height * 0.18
        origin = 'left top'
      } else if (r.left - mw > 12) {
        x = r.left + r.width * 0.06 - mw
        y = r.top + r.height * 0.18
        origin = 'right top'
      } else {
        x = (innerWidth - mw) / 2
        y = r.bottom + 6
        origin = 'center top'
      }
      m.style.left = `${Math.max(12, x)}px`
      m.style.top = `${Math.max(12, Math.min(innerHeight - mh - 12, y))}px`
      m.style.setProperty('--origin', origin)
    }
    place()
    m.querySelector<HTMLElement>('.mi')?.focus()
    addEventListener('resize', place)
    return () => removeEventListener('resize', place)
  }, [open, anchor])

  return (
    <div
      id="lmenu"
      ref={menu}
      className="lmenu"
      role="menu"
      aria-label="Lenny"
      hidden={!open}
      onKeyDown={(e) => menuKeys(e, onClose)}
    >
      {open ? (
        <>
          <div className="m-head">
            <b>{head}</b>
            <span>{sub}</span>
          </div>
          {items.map((it) => (
            <button
              key={it.act}
              className="mi"
              type="button"
              role="menuitem"
              data-act={it.act}
              onClick={() => {
                onClose(false)
                it.run()
              }}
            >
              <Icon name={it.icon} />
              {it.label}
            </button>
          ))}
          <hr />
          <button
            className="mi"
            type="button"
            role="menuitem"
            data-act="settings"
            onClick={onSettings}
          >
            <Icon name="settings" />
            Lenny settings
          </button>
        </>
      ) : null}
    </div>
  )
}
