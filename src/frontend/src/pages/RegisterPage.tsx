import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import './InterviewFlow.css'

export default function RegisterPage() {
  const navigate = useNavigate()
  const { register } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setError(null)
    setIsSubmitting(true)

    try {
      await register(email, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to register')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className="auth-layout">
      <article className="flow-card auth-card">
        <p className="section-eyebrow">Create Account</p>
        <h1>Register and keep your interview history private</h1>
        <p className="support-copy">
          Each account has its own interview sessions, summaries, and progress history.
        </p>

        <form className="answer-form" onSubmit={submit}>
          <label htmlFor="register-email" className="field-label">
            Email
          </label>
          <input
            id="register-email"
            className="text-input"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />

          <label htmlFor="register-password" className="field-label">
            Password
          </label>
          <input
            id="register-password"
            className="text-input"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={8}
            required
          />

          <label htmlFor="register-confirm-password" className="field-label">
            Confirm password
          </label>
          <input
            id="register-confirm-password"
            className="text-input"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            minLength={8}
            required
          />

          {error && (
            <p className="status-banner error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="primary-button" disabled={isSubmitting}>
            {isSubmitting ? 'Creating account...' : 'Register'}
          </button>
        </form>

        <p className="auth-switch">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </article>
    </section>
  )
}
