import { NavLink } from 'react-router-dom'
import './InterviewFlow.css'

export default function HomePage() {
  return (
    <section className="home-layout">
      <article className="hero-card">
        <p className="section-eyebrow">Interview Simulator</p>
        <h1>Run a full mock interview, not a loose chat thread.</h1>
        <p className="support-copy">
          Upload or paste your CV and target job description, pick the interview length, answer one
          question at a time, and finish with a scored performance report.
        </p>
        <div className="hero-actions">
          <NavLink to="/interviews/new" className="primary-button">
            Configure Interview
          </NavLink>
          <NavLink to="/interviews/history" className="secondary-button">
            View History
          </NavLink>
        </div>
      </article>

      <section className="info-grid">
        <article className="flow-card feature-card">
          <p className="section-eyebrow">1. Configure</p>
          <h2>Bring your own context</h2>
          <p>
            Paste text directly or upload `pdf` and `docx` files for MarkItDown parsing before the
            interview starts.
          </p>
        </article>

        <article className="flow-card feature-card">
          <p className="section-eyebrow">2. Practice</p>
          <h2>Answer one prompt at a time</h2>
          <p>
            The interview runner keeps focus narrow, tracks progress, and moves through behavioral
            and technical questions in a deliberate sequence.
          </p>
        </article>

        <article className="flow-card feature-card">
          <p className="section-eyebrow">3. Review</p>
          <h2>Revisit every session</h2>
          <p>
            Completed interviews are stored in the database, with scorecards, written feedback, and
            per-question commentary available from history.
          </p>
        </article>
      </section>
    </section>
  )
}
