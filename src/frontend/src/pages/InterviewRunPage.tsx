import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { finishInterview, getInterview, submitInterviewAnswer } from '../api'
import type { InterviewSession } from '../types'
import './InterviewFlow.css'

export default function InterviewRunPage() {
  const { sessionId = '' } = useParams()
  const navigate = useNavigate()
  const [session, setSession] = useState<InterviewSession | null>(null)
  const [answer, setAnswer] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false

    const loadSession = async () => {
      setIsLoading(true)
      setError(null)

      try {
        const nextSession = await getInterview(sessionId)
        if (cancelled) {
          return
        }
        setSession(nextSession)
        if (nextSession.is_completed) {
          navigate(`/interviews/${nextSession.id}/summary`, { replace: true })
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load interview')
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void loadSession()

    return () => {
      cancelled = true
    }
  }, [navigate, sessionId])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!session) {
      return
    }

    const trimmedAnswer = answer.trim()
    if (!trimmedAnswer) {
      setError('Write an answer before moving forward.')
      return
    }

    setError(null)
    setIsSubmitting(true)

    try {
      const isLastQuestion = session.current_question_index === session.questions.length - 1
      const updated = isLastQuestion
        ? await finishInterview(session.id, trimmedAnswer)
        : await submitInterviewAnswer(session.id, trimmedAnswer)

      if (isLastQuestion) {
        navigate(`/interviews/${updated.id}/summary`)
        return
      }

      setSession(updated)
      setAnswer('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save your answer')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (isLoading) {
    return (
      <section className="flow-card">
        <p className="section-eyebrow">Interview Runner</p>
        <h1>Loading interview...</h1>
      </section>
    )
  }

  if (!session) {
    return (
      <section className="flow-card">
        <p className="section-eyebrow">Interview Runner</p>
        <h1>Interview unavailable</h1>
        <p className="support-copy">{error ?? 'The requested interview could not be found.'}</p>
      </section>
    )
  }

  const currentQuestion = session.questions[session.current_question_index]
  const answeredCount = session.answers.length
  const totalQuestions = session.questions.length
  const isLastQuestion = session.current_question_index === totalQuestions - 1
  const progressValue = totalQuestions === 0 ? 0 : (answeredCount / totalQuestions) * 100

  return (
    <section className="runner-layout">
      <article className="flow-card runner-header">
        <div className="section-head">
          <div>
            <p className="section-eyebrow">Interview In Progress</p>
            <h1>{session.role_title ?? 'Mock interview'}</h1>
          </div>
          <span className="length-pill">{session.interview_length}</span>
        </div>

        <div className="progress-copy">
          <span>{answeredCount} answered</span>
          <span>{totalQuestions - answeredCount} remaining</span>
        </div>
        <div className="progress-track" aria-hidden="true">
          <div className="progress-fill" style={{ width: `${progressValue}%` }} />
        </div>
      </article>

      <article className="flow-card question-stage">
        <div className="question-stage-head">
          <span className={`tag ${currentQuestion.category}`}>{currentQuestion.category}</span>
          <strong>
            Question {session.current_question_index + 1} of {totalQuestions}
          </strong>
        </div>
        <h2>{currentQuestion.prompt}</h2>
        <p className="support-copy">
          Write your response in full sentences. The next step stores this answer and advances the
          interview.
        </p>

        <form className="answer-form" onSubmit={submit}>
          <label htmlFor="answer-input" className="field-label">
            Your answer
          </label>
          <textarea
            id="answer-input"
            className="large-textarea"
            rows={10}
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            placeholder="Write your answer here..."
            disabled={isSubmitting}
          />

          {error && (
            <p className="status-banner error" role="alert">
              {error}
            </p>
          )}

          <div className="footer-actions">
            <button type="submit" className="primary-button" disabled={isSubmitting}>
              {isSubmitting
                ? isLastQuestion
                  ? 'Finishing interview...'
                  : 'Saving answer...'
                : isLastQuestion
                  ? 'Finish Interview'
                  : 'Next Question'}
            </button>
          </div>
        </form>
      </article>
    </section>
  )
}
