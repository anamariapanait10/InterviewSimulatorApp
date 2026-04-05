import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { deleteInterview, listInterviewHistory } from '../api'
import type { InterviewHistoryItem } from '../types'
import './InterviewFlow.css'

export default function InterviewHistoryPage() {
  const [history, setHistory] = useState<InterviewHistoryItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      setIsLoading(true)
      try {
        const items = await listInterviewHistory()
        if (!cancelled) {
          setHistory(items)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load history')
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [])

  const handleDelete = async (sessionId: string) => {
    setError(null)
    setDeletingId(sessionId)
    try {
      await deleteInterview(sessionId)
      setHistory((previous) => previous.filter((item) => item.id !== sessionId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to delete interview')
    } finally {
      setDeletingId(null)
    }
  }

  if (isLoading) {
    return (
      <section className="flow-card">
        <p className="section-eyebrow">Interview History</p>
        <h1>Loading history...</h1>
      </section>
    )
  }

  if (error) {
    return (
      <section className="flow-card">
        <p className="section-eyebrow">Interview History</p>
        <h1>History unavailable</h1>
        <p className="support-copy">{error}</p>
      </section>
    )
  }

  return (
    <section className="page-stack">
      <article className="flow-card">
        <p className="section-eyebrow">Interview History</p>
        <h1>Review past sessions</h1>
        <p className="support-copy">
          Every interview is saved in the database and can be reopened for the full summary report.
        </p>
      </article>

      {history.length === 0 ? (
        <article className="flow-card">
          <h2>No interviews yet</h2>
          <p className="support-copy">Start a new session to build your first interview record.</p>
        </article>
      ) : (
        <div className="history-grid">
          {history.map((item) => (
            <article key={item.id} className="history-card">
              <div className="history-card-head">
                <p className="section-eyebrow">{item.role_title}</p>
                <span className={item.is_completed ? 'status-dot complete' : 'status-dot pending'}>
                  {item.is_completed ? 'Completed' : 'In progress'}
                </span>
              </div>
              <h2>{item.interview_length ?? 'custom'} interview</h2>
              <div className="meta-grid compact">
                <div>
                  <span>Questions</span>
                  <strong>{item.question_count}</strong>
                </div>
                <div>
                  <span>Answered</span>
                  <strong>{item.answered_count}</strong>
                </div>
                <div>
                  <span>Score</span>
                  <strong>{item.score ?? 'Pending'}</strong>
                </div>
              </div>
              <p className="history-date">{new Date(item.created_at).toLocaleString()}</p>
              <div className="history-actions">
                <NavLink to={`/interviews/${item.id}/details`} className="secondary-button">
                  Open
                </NavLink>
                <button
                  type="button"
                  className="delete-button"
                  disabled={deletingId === item.id}
                  onClick={() => void handleDelete(item.id)}
                >
                  {deletingId === item.id ? 'Deleting...' : 'Delete'}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
