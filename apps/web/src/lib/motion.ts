// Framework-independent motion from the mock: pointer tracking, Lenny's spring rig, blinks,
// moods, sparkles and thrown cards. Motion never gates data or controls; reduced motion
// shortens or skips it.
import { getSettings } from './settings'

const rmQuery =
  typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null
export const reducedMotion = (): boolean => rmQuery?.matches ?? false

export const dur = (ms: number): number => (reducedMotion() ? 1 : ms)
export const wait = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, reducedMotion() ? Math.min(ms, 300) : ms))

/** Pointer (or dragged file) position that Lenny follows. */
export const pointer = { x: innerWidth / 2, y: innerHeight / 2, dragging: false }
let pointerRaf = 0
let bigLenny: (() => SVGSVGElement | null) | null = null

/** The stage Lenny whose mouth opens toward a dragged file. */
export function registerBigLenny(get: () => SVGSVGElement | null): void {
  bigLenny = get
}
export const big = (): SVGSVGElement | null => bigLenny?.() ?? null

export function track(x: number, y: number): void {
  pointer.x = x
  pointer.y = y
  if (!pointerRaf) pointerRaf = requestAnimationFrame(updateDraggedFileReaction)
}

function updateDraggedFileReaction(): void {
  pointerRaf = 0
  const b = big()
  if (pointer.dragging && b) {
    const m = mouthCenter(b)
    setOpen(
      b,
      Math.max(0.25, Math.min(1, 1.25 - Math.hypot(pointer.x - m.x, pointer.y - m.y) / 380)),
    )
  }
}

export function setOpen(el: Element | null, v: number): void {
  if (el instanceof SVGElement) el.style.setProperty('--open', v.toFixed(2))
}

/** Replay a one-shot CSS mood class (blink, happy, hop, talk, chew, gulp, boop). */
export function mood(el: Element | null, cls: string, ms: number): void {
  if (!el || reducedMotion()) return
  el.classList.remove(cls)
  el.getBoundingClientRect()
  el.classList.add(cls)
  setTimeout(() => el.classList.remove(cls), ms)
}

export function cheer(el: Element | null, ms = 1000): void {
  if (getSettings().playful) mood(el, 'hop', ms)
  mood(el, 'happy', ms + 150)
}

export function boop(el: Element | null): void {
  mood(el, 'boop', 540)
  mood(el, 'happy', 800)
}

export function mouthCenter(el: Element): { x: number; y: number } {
  const m = el.querySelector('.l-mouth')
  const r = (m ?? el).getBoundingClientRect()
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 }
}

// Springs: the face looks toward the pointer and the body leans a little.
interface Rig {
  fx: number
  fy: number
  vx: number
  vy: number
  lean: number
  vl: number
}
const rigs = new WeakMap<Element, Rig>()
let rigT = performance.now()
let rigStarted = false
let rigRaf = 0

function rigLoop(now: number): void {
  rigRaf = 0
  if (reducedMotion()) return
  const dt = Math.min(0.05, (now - rigT) / 1000)
  rigT = now
  const on = getSettings().follow
  document.querySelectorAll<SVGSVGElement>('svg.lenny').forEach((svg) => {
    const r = svg.getBoundingClientRect()
    if (!r.width) return
    let st = rigs.get(svg)
    if (!st) {
      st = { fx: 0, fy: 0, vx: 0, vy: 0, lean: 0, vl: 0 }
      rigs.set(svg, st)
    }
    const dx = pointer.x - (r.left + r.width / 2)
    const dy = pointer.y - (r.top + r.height * 0.45)
    const d = Math.hypot(dx, dy) || 1
    const reach = Math.min(1, d / (r.width * 1.1))
    const tx = on ? (dx / d) * 9 * reach : 0
    const ty = on ? (dy / d) * 6.5 * reach : 0
    const eager = pointer.dragging && svg === big()
    const tl = on ? Math.max(-1, Math.min(1, dx / (r.width * 2))) * (eager ? 9 : 3) : 0
    st.vx += (150 * (tx - st.fx) - 19 * st.vx) * dt
    st.fx += st.vx * dt
    st.vy += (150 * (ty - st.fy) - 19 * st.vy) * dt
    st.fy += st.vy * dt
    st.vl += (80 * (tl - st.lean) - 13 * st.vl) * dt
    st.lean += st.vl * dt
    svg
      .querySelector('.l-face')
      ?.setAttribute('transform', `translate(${st.fx.toFixed(2)} ${st.fy.toFixed(2)})`)
    svg.querySelector('.l-rig')?.setAttribute('transform', `rotate(${st.lean.toFixed(2)} 0 84)`)
  })
  rigRaf = requestAnimationFrame(rigLoop)
}

/** Start the shared loops once: rig springs, blinking and pointer tracking. */
export function startMotion(): void {
  if (rigStarted) return
  rigStarted = true
  addEventListener('pointermove', (e) => track(e.clientX, e.clientY))
  setInterval(() => {
    document.querySelectorAll('svg.lenny').forEach((l) => {
      if (Math.random() < 0.6) mood(l, 'blink', 180)
    })
  }, 2600)
  const syncMotionPreference = () => {
    if (reducedMotion()) {
      cancelAnimationFrame(rigRaf)
      rigRaf = 0
    } else if (!rigRaf) {
      rigT = performance.now()
      rigRaf = requestAnimationFrame(rigLoop)
    }
  }
  rmQuery?.addEventListener('change', syncMotionPreference)
  syncMotionPreference()
}

