// The meadow: painted day/night stills, clouds drifting in code, pollen by day and fireflies at
// night. The background stays anchored as the cursor moves; only Lenny follows the pointer.
import { useEffect, useRef } from 'react'
import { reducedMotion } from '../lib/motion'

const IMG_W = 2912
const IMG_H = 1632
const OBJ_Y = 0.62
const BLEED = 24

interface Cloud {
  src: string
  w: number
  y: number
  v: number
  o: number
  x: number
  day?: boolean
}

// Clouds stay in the upper sky and fade out above the hills, so they never pass behind the land.
const CLOUDS: Cloud[] = [
  { src: 'cloud-cumulus-2', w: 0.23, y: 0.35, v: 12, o: 0.95, x: 0.06 },
  { src: 'cloud-cumulus-1', w: 0.21, y: 0.04, v: 9, o: 0.92, x: 0.55 },
  { src: 'cloud-puffy-small-1', w: 0.11, y: 0.55, v: 16, o: 0.9, x: 0.82, day: true },
  { src: 'cloud-wispy-2', w: 0.18, y: 0, v: 20, o: 0.8, x: 0.3, day: true },
  { src: 'cloud-soft-distant-1', w: 0.16, y: 0.7, v: 6, o: 0.65, x: 0.68 },
]

interface Mote {
  x: number
  y: number
  r: number
  vx: number
  vy: number
  ph: number
  sp: number
  low: number
}

export function World() {
  const cloudsRef = useRef<HTMLDivElement>(null)
  const motesRef = useRef<HTMLCanvasElement>(null)

  // Clouds
  useEffect(() => {
    const wc = cloudsRef.current
    if (!wc) return
    const clouds = CLOUDS.map((c) => {
      const img = new Image()
      img.src = `/art/${c.src}.webp`
      img.alt = ''
      img.decoding = 'async'
      if (c.day) img.className = 'day-only'
      img.style.setProperty('--o', String(c.o))
      wc.append(img)
      return { ...c, el: img, xp: c.x * innerWidth, px: 90 }
    })
    let band = { top: 0, bottom: 300 }
    const layout = () => {
      // Mirror object-fit: cover + object-position so cloud limits follow the painted horizon.
      const W = innerWidth + BLEED * 2
      const H = innerHeight + BLEED * 2
      const dh = IMG_H * Math.max(W / IMG_W, H / IMG_H)
      const top = -BLEED + (H - dh) * OBJ_Y
      const clip = top + dh * 0.36
      wc.style.setProperty('--fade-start', `${Math.max(0, clip - dh * 0.1)}px`)
      wc.style.setProperty('--fade-end', `${Math.max(40, clip)}px`)
      band = { top: Math.max(8, top + dh * 0.02), bottom: clip - dh * 0.05 }
      clouds.forEach((c) => {
        c.px = Math.max(90, c.w * innerWidth)
        c.el.style.width = `${c.px}px`
      })
    }
    let last = performance.now()
    let raf = 0
    const drift = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now
      const k = Math.max(0.5, innerWidth / 1440)
      clouds.forEach((c) => {
        if (!reducedMotion()) c.xp += c.v * k * dt
        if (c.xp > innerWidth + 40) c.xp = -c.px - 40
        const ratio = c.el.naturalWidth ? c.el.naturalHeight / c.el.naturalWidth : 0.6
        const y = band.top + c.y * Math.max(0, band.bottom - band.top - c.px * ratio)
        c.el.style.transform = `translate3d(${c.xp.toFixed(1)}px, ${y.toFixed(1)}px, 0)`
      })
      raf = requestAnimationFrame(drift)
    }
    layout()
    addEventListener('resize', layout)
    raf = requestAnimationFrame(drift)
    return () => {
      cancelAnimationFrame(raf)
      removeEventListener('resize', layout)
      clouds.forEach((c) => c.el.remove())
    }
  }, [])

  // Pollen by day, fireflies at night
  useEffect(() => {
    const canvas = motesRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    let MW = 0
    let MH = 0
    let DPR = 1
    let night = 0
    const newMote = (anywhere: boolean): Mote => ({
      x: Math.random() * MW,
      y: anywhere ? Math.random() * MH : MH + 10,
      r: 0.8 + Math.random() * 2.2,
      vx: 4 + Math.random() * 10,
      vy: -(3 + Math.random() * 8),
      ph: Math.random() * 6.283,
      sp: 0.6 + Math.random() * 1.2,
      low: 0.56 + Math.random() * 0.4,
    })
    const size = () => {
      DPR = Math.min(2, devicePixelRatio || 1)
      MW = canvas.clientWidth
      MH = canvas.clientHeight
      canvas.width = MW * DPR
      canvas.height = MH * DPR
    }
    size()
    const parts = Array.from({ length: 46 }, () => newMote(true))
    const readNight = () => {
      night =
        parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--night')) || 0
    }
    readNight()
    const nightTimer = setInterval(readNight, 1000)
    addEventListener('resize', size)
    let t0 = performance.now()
    let raf = 0
    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - t0) / 1000)
      t0 = now
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0)
      ctx.clearRect(0, 0, MW, MH)
      const dark = night > 0.5
      parts.forEach((p, i) => {
        p.ph += dt * p.sp
        if (dark) {
          if (i >= 30) return
          p.x += p.vx * 0.12 * dt
          if (p.x > MW + 40) p.x = -40
          const x = p.x + Math.sin(p.ph * 0.6) * 30
          const y = MH * p.low + Math.sin(p.ph * 0.9) * 18
          const a = Math.max(0, Math.sin(p.ph * 1.4)) ** 2
          const R = p.r * 7
          const g = ctx.createRadialGradient(x, y, 0, x, y, R)
          g.addColorStop(0, `rgba(240, 255, 170, ${(0.95 * a).toFixed(3)})`)
          g.addColorStop(0.22, `rgba(215, 250, 120, ${(0.45 * a).toFixed(3)})`)
          g.addColorStop(1, 'rgba(200, 240, 100, 0)')
          ctx.fillStyle = g
          ctx.beginPath()
          ctx.arc(x, y, R, 0, 6.283)
          ctx.fill()
        } else {
          p.x += (p.vx + Math.sin(p.ph) * 6) * dt
          p.y += (p.vy + Math.cos(p.ph * 0.8) * 4) * dt
          if (p.x > MW + 10 || p.y < -10) Object.assign(p, newMote(false))
          const a = 0.3 + 0.35 * Math.sin(p.ph * 1.7)
          const R = p.r * 2.2
          const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, R)
          g.addColorStop(0, `rgba(255, 252, 236, ${Math.max(0, a).toFixed(3)})`)
          g.addColorStop(1, 'rgba(255, 252, 236, 0)')
          ctx.fillStyle = g
          ctx.beginPath()
          ctx.arc(p.x, p.y, R, 0, 6.283)
          ctx.fill()
        }
      })
      if (!reducedMotion()) raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(raf)
      clearInterval(nightTimer)
      removeEventListener('resize', size)
    }
  }, [])

  return (
    <>
      <div id="world" aria-hidden="true">
        <div className="w-ground">
          <div className="w-scene">
            <img src="/art/meadow-day.webp" alt="" />
          </div>
          <div className="w-scene w-night">
            <img src="/art/meadow-night.webp" alt="" />
          </div>
        </div>
        <canvas id="motes" ref={motesRef} />
        <div className="w-clouds" id="wClouds" ref={cloudsRef} />
        <div className="w-light" />
      </div>
      <div id="spot" aria-hidden="true" />
    </>
  )
}
