import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth'
import './InterviewFlow.css'

export default function HomePage() {
  const { isAuthenticated } = useAuth()

  return (
    <section className="home-layout">
      <article className="hero-card">
        <p className="section-eyebrow">Interview Simulator</p>
        <h1>Run full mock interviews and get instant detailed feedback.</h1>
        <p className="support-copy">
          Upload or paste your CV and target job description, pick the interview length, answer one
          question at a time, and finish with a scored performance report!
        </p>
        <div className="hero-actions">
          {isAuthenticated ? (
            <>
              <NavLink to="/interviews/new" className="primary-button">
                Configure Interview
              </NavLink>
              <NavLink to="/interviews/history" className="secondary-button">
                View History
              </NavLink>
            </>
          ) : (
            <>
              <NavLink to="/register" className="primary-button">
                Create Account
              </NavLink>
              <NavLink to="/login" className="secondary-button">
                Log In
              </NavLink>
            </>
          )}
        </div>
      </article>

      <section className="info-grid">
        <article className="flow-card feature-card">
          <p className="section-eyebrow">1. Configure</p>
          <h2>Bring your own context</h2>
          <p className="mt-2">
            Paste your CV and job description direcly as text or upload them as pdf or docx files.
          </p>
        </article>

        <article className="flow-card feature-card">
          <p className="section-eyebrow">2. Practice</p>
          <h2>Simulate real interviews</h2>
          <p className="mt-2">
            Answer one question at a time in a guided, realistic flow. The AI adapts dynamically,
            challenging you with behavioral and technical prompts based on your responses.
          </p>
        </article>

        <article className="flow-card feature-card">
          <p className="section-eyebrow">3. Review</p>
          <h2>Get actionable feedback</h2>
          <p className="mt-2">
            Review detailed scorecards, strengths, and improvement areas after each session.
            Revisit past interviews to track progress and refine your answers over time.
          </p>
        </article>
      </section>
    </section>
  )
}