export function burst(x: number, y: number, n = 12): void {
  if (reducedMotion()) return
  const cols = ['var(--lb1)', '#FFFFFF', '#FFE08A']
  for (let i = 0; i < n; i++) {
    const s = document.createElement('i')
    s.className = 'spark'
    s.style.left = `${x}px`
    s.style.top = `${y}px`
    s.style.setProperty('--c', cols[i % 3]!)
    document.body.append(s)
    const a = (i / n) * 6.283 + Math.random() * 0.4
    const d = 40 + Math.random() * 34
    const sc = 0.6 + Math.random() * 0.9
    s.animate(
      [
        { transform: 'translate(0, 0) scale(0) rotate(0deg)', opacity: 1 },
        {
          transform: `translate(${Math.cos(a) * d}px, ${Math.sin(a) * d}px) scale(${sc}) rotate(${90 + Math.random() * 90}deg)`,
          opacity: 1,
          offset: 0.6,
        },
        {
          transform: `translate(${Math.cos(a) * d * 1.25}px, ${Math.sin(a) * d * 1.25 + 12}px) scale(0) rotate(200deg)`,
          opacity: 0,
        },
      ],
      { duration: 900 + Math.random() * 300, easing: 'cubic-bezier(.2, .8, .3, 1)' },
    ).finished.then(
      () => s.remove(),
      () => s.remove(),
    )
  }
}

export function burstAt(el: Element | null | undefined, n = 12): void {
  const r = el?.getBoundingClientRect()
  if (r?.width) burst(r.left + r.width / 2, r.top + r.height / 2, n)
}

/** Keyframes along a parabola: things are tossed, not slid. */
export function arcFrames(
  dx: number,
  dy: number,
  lift: number,
  endScale: number,
  endRot: number,
): Keyframe[] {
  const f: Keyframe[] = []
  const n = 14
  for (let i = 0; i <= n; i++) {
    const t = i / n
    f.push({
      transform: `translate(${(dx * t).toFixed(1)}px, ${(dy * t - lift * 4 * t * (1 - t)).toFixed(1)}px) scale(${(1 + (endScale - 1) * t * t).toFixed(3)}) rotate(${(endRot * t).toFixed(1)}deg)`,
      opacity: t < 0.8 ? 1 : 1 - (t - 0.8) * 2.5,
    })
  }
  return f
}

export function spitFrames(ox: number, oy: number): Keyframe[] {
  const lift = 110 + Math.random() * 60
  const f: Keyframe[] = []
  const n = 14
  for (let i = 0; i <= n; i++) {
    const t = i / n
    f.push({
      transform: `translate(${(ox * (1 - t)).toFixed(1)}px, ${(oy * (1 - t) - lift * 4 * t * (1 - t)).toFixed(1)}px) scale(${(0.08 + 1.04 * t).toFixed(3)})`,
      opacity: Math.min(1, 0.3 + t * 2),
      offset: t * 0.8,
    })
  }
  f.push({ transform: 'scale(.97)', offset: 0.9 }, { transform: 'none', offset: 1 })
  return f
}

/** Throw a file card from a point into Lenny's mouth (or bounce it off when rejected). */
export function flyCard(
  tag: string,
  tc: string,
  name: string,
  from: { x: number; y: number },
  to: { x: number; y: number },
  i: number,
  reject: boolean,
): Promise<void> {
  const el = document.createElement('div')
  el.className = 'flycard'
  const t = document.createElement('span')
  t.className = 'tag'
  t.style.setProperty('--tc', tc)
  t.textContent = tag
  const n = document.createElement('span')
  n.textContent = name
  el.append(t, n)
  document.body.append(el)
  el.style.left = `${from.x - el.offsetWidth / 2}px`
  el.style.top = `${from.y - el.offsetHeight / 2}px`
  const dx = to.x - from.x
  const dy = to.y - from.y
  const kf: Keyframe[] = reject
    ? [
        { transform: 'none' },
        {
          transform: `translate(${dx * 0.85}px,${dy * 0.85}px) scale(.5) rotate(-10deg)`,
          offset: 0.45,
        },
        {
          transform: `translate(${dx * 0.55 + 140}px,${dy * 0.55 + 120}px) scale(.8) rotate(160deg)`,
          opacity: 0,
        },
      ]
    : arcFrames(dx, dy, Math.min(170, Math.abs(dx) * 0.3 + 70), 0.1, 18)
  const a = el.animate(kf, {
    duration: dur(reject ? 1000 : 760),
    delay: reducedMotion() ? 0 : i * 130,
    easing: reject ? 'ease-in-out' : 'cubic-bezier(.45, .05, .6, .95)',
    fill: 'forwards',
  })
  return a.finished.then(
    () => el.remove(),
    () => el.remove(),
  )
}

/** Toss a cleared bubble up into the header's Your files button. */
export function tossToHistory(el: HTMLElement | null, i = 0): Promise<void> {
  const btn = document.querySelector('header [data-act=history]')
  const orb = el?.querySelector('.orb')
  const ping = () => {
    if (!btn) return
    btn.classList.remove('ping')
    void (btn as HTMLElement).offsetWidth
    btn.classList.add('ping')
  }
  if (!el || !orb || !btn || reducedMotion()) {
    ping()
    return Promise.resolve()
  }
  const r = orb.getBoundingClientRect()
  const to = btn.getBoundingClientRect()
  if (!to.width) return Promise.resolve()
  return el
    .animate(
      arcFrames(
        to.left + to.width / 2 - (r.left + r.width / 2),
        to.top + to.height / 2 - (r.top + r.height / 2),
        70,
        0.12,
        0,
      ),
      { duration: 700, delay: i * 90, easing: 'cubic-bezier(.45, .05, .6, .95)', fill: 'forwards' },
    )
    .finished.then(ping, ping)
}
