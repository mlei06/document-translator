// Password accounts and optional access-key sign-in both create an HttpOnly session.
// Lenny keeps the mock's reactions: eyes follow the typing, and he looks away from the key.
import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, NetworkError, unwrap, type Session } from '../api/client'
import { Lenny } from '../lenny/Lenny'
import { Speech, type Line } from '../lenny/Speech'
import { boop, burst, cheer, track, wait } from '../lib/motion'
import { Icon } from '../ui/icons'
import { ThemeButton } from './Header'

const TICKLES: [string, string][] = [
  ['Hehe, that tickles!', "Sign in and I'll show you what else I can do."],
  ['Boop!', "I'm ready when you are."],
  ['Hi hi!', 'Your sign-in details go on the left.'],
]
const IDLE: Line = {
  say: "Hi, I'm Lenny!",
  sub: 'Sign in so I can start translating your documents.',
}

export interface SignInHandle {
  lenny: () => SVGSVGElement | null
  reset: (line?: Line) => void
}

export const SignIn = forwardRef<
  SignInHandle,
  { hidden: boolean; message: Line | null; onSignedIn: (session: Session) => void }
>(function SignIn({ hidden, message, onSignedIn }, ref) {
  const [key, setKey] = useState('')
  const [authMode, setAuthMode] = useState<'signin' | 'signup' | 'key'>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [line, setLine] = useState<Line>(message ?? IDLE)
  const [busy, setBusy] = useState(false)
  const [shy, setShy] = useState(false)
  const lenny = useRef<SVGSVGElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const signLenny = useRef<HTMLDivElement>(null)
  const [shown, setShown] = useState(message)
  if (message !== shown) {
    setShown(message)
    if (message) setLine(message)
  }

  useImperativeHandle(ref, () => ({
    lenny: () => lenny.current,
    reset: (l) => {
      setKey('')
      setPassword('')
      setEmail('')
      setDisplayName('')
      setAuthMode('signin')
      setError(null)
      setShy(false)
      setLine(l ?? IDLE)
    },
  }))

  useEffect(() => {
    lenny.current?.classList.toggle('shy', shy)
  }, [shy])

  useEffect(() => {
    document
      .querySelectorAll<HTMLElement>('.signpanel .sc-brand, .sc-form > *')
      .forEach((el, i) => {
        el.style.setProperty('--d', String(i))
      })
    const t = setTimeout(() => document.body.classList.add('settled'), 1800)
    return () => clearTimeout(t)
  }, [])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const value = key.trim()
    if (authMode === 'key' && !value) {
      setLine({
        say: 'I need your access key first.',
        sub: 'Your IT admin gives you one. It starts with dt_.',
      })
      input.current?.focus()
      return
    }
    setError(null)
    setBusy(true)
    try {
      const session =
        authMode === 'signup'
          ? await unwrap(
              api.POST('/v1/accounts', {
                body: {
                  email: email.trim(),
                  password,
                  display_name: displayName.trim() || undefined,
                },
              }),
            )
          : await unwrap(
              api.POST('/v1/sessions', {
                body: authMode === 'key' ? { key: value } : { email: email.trim(), password },
              }),
            )
      setKey('')
      setPassword('')
      input.current?.blur()
      setShy(false)
      const r = signLenny.current?.getBoundingClientRect()
      if (r) burst(r.left + r.width / 2, r.top + r.height * 0.35, 14)
      cheer(lenny.current)
      setLine({ say: `Welcome, ${session.user.display_name}!` })
      await wait(700)
      onSignedIn(session)
    } catch (err) {
      setShy(false)
      setError(
        err instanceof ApiError && err.status === 404 && authMode === 'signup'
          ? 'Account registration is disabled. Ask your administrator for access.'
          : err instanceof ApiError && err.status === 401
            ? authMode === 'key'
              ? 'That access key did not work.'
              : 'Email or password is incorrect.'
            : err instanceof ApiError
              ? err.message
              : 'The service could not be reached. Please try again.',
      )
      if (err instanceof ApiError && err.status === 401)
        setLine({
          say: "Those details didn't work.",
          sub:
            authMode === 'key'
              ? 'Check your access key or ask your IT admin for a new one.'
              : 'Check your email and password, then try again.',
        })
      else if (err instanceof ApiError && err.status === 429)
        setLine({ say: 'Too many tries!', sub: 'Wait a few minutes, then try again.' })
      else if (err instanceof NetworkError)
        setLine({
          say: "I can't reach the translation service.",
          sub: 'Check your connection and try again.',
        })
      else
        setLine({
          say: 'Something went wrong signing in.',
          sub: err instanceof ApiError ? err.message : 'Try again in a moment.',
        })
      input.current?.focus()
    } finally {
      setBusy(false)
    }
  }

  return (
    <section id="signin" hidden={hidden}>
      <div className="signpanel">
        <div className="sc-top">
          <span className="sc-brand">
            <span className="sc-logo">
              <Icon name="brand" />
            </span>
            Lenny
          </span>
          <ThemeButton
            onToggled={(night) => {
              boop(lenny.current)
              setLine({
                say: night ? 'Ooh, fireflies!' : 'Good morning!',
                sub: 'Sign in so I can start translating your documents.',
              })
            }}
          />
        </div>
        <div className="sc-center">
          <form id="signForm" className="sc-form" onSubmit={(e) => void submit(e)}>
            <div className="sc-head">
              <h1>{authMode === 'signup' ? 'Create your account' : 'Sign in to Lenny'}</h1>
              <p>
                {authMode === 'key'
                  ? 'Use your provisioned access key.'
                  : 'Your documents, translated and ready when you need them.'}
              </p>
            </div>
            {authMode !== 'key' ? (
              <>
                {authMode === 'signup' ? (
                  <div className="sc-field">
                    <label htmlFor="display-name">
                      Name <span className="sc-desc">(optional)</span>
                    </label>
                    <input
                      id="display-name"
                      name="name"
                      autoComplete="name"
                      maxLength={100}
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      disabled={busy}
                    />
                  </div>
                ) : null}
                <div className="sc-field">
                  <label htmlFor="email">Email</label>
                  <input
                    id="email"
                    ref={input}
                    name="email"
                    type="email"
                    autoComplete="username"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={busy}
                  />
                </div>
                <div className="sc-field">
                  <label htmlFor="password">Password</label>
                  <input
                    id="password"
                    name="password"
                    type="password"
                    autoComplete={authMode === 'signup' ? 'new-password' : 'current-password'}
                    required
                    minLength={authMode === 'signup' ? 8 : undefined}
                    maxLength={128}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onFocus={() => setShy(true)}
                    onBlur={() => setShy(false)}
                    disabled={busy}
                    aria-describedby={authMode === 'signup' ? 'password-help' : undefined}
                  />
                  {authMode === 'signup' ? (
                    <p id="password-help" className="sc-desc">
                      Use at least 8 characters. A memorable passphrase works well.
                    </p>
                  ) : null}
                </div>
              </>
            ) : (
              <div className="sc-field">
                <div className="sc-row">
                  <label htmlFor="key">Access key</label>
                  <a
                    href="#"
                    onClick={(e) => {
                      e.preventDefault()
                      setLine({
                        say: 'No worries!',
                        sub: "Ask your IT admin for a new key. There's no password to reset.",
                      })
                    }}
                  >
                    Lost your key?
                  </a>
                </div>
                <input
                  id="key"
                  ref={input}
                  name="key"
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="dt_..."
                  value={key}
                  disabled={busy}
                  onChange={(e) => setKey(e.target.value)}
                  onFocus={() => {
                    setShy(true)
                    setLine({ say: 'Paste your access key', sub: "Don't worry, I won't peek." })
                  }}
                  onBlur={() =>
                    setTimeout(() => {
                      if (document.activeElement?.id === 'key') return
                      setShy(false)
                      setLine(IDLE)
                    }, 0)
                  }
                />
              </div>
            )}
            {error ? (
              <p className="auth-error" role="alert">
                {error}
              </p>
            ) : null}
            <button className="sc-btn" type="submit" disabled={busy}>
              {busy
                ? authMode === 'signup'
                  ? 'Creating account...'
                  : 'Signing in...'
                : authMode === 'signup'
                  ? 'Create account'
                  : 'Sign in'}
            </button>
            <div className="sc-field">
              <p className="sc-desc">
                {authMode === 'signup' ? 'Already have an account? ' : 'New to Lenny? '}
                <button
                  className="auth-link"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setAuthMode(authMode === 'signup' ? 'signin' : 'signup')
                    setError(null)
                    setPassword('')
                    setKey('')
                  }}
                >
                  {authMode === 'signup' ? 'Sign in instead' : 'Create an account'}
                </button>
              </p>
              <button
                className="auth-link"
                type="button"
                disabled={busy}
                onClick={() => {
                  setAuthMode(authMode === 'key' ? 'signin' : 'key')
                  setError(null)
                  setPassword('')
                  setKey('')
                }}
              >
                {authMode === 'key' ? 'Use email and password' : 'Use an access key'}
              </button>
            </div>
          </form>
        </div>
      </div>
      <div className="sign-card">
        <div className="lenny-wrap">
          <Speech id="signSpeech" line={line} who={lenny} />
          <div
            id="signLenny"
            ref={signLenny}
            onClick={() => {
              boop(lenny.current)
              const [a, b] = TICKLES[Math.floor(Math.random() * TICKLES.length)]!
              setLine({ say: a, sub: b })
            }}
            onPointerMove={(e) => track(e.clientX, e.clientY)}
          >
            <Lenny ref={lenny} size="big" />
          </div>
        </div>
        <figure className="sign-caption">
          <p>
            Drop in a PowerPoint, Word, Excel, PDF or text file. Lenny translates it and keeps the
            layout intact.
          </p>
          <span>Lenny, the document translator for your team</span>
        </figure>
      </div>
    </section>
  )
})
