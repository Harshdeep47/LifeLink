/**
 * Shared primitives: loading, empty and error states, cards, buttons, fields.
 *
 * Every async view in the app uses `AsyncState` so loading, empty and error are
 * handled consistently rather than each screen inventing its own. The error
 * state always offers a retry and shows the correlation id, which is what makes
 * a user's report traceable to a specific request in the logs.
 */
import { Component } from 'react'

import './ui.css'

export function Spinner({ label = 'Loading' }) {
  return (
    <span className="spinner" role="status" aria-live="polite">
      <span className="spinner__ring" aria-hidden="true" />
      <span className="visually-hidden">{label}</span>
    </span>
  )
}

export function LoadingPanel({ message = 'Loading…' }) {
  return (
    <div className="state-panel" role="status" aria-live="polite">
      <Spinner />
      <p className="state-panel__message">{message}</p>
    </div>
  )
}

export function EmptyPanel({ title, message, action }) {
  return (
    <div className="state-panel state-panel--empty">
      <span className="state-panel__glyph" aria-hidden="true">◌</span>
      <h3 className="state-panel__title">{title}</h3>
      {message && <p className="state-panel__message">{message}</p>}
      {action}
    </div>
  )
}

export function ErrorPanel({ error, onRetry, title = 'Something went wrong' }) {
  const message = error?.message ?? 'An unexpected error occurred.'
  const code = error?.code
  const correlationId = error?.correlationId

  return (
    <div className="state-panel state-panel--error" role="alert">
      <span className="state-panel__glyph" aria-hidden="true">!</span>
      <h3 className="state-panel__title">{title}</h3>
      <p className="state-panel__message">{message}</p>
      {code && <p className="state-panel__meta">Error code: <code>{code}</code></p>}
      {correlationId && (
        <p className="state-panel__meta">
          Reference: <code>{correlationId}</code>
        </p>
      )}
      {onRetry && (
        <button type="button" className="btn btn--secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

/**
 * One place that decides which of loading / error / empty / content to show.
 * Views pass the hook result straight in.
 */
export function AsyncState({
  loading,
  error,
  isEmpty,
  onRetry,
  loadingMessage,
  emptyTitle = 'Nothing to show',
  emptyMessage,
  emptyAction,
  children,
}) {
  if (loading) return <LoadingPanel message={loadingMessage} />
  if (error) return <ErrorPanel error={error} onRetry={onRetry} />
  if (isEmpty) {
    return <EmptyPanel title={emptyTitle} message={emptyMessage} action={emptyAction} />
  }
  return children
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  tone = 'default',
  as: As = 'section',
  className = '',
}) {
  return (
    // className is appended rather than replacing the base classes, so a
    // caller can mark a card (for example as the nearest result) without
    // losing the card styling.
    <As className={`card card--${tone}${className ? ` ${className}` : ''}`}>
      {(title || actions) && (
        <header className="card__header">
          <div>
            {title && <h3 className="card__title">{title}</h3>}
            {subtitle && <p className="card__subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="card__actions">{actions}</div>}
        </header>
      )}
      <div className="card__body">{children}</div>
    </As>
  )
}

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled = false,
  type = 'button',
  ...rest
}) {
  return (
    <button
      type={type}
      className={`btn btn--${variant} btn--${size}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <Spinner label="Working" />}
      <span>{children}</span>
    </button>
  )
}

/** A labelled field with help text and an accessible error association. */
export function Field({ label, htmlFor, hint, error, required, children }) {
  const hintId = hint ? `${htmlFor}-hint` : undefined
  const errorId = error ? `${htmlFor}-error` : undefined
  return (
    <div className={`field ${error ? 'field--invalid' : ''}`}>
      <label className="field__label" htmlFor={htmlFor}>
        {label}
        {required && <span className="field__required" aria-hidden="true"> *</span>}
        {required && <span className="visually-hidden"> (required)</span>}
      </label>
      {hint && <p className="field__hint" id={hintId}>{hint}</p>}
      {children({ id: htmlFor, describedBy: [hintId, errorId].filter(Boolean).join(' ') || undefined })}
      {error && <p className="field__error" id={errorId} role="alert">{error}</p>}
    </div>
  )
}

export function Notice({ children, tone = 'info', title }) {
  return (
    <div className={`notice notice--${tone}`} role={tone === 'warning' ? 'alert' : undefined}>
      {title && <strong className="notice__title">{title}</strong>}
      <div className="notice__body">{children}</div>
    </div>
  )
}

/**
 * Search results are a report, not a hold.
 *
 * This wording changed when temporary reservations were added. It used to say
 * LifeLink does not reserve blood at all, which was true then and is now
 * wrong: a user can hold units explicitly. What remains true, and is the point
 * of this notice, is that *browsing* holds nothing — a figure on a results
 * page is a report from the facility until someone reserves against it.
 *
 * Centralised so the wording cannot drift between pages.
 */
export function NotAReservationNotice() {
  return (
    <p className="inline-note">
      Figures here are reported by each facility and are{' '}
      <strong>not held for you</strong> until you request a reservation. Stock
      can change or be used by someone else at any time, and nothing shown has
      been clinically approved for a particular patient.
    </p>
  )
}

export function DefinitionList({ items }) {
  return (
    <dl className="definition-list">
      {items
        .filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
        .map((item) => (
          <div className="definition-list__row" key={item.label}>
            <dt>{item.label}</dt>
            <dd>{item.value}</dd>
          </div>
        ))}
    </dl>
  )
}

/**
 * Error boundary so one failing panel cannot blank the whole application.
 * React requires a class component for this.
 */
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // Surfaced in the browser console; a production build would forward this
    // to CloudWatch via a logging endpoint.
    console.error('LifeLink UI error', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <ErrorPanel
          title="This section could not be displayed"
          error={{ message: this.state.error.message, code: 'UI_ERROR' }}
          onRetry={() => this.setState({ error: null })}
        />
      )
    }
    return this.props.children
  }
}
