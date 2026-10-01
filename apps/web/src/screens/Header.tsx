// Header: brand, History, day/night and the account menu (identity from the service).
import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import type { Me } from '../api/client'
import { useWorkspace } from '../app/workspace'
import { initials } from '../lib/format'
import { cheer, big, reducedMotion } from '../lib/motion'
import { updateSettings } from '../lib/settings'
import { applyTheme, isDark, useDark } from '../lib/theme'
import { Icon } from '../ui/icons'
import { menuKeys, useOutsideClose } from '../ui/menu'

export function ThemeButton({ onToggled }: { onToggled?: (night: boolean) => void }) {
  const dark = useDark()
  const label = dark ? 'Switch to day' : 'Switch to night'
  return (
    <button
      className="icon-btn"
      type="button"
      data-act="theme"
      aria-label={label}
      title={label}
      onClick={() => {
        const theme = isDark() ? 'light' : 'dark'
        updateSettings({ theme })
        applyTheme(theme, true)
        onToggled?.(theme === 'dark')
      }}
    >
      <Icon name={dark ? 'sun' : 'moon'} />
    </button>
  )
}

export function Header({ me }: { me: Me }) {
  const ws = useWorkspace()
  const [open, setOpen] = useState(false)
  const chip = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const close = useCallback((refocus: boolean) => {
    setOpen(false)
    if (refocus) chip.current?.focus()
  }, [])
  useOutsideClose(open, [menu, chip], close)

  useLayoutEffect(() => {
    const m = menu.current
    const c = chip.current
    if (!open || !m || !c) return
    const r = c.getBoundingClientRect()
    m.style.left = `${Math.max(12, r.right - m.offsetWidth)}px`
    m.style.top = `${r.bottom + 6}px`
    m.style.setProperty('--origin', 'right top')
    m.querySelector<HTMLElement>('.mi')?.focus()
  }, [open])

  const item = (
    label: string,
    icon: 'history' | 'settings' | 'rotate' | 'logout',
    run: () => void,
  ) => (
    <button
      className="mi"
      type="button"
      role="menuitem"
      onClick={() => {
        close(false)
        run()
      }}
    >
      <Icon name={icon} />
      {label}
    </button>
  )

  return (
    <>
      <header className="top">
        <div className="brand">
          <span className="sc-logo">
            <Icon name="brand" />
          </span>
          <span>Lenny</span>
          <small>Document Translator</small>
        </div>
        <div className="hdr-right" id="appActions">
          <button
            className="icon-btn"
            type="button"
            data-act="history"
            aria-label="Open History"
            title="History"
            onClick={ws.openHistory}
          >
            <Icon name="history" />
          </button>
          <ThemeButton
            onToggled={(night) => {
              cheer(big())
              ws.say({
                say: night ? 'Ooh, fireflies!' : 'Good morning!',
                sub: night ? 'Night mode is on.' : 'Day mode is on.',
              })
              setTimeout(ws.restoreSpeech, reducedMotion() ? 1200 : 2200)
            }}
          />
          <button
            className="uchip"
            id="uchip"
            ref={chip}
            type="button"
            aria-haspopup="menu"
            aria-expanded={open}
            aria-label={`Account: ${me.display_name}`}
            onClick={() => setOpen((o) => !o)}
          >
            <span className="avatar" id="uavatar" aria-hidden="true">
              {initials(me.display_name)}
            </span>
            <span id="uname">{me.display_name}</span>
            <Icon name="chevron" />
          </button>
        </div>
      </header>
      <div
        id="umenu"
        ref={menu}
        className="lmenu"
        role="menu"
        aria-label="Account"
        hidden={!open}
        onKeyDown={(e) => menuKeys(e, close)}
      >
        {open ? (
          <>
            <div className="m-head">
              <b>{me.display_name}</b>
              <span>Signed in</span>
            </div>
            {item('History', 'history', ws.openHistory)}
            {item('Lenny settings', 'settings', ws.openSettings)}
            {item('Start over', 'rotate', ws.startOver)}
            <hr />
            {item('Sign out', 'logout', ws.signOut)}
          </>
        ) : null}
      </div>
    </>
  )
}
