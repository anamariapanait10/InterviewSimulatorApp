import type { InterviewSession } from '../types'

interface InterviewSummaryPanelProps {
  session: InterviewSession
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
        <div className="score-badge" aria-label={`Interview score ${session.score ?? 0} out of 100`}>
          <span>{session.score ?? 0}</span>
          <small>/100</small>
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
            <span>Questions</span>
            <strong>{session.questions.length}</strong>
          </div>
          <div>
            <span>Completed</span>
            <strong>{session.completed_at ? new Date(session.completed_at).toLocaleString() : 'In progress'}</strong>
          </div>
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
            <h2>Recommendation</h2>
            <p>{session.report.hire_recommendation || session.report.recommendation}</p>
          </section>
        </div>
      </article>

      {session.report.coding_evaluation && (
        <article className="flow-card">
          <p className="section-eyebrow">Coding Evaluation</p>
          <div className="summary-columns">
            <section>
              <h2>Scorecard</h2>
              <div className="score-list">
                <p>Communication: {session.report.coding_evaluation.communication}/10</p>
                <p>Problem solving: {session.report.coding_evaluation.problem_solving}/10</p>
                <p>Coding: {session.report.coding_evaluation.coding}/10</p>
                <p>Complexity analysis: {session.report.coding_evaluation.complexity_analysis}/10</p>
                <p>Debugging: {session.report.coding_evaluation.debugging}/10</p>
                <p>Edge cases: {session.report.coding_evaluation.edge_cases}/10</p>
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
