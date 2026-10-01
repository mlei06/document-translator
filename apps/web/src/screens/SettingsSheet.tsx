// Lenny settings: look, theme, default language and engine, behaviour. Saved in this browser.
import { useEffect, useRef } from 'react'
import { Lenny } from '../lenny/Lenny'
import { languageName } from '../lib/format'
import { boop } from '../lib/motion'
import {
  resetSettings,
  SWATCHES,
  updateSettings,
  useSettings,
  type Settings,
  type Theme,
} from '../lib/settings'
import { applyTheme } from '../lib/theme'
import { useDialog } from '../ui/useDialog'
type Flag = 'sprout' | 'follow' | 'playful'
export function SettingsSheet({
  languages,
  onClose,
}: {
  languages: string[]
  onClose: () => void
}) {
  const s = useSettings()
  const lenny = useRef<SVGSVGElement>(null)
  const sheet = useRef<HTMLDivElement>(null)
  useDialog(sheet, onClose)
  useEffect(() => {
    sheet.current?.querySelector<HTMLElement>('input[name=lhue]:checked, #hue')?.focus()
  }, [])
  const set = (patch: Partial<Settings>) => updateSettings(patch)
  const sw = (key: Flag, label: string) => (
    <button
      className="switch"
      type="button"
      role="switch"
      aria-checked={s[key]}
      aria-label={label}
      onClick={() => {
        set({ [key]: !s[key] } as Partial<Settings>)
        if (key !== 'follow') boop(lenny.current)
      }}
    />
  )
  return (
    <div
      id="settings"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="set-title"
        ref={sheet}
      >
        <div className="sheet-head">
          <h2 id="set-title">Lenny settings</h2>
          <p>Make Lenny yours. Appearance and defaults save in this browser.</p>
        </div>
        <div className="sheet-body">
          <section className="set-group">
            <h3>Look</h3>
            <div className="look">
              <div className="look-stage">
                <Lenny ref={lenny} size="preview" />
              </div>
              <div className="look-ctl">
                <div className="swatches" role="radiogroup" aria-label="Lenny's color">
                  {SWATCHES.map(([name, hue]) => (
                    <label className="sw" title={name} key={name}>
                      <input
                        type="radio"
                        name="lhue"
                        value={hue}
                        aria-label={name}
                        checked={s.hue === hue}
                        onChange={() => set({ hue })}
                      />
                      <span style={{ ['--c' as string]: `hsl(${hue} 50% 58%)` }} />
                    </label>
                  ))}
                </div>
                <label className="hue-l" htmlFor="hue">
                  Or pick any color
                </label>
                <input
                  className="hue"
                  id="hue"
                  type="range"
                  min={0}
                  max={359}
                  value={s.hue}
                  onChange={(e) => set({ hue: Number(e.target.value) })}
                />
                <div className="set-row compact">
                  <div>
                    <b>Sprout</b>
                  </div>
                  {sw('sprout', 'Sprout')}
                </div>
              </div>
            </div>
          </section>
          <section className="set-group">
            <h3>Theme</h3>
            <div className="set-row">
              <div>
                <b>Meadow</b>
                <span>Day or night. System follows your computer.</span>
              </div>
              <div className="seg" role="group" aria-label="Theme">
                {(
                  [
                    ['system', 'System'],
                    ['light', 'Day'],
                    ['dark', 'Night'],
                  ] as [Theme, string][]
                ).map(([v, l]) => (
                  <button
                    key={v}
                    type="button"
                    aria-pressed={s.theme === v}
                    onClick={() => {
                      set({ theme: v })
                      applyTheme(v, true)
                    }}
                  >
                    {l}
                  </button>
                ))}
              </div>
            </div>
          </section>
          <section className="set-group">
            <h3>Translation</h3>
            <div className="set-row">
              <div>
                <b>Default language</b>
                <span>New files translate into this language automatically.</span>
              </div>
              <select
                className="sc-select"
                id="deflang"
                aria-label="Default language"
                value={s.lang}
                onChange={(e) => set({ lang: e.target.value })}
              >
                <option value="">Ask me every time</option>
                {languages.map((l) => (
                  <option key={l} value={l}>
                    {languageName(l)}
                  </option>
                ))}
              </select>
            </div>
          </section>
          <section className="set-group">
            <h3>Behavior</h3>
            <div className="set-row">
              <div>
                <b>Follow my cursor</b>
                <span>Lenny watches your pointer and anything you drag.</span>
              </div>
              {sw('follow', 'Follow my cursor')}
            </div>
            <div className="set-row">
              <div>
                <b>Playful reactions</b>
                <span>Hops and cheers when files finish.</span>
              </div>
              {sw('playful', 'Playful reactions')}
            </div>
          </section>
        </div>
        <div className="sheet-foot">
          <button
            className="btn alt"
            type="button"
            onClick={() => {
              resetSettings()
              applyTheme('system', true)
              boop(lenny.current)
            }}
          >
            Reset browser preferences
          </button>
          <button className="btn" type="button" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
