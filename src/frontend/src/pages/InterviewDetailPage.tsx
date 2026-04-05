import { useEffect, useState } from 'react'
import { NavLink, useParams } from 'react-router-dom'
import { getInterview } from '../api'
import InterviewSummaryPanel from '../components/InterviewSummaryPanel'
import type { InterviewSession } from '../types'
import './InterviewFlow.css'

export default function InterviewDetailPage() {
  const { sessionId = '' } = useParams()
  const [session, setSession] = useState<InterviewSession | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const nextSession = await getInterview(sessionId)
        if (!cancelled) {
          setSession(nextSession)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load interview details')
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  if (error) {
    return (
      <section className="flow-card">
        <p className="section-eyebrow">Interview Details</p>
        <h1>Details unavailable</h1>
        <p className="support-copy">{error}</p>
      </section>
    )
  }

  if (!session) {
    return (
      <section className="flow-card">
        <p className="section-eyebrow">Interview Details</p>
        <h1>Loading details...</h1>
      </section>
    )
  }

  return (
    <section className="page-stack">
      <InterviewSummaryPanel session={session} />
      <div className="footer-actions">
        <NavLink to="/interviews/history" className="secondary-button">
          Back to History
        </NavLink>
        {!session.is_completed && (
          <NavLink to={`/interviews/${session.id}/run`} className="primary-button">
            Resume Interview
          </NavLink>
        )}
      </div>
    </section>
  )
}
