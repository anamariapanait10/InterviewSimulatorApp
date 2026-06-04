import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import CodingInterviewStage from '../components/CodingInterviewStage'
import {
  getInterview,
  getInterviewHint,
  getInterviewModelAnswer,
  recordPracticeDuration,
  skipInterviewQuestion,
  submitInterviewAnswer,
} from '../api'
import type { InterviewSession } from '../types'
import './InterviewFlow.css'

const PRACTICE_FLUSH_INTERVAL_MS = 15000

export default function InterviewRunPage() {
  const { sessionId = '' } = useParams()
  const navigate = useNavigate()
  const [session, setSession] = useState<InterviewSession | null>(null)
  const [answer, setAnswer] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [hint, setHint] = useState<string | null>(null)
  const [modelAnswer, setModelAnswer] = useState<string | null>(null)
  const [isLoadingHint, setIsLoadingHint] = useState(false)
  const [isLoadingModelAnswer, setIsLoadingModelAnswer] = useState(false)
  const sessionRef = useRef<InterviewSession | null>(null)
  const activeStartedAtRef = useRef<number | null>(null)
  const pendingPracticeMsRef = useRef(0)

  const captureElapsedPractice = () => {
    if (activeStartedAtRef.current === null) {
      return
    }

    const now = Date.now()
    pendingPracticeMsRef.current += Math.max(now - activeStartedAtRef.current, 0)
    activeStartedAtRef.current = now
  }

  const stopPracticeTracking = () => {
    if (activeStartedAtRef.current === null) {
      return
    }

    captureElapsedPractice()
    activeStartedAtRef.current = null
  }

  const shouldTrackPractice = () => {
    const currentSession = sessionRef.current
    if (!currentSession || currentSession.is_completed) {
      return false
    }

    return document.visibilityState === 'visible' && document.hasFocus()
  }

  const syncPracticeTrackingState = () => {
    if (shouldTrackPractice()) {
      if (activeStartedAtRef.current === null) {
        activeStartedAtRef.current = Date.now()
      }
      return
    }

    stopPracticeTracking()
  }

  const flushPracticeDuration = async (options?: {
    keepalive?: boolean
    forceStop?: boolean
  }) => {
    if (options?.forceStop) {
      stopPracticeTracking()
    }

    const currentSession = sessionRef.current
    if (!currentSession || currentSession.is_completed) {
      pendingPracticeMsRef.current = 0
      return
    }

    const wholeSeconds = Math.floor(pendingPracticeMsRef.current / 1000)
    if (wholeSeconds <= 0) {
      return
    }

    pendingPracticeMsRef.current -= wholeSeconds * 1000

    try {
      await recordPracticeDuration(currentSession.id, wholeSeconds, {
        keepalive: options?.keepalive,
      })
      setSession((previous) =>
        previous && previous.id === currentSession.id
          ? {
              ...previous,
              practice_duration_seconds: (previous.practice_duration_seconds ?? 0) + wholeSeconds,
            }
          : previous,
      )
    } catch {
      pendingPracticeMsRef.current += wholeSeconds * 1000
    }
  }

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
        setHint(null)
        setModelAnswer(null)
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
  }, [sessionId])

  useEffect(() => {
    if (session?.is_completed) {
      navigate(`/interviews/${session.id}/summary`, { replace: true })
    }
  }, [navigate, session])

  useEffect(() => {
    sessionRef.current = session
    syncPracticeTrackingState()
  }, [session])

  useEffect(() => {
    if (!session || session.is_completed) {
      return
    }

    const handleVisibilityChange = () => {
      syncPracticeTrackingState()
      if (document.visibilityState !== 'visible') {
        void flushPracticeDuration({ forceStop: true })
      }
    }

    const handleWindowFocus = () => {
      syncPracticeTrackingState()
    }

    const handleWindowBlur = () => {
      syncPracticeTrackingState()
      void flushPracticeDuration({ forceStop: true })
    }

    const handlePageHide = () => {
      void flushPracticeDuration({ forceStop: true, keepalive: true })
    }

    const intervalId = window.setInterval(() => {
      if (activeStartedAtRef.current !== null) {
        captureElapsedPractice()
      }
      void flushPracticeDuration()
    }, PRACTICE_FLUSH_INTERVAL_MS)

    document.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('focus', handleWindowFocus)
    window.addEventListener('blur', handleWindowBlur)
    window.addEventListener('pagehide', handlePageHide)
    syncPracticeTrackingState()

    return () => {
      window.clearInterval(intervalId)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      window.removeEventListener('focus', handleWindowFocus)
      window.removeEventListener('blur', handleWindowBlur)
      window.removeEventListener('pagehide', handlePageHide)
      void flushPracticeDuration({ forceStop: true, keepalive: true })
    }
  }, [session?.id, session?.is_completed])

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
      await flushPracticeDuration({ forceStop: true })
      const updated = await submitInterviewAnswer(session.id, trimmedAnswer)
      setSession(updated)
      setAnswer('')
      setHint(null)
      setModelAnswer(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save your answer')
    } finally {
      setIsSubmitting(false)
    }
  }

  const loadHint = async () => {
    if (!session) {
      return
    }

    setError(null)
    setIsLoadingHint(true)
    try {
      const response = await getInterviewHint(session.id)
      setHint(response.content)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load hint')
    } finally {
      setIsLoadingHint(false)
    }
  }

  const loadModelAnswer = async () => {
    if (!session) {
      return
    }

    setError(null)
    setIsLoadingModelAnswer(true)
    try {
      const response = await getInterviewModelAnswer(session.id)
      setModelAnswer(response.content)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load model answer')
    } finally {
      setIsLoadingModelAnswer(false)
    }
  }

  const skipQuestion = async () => {
    if (!session) {
      return
    }

    setError(null)
    setIsSubmitting(true)
    try {
      await flushPracticeDuration({ forceStop: true })
      const updated = await skipInterviewQuestion(session.id)
      setSession(updated)
      setAnswer('')
      setHint(null)
      setModelAnswer(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to skip this question')
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

  const questionStageComplete = session.current_question_index >= session.questions.length
  const currentQuestion = questionStageComplete ? null : session.questions[session.current_question_index]
  const answeredCount = session.answers.length
  const stageCount = session.questions.length + (session.coding_round ? 1 : 0)
  const completedStageCount = answeredCount + (session.is_completed && session.coding_round ? 1 : 0)
  const progressValue = stageCount === 0 ? 0 : (completedStageCount / stageCount) * 100

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
          <span>{answeredCount} question answers saved</span>
          <span>{Math.max(0, stageCount - completedStageCount)} steps remaining</span>
        </div>
        <div className="progress-track" aria-hidden="true">
          <div className="progress-fill" style={{ width: `${progressValue}%` }} />
        </div>
      </article>

      {!questionStageComplete && currentQuestion ? (
        <article className="flow-card question-stage">
          <div className="question-stage-head">
            <span className={`tag ${currentQuestion.category}`}>{currentQuestion.category}</span>
            <strong>
              Question {session.current_question_index + 1} of {session.questions.length}
            </strong>
          </div>
          <h2>{currentQuestion.prompt}</h2>
          <p className="support-copy">
            Answer this part first. The coding round starts after the question stage is complete.
          </p>

          <div className="helper-actions">
            <button
              type="button"
              className="secondary-button"
              disabled={isSubmitting || isLoadingHint || isLoadingModelAnswer}
              onClick={() => void loadHint()}
            >
              {isLoadingHint ? 'Loading hint...' : 'Give Me a Hint'}
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={isSubmitting || isLoadingHint || isLoadingModelAnswer}
              onClick={() => void loadModelAnswer()}
            >
              {isLoadingModelAnswer ? 'Loading answer...' : "I Don't Know the Answer"}
            </button>
          </div>

          {hint && (
            <article className="helper-card">
              <p className="section-eyebrow">Hint</p>
              <p>{hint}</p>
            </article>
          )}

          {modelAnswer && (
            <article className="helper-card">
              <p className="section-eyebrow">Suggested Answer</p>
              <p>{modelAnswer}</p>
            </article>
          )}

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
                  ? 'Saving answer...'
                  : session.current_question_index === session.questions.length - 1
                    ? 'Start Coding Round'
                    : 'Next Question'}
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={isSubmitting}
                onClick={() => void skipQuestion()}
              >
                {isSubmitting ? 'Working...' : 'Skip Question'}
              </button>
            </div>
          </form>
        </article>
      ) : (
        <CodingInterviewStage session={session} onSessionChange={setSession} />
      )}
    </section>
  )
}
