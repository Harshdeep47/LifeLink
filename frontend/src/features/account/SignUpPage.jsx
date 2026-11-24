/**
 * Registration.
 *
 * Three steps, kept as three screens rather than one long form: details, the
 * emailed code, then done. A single form that silently becomes a
 * code-entry form is where people lose track of what is being asked.
 *
 * Account type is collected here but **grants nothing**. Choosing "Blood bank"
 * creates an ordinary donor account and records a request that an
 * administrator must verify. That is stated on the form, not buried: an
 * applicant who thinks they have institutional access and does not is worse
 * off than one who knows they are waiting.
 *
 * Sign-in stays with the hosted UI and PKCE (auth/cognito.js). Only
 * registration, confirmation and password recovery are done directly, because
 * those are unauthenticated operations that need no request signing.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { PASSWORD_REQUIREMENTS, passwordProblem } from '../../auth/passwordPolicy.js'

import { useAuth } from '../../auth/AuthContext.jsx'
import { beginSignIn } from '../../auth/cognito.js'
import {
  confirmSignUp,
  isSignUpConfigured,
  resendConfirmationCode,
  signUp,
} from '../../auth/cognitoSignUp.js'
import { Button, Card, Field, Notice } from '../../components/ui.jsx'

const ACCOUNT_TYPES = [
  {
    value: 'DONOR',
    label: 'Individual / Donor',
    detail: 'Find blood, reserve units, register for donation camps.',
  },
  {
    value: 'BLOOD_BANK',
    label: 'Blood bank',
    detail: 'Manage inventory and reservation requests for a facility.',
  },
  {
    value: 'HOSPITAL',
    label: 'Hospital',
    detail: 'Raise emergency requests and certify clinical priority.',
  },
  {
    value: 'CAMP_ORGANIZER',
    label: 'Donation camp organizer',
    detail: 'Create and run donation camps.',
  },
]

const INSTITUTIONAL = new Set(['BLOOD_BANK', 'HOSPITAL', 'CAMP_ORGANIZER'])

export function SignUpPage() {
  const { isAuthenticated } = useAuth()
  const [step, setStep] = useState('details') // details | confirm | done
  const [form, setForm] = useState({
    fullName: '',
    email: '',
    password: '',
    confirmPassword: '',
    accountType: 'DONOR',
    organizationName: '',
    acceptedTerms: false,
  })
  const [code, setCode] = useState('')
  const [destination, setDestination] = useState('')
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)
  const [busy, setBusy] = useState(false)

  const update = (key, value) => setForm((prev) => ({ ...prev, [key]: value }))
  const institutional = INSTITUTIONAL.has(form.accountType)

  if (isAuthenticated) {
    return (
      <div className="stack stack--narrow">
        <Card title="You are already signed in">
          <p className="text-sm">
            <Link to="/profile">Go to your profile</Link> or{' '}
            <Link to="/find">find blood</Link>.
          </p>
        </Card>
      </div>
    )
  }

  if (!isSignUpConfigured()) {
    return (
      <div className="stack stack--narrow">
        <header className="page-header"><h1>Create an account</h1></header>
        <Card>
          <Notice tone="warning" title="Registration is not available">
            <p className="text-sm" style={{ margin: 0 }}>
              This build has no identity provider configured. Public pages —
              blood availability, facilities and donation camps — work without
              an account.
            </p>
          </Notice>
        </Card>
      </div>
    )
  }

  const submitDetails = async (event) => {
    event.preventDefault()
    setError(null)

    if (!form.fullName.trim()) return setError('Enter your full name.')
    if (!form.email.trim()) return setError('Enter your email address.')
    const problem = passwordProblem(form.password)
    if (problem) return setError(problem)
    if (form.password !== form.confirmPassword) {
      return setError('The two passwords do not match.')
    }
    if (!form.acceptedTerms) {
      return setError('Please accept the terms and privacy notice to continue.')
    }
    if (institutional && !form.organizationName.trim()) {
      return setError('Enter the name of your organization.')
    }

    setBusy(true)
    try {
      const result = await signUp({
        email: form.email.trim(),
        password: form.password,
        fullName: form.fullName.trim(),
      })
      setDestination(result.destination)
      // Remembered so the request can be submitted after the first sign-in,
      // when there is a profile to attach it to.
      if (institutional) {
        try {
          window.sessionStorage.setItem(
            'lifelink.pendingOrgRequest',
            JSON.stringify({
              requestedType: form.accountType,
              organizationName: form.organizationName.trim(),
            }),
          )
        } catch { /* storage unavailable; the user can request from Profile */ }
      }
      setStep(result.userConfirmed ? 'done' : 'confirm')
    } catch (cause) {
      setError(cause?.message ?? 'Registration failed.')
    } finally {
      setBusy(false)
    }
  }

  const submitCode = async (event) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await confirmSignUp({ email: form.email.trim(), code: code.trim() })
      setStep('done')
    } catch (cause) {
      setError(cause?.message ?? 'Confirmation failed.')
    } finally {
      setBusy(false)
    }
  }

  const resend = async () => {
    setError(null)
    setInfo(null)
    try {
      const to = await resendConfirmationCode({ email: form.email.trim() })
      setInfo(`A new code has been sent to ${to}.`)
    } catch (cause) {
      setError(cause?.message ?? 'Could not send another code.')
    }
  }

  return (
    <div className="stack stack--narrow">
      <header className="page-header">
        <h1>Create an account</h1>
        <p className="page-header__lead">
          You do not need an account to search for blood or browse donation
          camps. An account lets you reserve units, register for camps and keep
          a donation history.
        </p>
      </header>

      <nav className="auth-tabs" aria-label="Account">
        <Link to="/sign-in" className="auth-tabs__tab">Sign in</Link>
        <span className="auth-tabs__tab auth-tabs__tab--active" aria-current="page">
          Create account
        </span>
      </nav>

      {step === 'details' && (
        <Card title="Your details">
          <form onSubmit={submitDetails}>
            <Field label="Full name" htmlFor="full-name">
              {({ id }) => (
                <input
                  id={id}
                  value={form.fullName}
                  onChange={(e) => update('fullName', e.target.value)}
                  autoComplete="name"
                  required
                />
              )}
            </Field>

            <Field label="Email address" htmlFor="email" hint="Your confirmation code is sent here.">
              {({ id }) => (
                <input
                  id={id}
                  type="email"
                  value={form.email}
                  onChange={(e) => update('email', e.target.value)}
                  autoComplete="email"
                  required
                />
              )}
            </Field>

            <Field
              label="Password"
              htmlFor="password"
              hint={PASSWORD_REQUIREMENTS}
            >
              {({ id }) => (
                <input
                  id={id}
                  type="password"
                  value={form.password}
                  onChange={(e) => update('password', e.target.value)}
                  autoComplete="new-password"
                  required
                />
              )}
            </Field>

            <Field label="Confirm password" htmlFor="confirm-password">
              {({ id }) => (
                <input
                  id={id}
                  type="password"
                  value={form.confirmPassword}
                  onChange={(e) => update('confirmPassword', e.target.value)}
                  autoComplete="new-password"
                  required
                />
              )}
            </Field>

            <Field label="Account type" htmlFor="account-type">
              {({ id }) => (
                <select
                  id={id}
                  value={form.accountType}
                  onChange={(e) => update('accountType', e.target.value)}
                >
                  {ACCOUNT_TYPES.map((type) => (
                    <option key={type.value} value={type.value}>{type.label}</option>
                  ))}
                </select>
              )}
            </Field>
            <p className="inline-note">
              {ACCOUNT_TYPES.find((t) => t.value === form.accountType)?.detail}
            </p>

            {institutional && (
              <>
                <Field label="Organization name" htmlFor="org-name">
                  {({ id }) => (
                    <input
                      id={id}
                      value={form.organizationName}
                      onChange={(e) => update('organizationName', e.target.value)}
                      required
                    />
                  )}
                </Field>
                <Notice tone="info" title="Institutional access is verified first">
                  <p className="text-sm" style={{ margin: 0 }}>
                    Your account will be created as an individual account and
                    your request for{' '}
                    <strong>
                      {ACCOUNT_TYPES.find((t) => t.value === form.accountType)?.label}
                    </strong>{' '}
                    access will be recorded as <strong>pending</strong>. An
                    administrator verifies the organization before any
                    institutional access is granted, so you will not be able to
                    see or change another organization&apos;s data in the meantime.
                  </p>
                </Notice>
              </>
            )}

            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.acceptedTerms}
                onChange={(e) => update('acceptedTerms', e.target.checked)}
              />
              <span className="text-sm">
                I accept the <Link to="/terms">terms</Link> and{' '}
                <Link to="/privacy">privacy notice</Link>.
              </span>
            </label>

            {error && <p className="field__error" role="alert">{error}</p>}

            <Button type="submit" disabled={busy}>
              {busy ? 'Creating account…' : 'Create account'}
            </Button>
          </form>
        </Card>
      )}

      {step === 'confirm' && (
        <Card title="Confirm your email">
          <p className="text-sm">
            We sent a six-digit code to <strong>{destination}</strong>. Enter it
            below to finish creating your account.
          </p>
          <form onSubmit={submitCode}>
            <Field label="Confirmation code" htmlFor="code">
              {({ id }) => (
                <input
                  id={id}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required
                />
              )}
            </Field>
            {error && <p className="field__error" role="alert">{error}</p>}
            {info && <p className="text-xs muted">{info}</p>}
            <div className="row">
              <Button type="submit" disabled={busy || !code.trim()}>
                {busy ? 'Confirming…' : 'Confirm'}
              </Button>
              <Button type="button" variant="secondary" onClick={resend}>
                Send a new code
              </Button>
            </div>
          </form>
        </Card>
      )}

      {step === 'done' && (
        <Card title="Account created">
          <Notice tone="success" title="You can sign in now">
            <p className="text-sm" style={{ margin: 0 }}>
              Your account is confirmed. Sign in to finish setting up your
              profile
              {institutional ? ' and submit your organization access request' : ''}.
            </p>
          </Notice>
          <Button type="button" onClick={() => beginSignIn({ returnTo: '/profile' })}>
            Continue to sign in
          </Button>
        </Card>
      )}
    </div>
  )
}
