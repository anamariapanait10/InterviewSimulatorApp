import type { InterviewSession } from '../types'

interface InterviewSummaryPanelProps {
  session: InterviewSession
}

function formatDuration(totalSeconds: number | null): string {
  if (totalSeconds === null || totalSeconds <= 0) {
    return 'Not recorded'
  }

  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)

  if (hours > 0) {
    return `${hours}h ${minutes}m`
  }

  return `${minutes}m`
}

function formatScore(total: number | null | undefined, suffix = '/100'): string {
  if (total === null || total === undefined) {
    return 'Unavailable'
  }

  return `${total}${suffix}`
}

export default function InterviewSummaryPanel({ session }: InterviewSummaryPanelProps) {
  if (!session.report) {
    return (
      <section className="flow-card">
        <p className="section-eyebrow">Interview Report</p>
        <h1>Report unavailable</h1>
        <p className="support-copy">This interview has not been scored yet.</p>
      </section>
    )
  }

  const feedbackByQuestionId = new Map(
    session.report.question_feedback.map((feedback) => [feedback.question_id, feedback]),
  )

  return (
    <section className="summary-layout">
      <article className="flow-card score-card">
        <p className="section-eyebrow">Interview Outcome</p>
        <h1>{session.role_title ?? 'Interview summary'}</h1>
        <div className="summary-columns">
          <div className="score-badge" aria-label={`Interview score ${session.score ?? 0} out of 100`}>
            <span>{session.score ?? 0}</span>
            <small>/100 interview</small>
          </div>
          <div className="score-badge" aria-label={`Job match score ${session.report.job_match_score ?? 0} out of 100`}>
            <span>{session.report.job_match_score ?? '—'}</span>
            <small>{session.report.job_match_score === null ? 'job fit unavailable' : '/100 job fit'}</small>
          </div>
        </div>
        <p className="support-copy">{session.report.summary}</p>
        <div className="meta-grid compact">
          <div>
            <span>Length</span>
            <strong>{session.interview_length ?? 'custom'}</strong>
          </div>
          <div>
            <span>Company</span>
            <strong>{session.target_company ?? session.coding_round?.matched_company ?? 'General bank'}</strong>
          </div>
          <div>
            <span>Practice Time</span>
            <strong>{formatDuration(session.practice_duration_seconds)}</strong>
          </div>
          <div>
            <span>Completed</span>
            <strong>{session.completed_at ? new Date(session.completed_at).toLocaleString() : 'In progress'}</strong>
          </div>
        </div>
      </article>

      <article className="flow-card">
        <p className="section-eyebrow">Job Fit</p>
        <div className="summary-columns">
          <section>
            <h2>Match Assessment</h2>
            <p>{session.report.job_match_feedback ?? 'Job fit details were not produced in this report.'}</p>
            <p className="review-feedback">
              Recommendation: {session.report.hire_recommendation || session.report.recommendation}
            </p>
          </section>
          <section>
            <h2>Role Alignment</h2>
            <div className="summary-columns">
              <section>
                <h3>Strong matches</h3>
                <ul className="detail-list">
                  {(session.report.matched_requirements.length > 0
                    ? session.report.matched_requirements
                    : ['Not available in this report.']).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
              <section>
                <h3>Gaps to close</h3>
                <ul className="detail-list">
                  {(session.report.missing_requirements.length > 0
                    ? session.report.missing_requirements
                    : ['Not available in this report.']).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
            </div>
          </section>
        </div>
      </article>

      <article className="flow-card">
        <p className="section-eyebrow">Key Takeaways</p>
        <div className="summary-columns">
          <section>
            <h2>Strengths</h2>
            <ul className="detail-list">
              {session.report.strengths.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
          <section>
            <h2>Improvements</h2>
            <ul className="detail-list">
              {session.report.improvements.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
        </div>
      </article>

      {session.evaluation && (
        <article className="flow-card">
          <p className="section-eyebrow">Score Breakdown</p>
          <div className="score-breakdown-grid">
            {[
              { label: 'Behavioral', value: `${session.evaluation.behavioral_score}/100` },
              { label: 'Technical', value: `${session.evaluation.technical_score}/100` },
              { label: 'Coding', value: `${session.evaluation.coding_score}/100` },
              { label: 'Communication', value: `${session.evaluation.communication_score}/100` },
              { label: 'Job fit', value: formatScore(session.evaluation.job_match_score) },
            ].map((item) => (
              <article key={item.label} className="score-breakdown-card">
                <span className="score-breakdown-label">{item.label}</span>
                <strong className="score-breakdown-value">{item.value}</strong>
              </article>
            ))}
          </div>
        </article>
      )}

      <article className="flow-card">
        <p className="section-eyebrow">Detailed Report</p>
        <div className="narrative-grid">
          <section>
            <h2>Behavioral</h2>
            <p>{session.report.behavioral_feedback}</p>
          </section>
          <section>
            <h2>Technical</h2>
            <p>{session.report.technical_feedback}</p>
          </section>
          <section>
            <h2>Communication</h2>
            <p>{session.report.communication_feedback}</p>
          </section>
          <section>
            <h2>Job fit vs interview performance</h2>
            <p>
              Overall interview score: {formatScore(session.score)}. Job fit score: {formatScore(session.report.job_match_score)}.
              Use the job fit score to judge background alignment with the role, and the interview score to judge how
              strongly that fit was demonstrated in this session.
            </p>
          </section>
        </div>
      </article>

      {session.report.coding_evaluation && (
        <article className="flow-card">
          <p className="section-eyebrow">Coding Evaluation</p>
          <div className="summary-columns">
            <section>
              <h2>Scorecard</h2>
              <div className="score-breakdown-grid coding-score-grid">
                {[
                  { label: 'Communication', value: `${session.report.coding_evaluation.communication}/10` },
                  { label: 'Problem solving', value: `${session.report.coding_evaluation.problem_solving}/10` },
                  { label: 'Coding', value: `${session.report.coding_evaluation.coding}/10` },
                  { label: 'Complexity analysis', value: `${session.report.coding_evaluation.complexity_analysis}/10` },
                  { label: 'Debugging', value: `${session.report.coding_evaluation.debugging}/10` },
                  { label: 'Edge cases', value: `${session.report.coding_evaluation.edge_cases}/10` },
                ].map((item) => (
                  <article key={item.label} className="score-breakdown-card">
                    <span className="score-breakdown-label">{item.label}</span>
                    <strong className="score-breakdown-value">{item.value}</strong>
                  </article>
                ))}
              </div>
            </section>
            <section>
              <h2>Outcome</h2>
              <p>{session.report.coding_feedback}</p>
              <p className="review-feedback">
                Hire recommendation: {session.report.coding_evaluation.hire_recommendation}
              </p>
            </section>
          </div>
        </article>
      )}

      <article className="flow-card">
        <p className="section-eyebrow">Question Review</p>
        <div className="question-review-list">
          {session.questions.map((question) => {
            const answer = session.answers.find((entry) => entry.question_id === question.id)
            const feedback = feedbackByQuestionId.get(question.id)
            return (
              <article key={question.id} className="question-review-item">
                <div className="question-review-head">
                  <span className={`tag ${question.category}`}>{question.category}</span>
                  <strong>{feedback ? `${feedback.score}/10` : 'Pending'}</strong>
                </div>
                <h3>{question.prompt}</h3>
                <p className="review-answer">{answer?.answer_text ?? 'No answer recorded.'}</p>
                {feedback && <p className="review-feedback">{feedback.feedback}</p>}
              </article>
            )
          })}
        </div>
      </article>

      {session.coding_round?.problem && (
        <article className="flow-card">
          <p className="section-eyebrow">Coding Round Details</p>
          <h2>{session.coding_round.problem.title}</h2>
          <p className="support-copy">{session.coding_round.problem.prompt}</p>
          {session.coding_round.evaluation && (
            <div className="summary-columns mt-2">
              <section>
                <h3>Strengths</h3>
                <ul className="detail-list">
                  {session.coding_round.evaluation.strengths.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
              <section>
                <h3>Concerns</h3>
                <ul className="detail-list">
                  {session.coding_round.evaluation.concerns.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
            </div>
          )}
        </article>
      )}
    </section>
  )
}
