// Session bootstrap and the sign-in <-> meadow transition. Lenny is one character across both
// screens: the visible instance flies to where the other one sits.
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  api,
  stopSessionWork,
  onSessionExpired,
  setCsrf,
  unwrap,
  type Me,
  type Session,
} from './api/client'
import type { Line } from './lenny/Speech'
import { dur, reducedMotion, wait } from './lib/motion'
import { Home } from './screens/Home'
import { SignIn, type SignInHandle } from './screens/SignIn'
import { World } from './world/World'

type Screen =
  | { name: 'checking' }
  | { name: 'signin'; message: Line | null }
  | { name: 'entering'; me: Me }
  | { name: 'app'; me: Me }
  | { name: 'leaving'; me: Me; message: Line | null }

function flyLenny(from: Element | null, to: Element | null): void {
  if (!from || !to) return
  const a = from.getBoundingClientRect()
  const b = to.getBoundingClientRect()
  ;(from as HTMLElement).style.visibility = 'hidden'
  ;(to as HTMLElement).style.visibility = ''
  if (!a.width || !b.width || reducedMotion()) return
  ;(to as HTMLElement).style.transformOrigin = '0 0'
  to.animate(
    [
      {
        transform: `translate(${a.left - b.left}px, ${a.top - b.top}px) scale(${a.width / b.width})`,
      },
      { transform: 'none' },
    ],
    { duration: dur(1000), easing: 'cubic-bezier(.7, 0, .2, 1)' },
  )
}

export function App() {
  const qc = useQueryClient()
  const [screen, setScreen] = useState<Screen>({ name: 'checking' })
  const signIn = useRef<SignInHandle>(null)

  // A reloaded page keeps its session (the cookie) and recovers the CSRF token.
  useEffect(() => {
    unwrap(api.GET('/v1/sessions/current')).then(
      (s) => {
        setCsrf(s.csrf_token)
        setScreen({ name: 'app', me: s.user })
      },
      () => setScreen({ name: 'signin', message: null }),
    )
  }, [])

  const leave = useCallback(
    (message: Line | null) => {
      stopSessionWork()
      setCsrf(null)
      stopSessionWork()
      qc.clear()
      setScreen((s) =>
        s.name === 'app' || s.name === 'entering'
          ? { name: 'leaving', me: s.me, message }
          : { name: 'signin', message },
      )
    },
    [qc],
  )

  // Session ended elsewhere (expiry, revoked key, disabled user): back to sign-in, data cleared.
  useEffect(
    () =>
      onSessionExpired(() =>
        leave({
          say: 'Your session ended.',
          sub: 'Sign in to keep going. Translations already started keep running.',
        }),
      ),
    [leave],
  )

  const signedIn = (session: Session) => {
    setCsrf(session.csrf_token)
    qc.clear()
    setScreen({ name: 'entering', me: session.user })
  }

  const signOut = async () => {
    stopSessionWork()
    try {
      await unwrap(api.DELETE('/v1/sessions/current'))
    } catch {
      // the cookie may already be gone; signing out locally is still right
    }
    leave(null)
  }

  const mode = screen.name === 'app' || screen.name === 'entering' ? 'mode-app' : 'mode-signin'
  useLayoutEffect(() => {
    document.body.classList.remove('mode-app', 'mode-signin')
    document.body.classList.add(mode)
  }, [mode])

  useLayoutEffect(() => {
    if (screen.name === 'entering') {
      flyLenny(signIn.current?.lenny() ?? null, document.querySelector('#lennyBtn .lenny'))
      let live = true
      void wait(1000).then(() => {
        if (live) setScreen((s) => (s.name === 'entering' ? { name: 'app', me: s.me } : s))
      })
      return () => {
        live = false
      }
    }
    if (screen.name === 'leaving') {
      signIn.current?.reset(screen.message ?? undefined)
      flyLenny(document.querySelector('#lennyBtn .lenny'), signIn.current?.lenny() ?? null)
      let live = true
      void wait(1000).then(() => {
        if (!live) return
        setScreen({ name: 'signin', message: screen.message })
        document.querySelector<HTMLInputElement>('#signin input:not([disabled])')?.focus()
      })
      return () => {
        live = false
      }
    }
    if (screen.name === 'signin' || screen.name === 'app') {
      const l = signIn.current?.lenny()
      if (l) l.style.visibility = ''
    }
    return undefined
  }, [screen])

  const me =
    screen.name === 'entering' || screen.name === 'app' || screen.name === 'leaving'
      ? screen.me
      : null

  return (
    <>
      <World />
      <SignIn
        ref={signIn}
        hidden={screen.name === 'app' || screen.name === 'checking'}
        message={screen.name === 'signin' ? screen.message : null}
        onSignedIn={signedIn}
      />
      {me ? (
        <Home
          key={me.id}
          me={me}
          arriving={screen.name === 'entering'}
          onSignOut={() => void signOut()}
        />
      ) : null}
    </>
  )
}
