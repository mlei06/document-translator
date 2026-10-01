// Lenny's speech: words fade in one by one while the mouth moves; mirrored to screen readers
// through the polite live region.
import { Fragment, useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react'
import { mood } from '../lib/motion'

export interface Line {
  say: string
  sub?: string
  extra?: ReactNode
}

export function Speech({
  id,
  line,
  who,
  style,
  live = true,
}: {
  id: string
  line: Line
  who: RefObject<SVGSVGElement | null>
  style?: React.CSSProperties
  live?: boolean
}) {
  const box = useRef<HTMLDivElement>(null)
  const words = line.say.split(/\s+/).filter(Boolean)

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    el.classList.remove('settled', 'pop')
    el.getBoundingClientRect()
    el.classList.add('pop')
    const t = setTimeout(() => el.classList.add('settled'), words.length * 34 + 800)
    mood(who.current, 'talk', Math.min(1800, 160 + words.length * 80))
    return () => clearTimeout(t)
    // Replay only when the words change, like the mock's setSay.
  }, [line.say, line.sub, words.length, who])

  return (
    <div
      id={id}
      ref={box}
      className="speech"
      aria-live={live ? 'polite' : 'off'}
      style={{ ...style, ['--n' as string]: words.length }}
    >
      <p className="say">
        {words.map((w, i) => (
          <Fragment key={`${i}-${w}`}>
            {i ? ' ' : null}
            <span className="w" style={{ ['--i' as string]: i }}>
              {w}
            </span>
          </Fragment>
        ))}
      </p>
      {line.sub ? <p className="sub">{line.sub}</p> : null}
      <div className="extra">{line.extra}</div>
    </div>
  )
}
