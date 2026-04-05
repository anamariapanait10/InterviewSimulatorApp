import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import './InterviewFlow.css'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const redirectTo = (location.state as { from?: string } | null)?.from ?? '/'

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      await login(email, password)
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className="auth-layout">
      <article className="flow-card auth-card">
        <p className="section-eyebrow">Account Access</p>
        <h1>Log in to your interview workspace</h1>
        <p className="support-copy">
          Your interview sessions are now linked to your account, so only you can view and manage them.
        </p>

        <form className="answer-form" onSubmit={submit}>
          <label htmlFor="login-email" className="field-label">
            Email
          </label>
          <input
            id="login-email"
            className="text-input"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />

          <label htmlFor="login-password" className="field-label">
            Password
          </label>
          <input
            id="login-password"
            className="text-input"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={8}
            required
          />

          {error && (
            <p className="status-banner error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="primary-button" disabled={isSubmitting}>
            {isSubmitting ? 'Signing in...' : 'Log In'}
          </button>
        </form>

        <p className="auth-switch">
          Need an account? <Link to="/register">Register</Link>
        </p>
      </article>
    </section>
  )
}
