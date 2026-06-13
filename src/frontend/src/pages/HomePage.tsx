import { useEffect, useState } from 'react'
import { listInterviewHistory } from '../api'
import { useAuth } from '../auth'
import type { InterviewHistoryItem } from '../types'
import './InterviewFlow.css'

interface HeatmapCell {
  dateKey: string
  label: string
  count: number
}

const HEATMAP_DAYS = 112
const HEATMAP_WEEKDAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const LENGTH_LABELS = {
  short: 'Short',
  medium: 'Medium',
  long: 'Long',
} as const

function formatDateKey(date: Date): string {
  const year = date.getFullYear()
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${year}-${month}-${day}`
}

function parseDateKey(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function formatShortDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(value))
}

function formatPracticeHours(totalSeconds: number): string {
  return `${(totalSeconds / 3600).toFixed(1)}h`
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`
}

function buildPracticeInsights(history: InterviewHistoryItem[]): string[] {
  if (history.length === 0) {
    return []
  }

  const now = Date.now()
  const fourteenDaysMs = 14 * 24 * 60 * 60 * 1000
  const recent = history.filter((item) => now - Date.parse(item.created_at) <= fourteenDaysMs)
  const previousWindow = history.filter((item) => {
    const age = now - Date.parse(item.created_at)
    return age > fourteenDaysMs && age <= fourteenDaysMs * 2
  })

  const recentCompleted = recent.filter((item) => item.is_completed && typeof item.score === 'number')
  const previousCompleted = previousWindow.filter((item) => item.is_completed && typeof item.score === 'number')
  const recentAverage = recentCompleted.length
    ? recentCompleted.reduce((sum, item) => sum + (item.score ?? 0), 0) / recentCompleted.length
    : null
  const previousAverage = previousCompleted.length
    ? previousCompleted.reduce((sum, item) => sum + (item.score ?? 0), 0) / previousCompleted.length
    : null

  const helpUsedCount = history.filter((item) => item.used_help).length
  const noHelpCount = history.length - helpUsedCount
  const independentRatios = history
    .map((item) => item.independent_answer_ratio)
    .filter((value): value is number => value !== null)
  const averageIndependentRatio = independentRatios.length
    ? independentRatios.reduce((sum, value) => sum + value, 0) / independentRatios.length
    : null
  const totalFocusLossSeconds = history.reduce((sum, item) => sum + item.focus_loss_seconds, 0)
  const latestInterviewAt = Math.max(...history.map((item) => Date.parse(item.created_at)))
  const daysSinceLastInterview = Math.floor((now - latestInterviewAt) / (24 * 60 * 60 * 1000))

  const insights: string[] = []
  if (daysSinceLastInterview >= 10) {
    insights.push(`You have taken a longer break: ${daysSinceLastInterview} days since the last interview.`)
  } else if (recentAverage !== null && previousAverage !== null) {
    const delta = recentAverage - previousAverage
    if (delta >= 5) {
      insights.push(`Your recent results show improvement: average score is up ${Math.round(delta)} points versus the previous two weeks.`)
    } else if (delta <= -5) {
      insights.push(`Recent performance has dipped by ${Math.round(Math.abs(delta))} points compared with the previous two weeks.`)
    } else {
      insights.push('Your scores are fairly stable lately, which suggests a period of consolidation or stagnation.')
    }
  }

  if (averageIndependentRatio !== null) {
    insights.push(
      `You solved ${formatPercent(averageIndependentRatio)} of answered pre-coding questions without using built-in help on average.`,
    )
  }

  insights.push(
    `${noHelpCount} interview${noHelpCount === 1 ? '' : 's'} were completed without help, while ${helpUsedCount} used hints or model answers.`,
  )

  if (totalFocusLossSeconds > 0) {
    insights.push(`You spent about ${Math.round(totalFocusLossSeconds / 60)} minute${Math.round(totalFocusLossSeconds / 60) === 1 ? '' : 's'} away from the interview tab across saved sessions.`)
  }

  return insights.slice(0, 4)
}

function buildTopCompanies(history: InterviewHistoryItem[]) {
  const usage = new Map<string, { name: string; count: number; averageScore: number | null }>()

  for (const item of history) {
    const companyName = item.company_name || item.target_company
    if (!companyName) {
      continue
    }

    const existing = usage.get(companyName) ?? {
      name: companyName,
      count: 0,
      averageScore: null,
    }
    existing.count += 1
    usage.set(companyName, existing)
  }

  return Array.from(usage.values())
    .map((entry) => {
      const related = history.filter(
        (item) =>
          (item.company_name || item.target_company) === entry.name &&
          item.is_completed &&
          typeof item.score === 'number',
      )
      const averageScore = related.length
        ? Math.round(related.reduce((sum, item) => sum + (item.score ?? 0), 0) / related.length)
        : null
      return { ...entry, averageScore }
    })
    .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name))
    .slice(0, 4)
}

function buildHeatmap(history: InterviewHistoryItem[]): HeatmapCell[][] {
  const counts = new Map<string, number>()
  for (const item of history) {
    const created = new Date(item.created_at)
    const dateKey = formatDateKey(created)
    counts.set(dateKey, (counts.get(dateKey) ?? 0) + 1)
  }

  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const cells: HeatmapCell[] = []
  for (let offset = HEATMAP_DAYS - 1; offset >= 0; offset -= 1) {
    const day = new Date(today)
    day.setDate(today.getDate() - offset)
    const dateKey = formatDateKey(day)
    cells.push({
      dateKey,
      count: counts.get(dateKey) ?? 0,
      label: new Intl.DateTimeFormat(undefined, {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
      }).format(day),
    })
  }

  const firstWeekday = (parseDateKey(cells[0].dateKey).getDay() + 6) % 7
  const padded: HeatmapCell[] = [
    ...Array.from({ length: firstWeekday }, (_, index) => ({
      dateKey: `pad-start-${index}`,
      label: '',
      count: -1,
    })),
    ...cells,
  ]

  while (padded.length % 7 !== 0) {
    padded.push({
      dateKey: `pad-end-${padded.length}`,
      label: '',
      count: -1,
    })
  }

  const weeks: HeatmapCell[][] = []
  for (let index = 0; index < padded.length; index += 7) {
    weeks.push(padded.slice(index, index + 7))
  }
  return weeks
}

function heatmapLevel(count: number, maxCount: number): 0 | 1 | 2 | 3 | 4 {
  if (count <= 0 || maxCount <= 0) {
    return 0
  }
  const ratio = count / maxCount
  if (ratio >= 0.8) {
    return 4
  }
  if (ratio >= 0.55) {
    return 3
  }
  if (ratio >= 0.3) {
    return 2
  }
  return 1
}

function ScoreTrendChart({ sessions }: { sessions: InterviewHistoryItem[] }) {
  if (sessions.length === 0) {
    return (
      <div className="chart-empty-state">
        <p className="support-copy">Complete your first interview to unlock score trends.</p>
      </div>
    )
  }

  const width = 640
  const height = 220
  const padding = 24
  const innerWidth = width - padding * 2
  const innerHeight = height - padding * 2

  const points = sessions.map((session, index) => {
    const score = session.score ?? 0
    const x = sessions.length === 1 ? width / 2 : padding + (index / (sessions.length - 1)) * innerWidth
    const y = padding + ((100 - score) / 100) * innerHeight
    return { x, y, score, id: session.id }
  })

  const polyline = points.map((point) => `${point.x},${point.y}`).join(' ')
  const latestScore = sessions[sessions.length - 1]?.score ?? 0

  return (
    <div className="trend-chart-shell">
      <svg viewBox={`0 0 ${width} ${height}`} className="trend-chart" role="img" aria-label="Score evolution chart">
        <defs>
          <linearGradient id="scoreTrendStroke" x1="0%" x2="100%" y1="0%" y2="0%">
            <stop offset="0%" stopColor="var(--accent-coral)" />
            <stop offset="100%" stopColor="var(--accent-warm)" />
          </linearGradient>
        </defs>

        {[0, 25, 50, 75, 100].map((marker) => {
          const y = padding + ((100 - marker) / 100) * innerHeight
          return (
            <g key={marker}>
              <line x1={padding} x2={width - padding} y1={y} y2={y} className="trend-grid-line" />
              <text x={2} y={y + 4} className="trend-axis-label">
                {marker}
              </text>
            </g>
          )
        })}

        {points.length > 1 ? (
          <polyline
            fill="none"
            points={polyline}
            stroke="url(#scoreTrendStroke)"
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}

        {points.map((point) => (
          <circle key={point.id} cx={point.x} cy={point.y} r="5.5" className="trend-point" />
        ))}
      </svg>

      <div className="chart-caption-row">
        <div>
          <p className="section-eyebrow">Latest Score</p>
          <strong className="chart-highlight">{latestScore}</strong>
        </div>
        <div className="chart-x-labels">
          <span>{formatShortDate(sessions[0].created_at)}</span>
          <span>{formatShortDate(sessions[sessions.length - 1].created_at)}</span>
        </div>
      </div>
    </div>
  )
}

function ActivityHeatmap({ history }: { history: InterviewHistoryItem[] }) {
  const weeks = buildHeatmap(history)
  const counts = history.map((item) => formatDateKey(new Date(item.created_at)))
  const activityCounts = new Map<string, number>()
  for (const key of counts) {
    activityCounts.set(key, (activityCounts.get(key) ?? 0) + 1)
  }
  const maxCount = Math.max(0, ...activityCounts.values())

  return (
    <div className="activity-grid-shell">
      <div className="activity-weekday-labels" aria-hidden="true">
        {HEATMAP_WEEKDAY_LABELS.map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>
      <div className="activity-weeks">
        {weeks.map((week, weekIndex) => (
          <div key={`week-${weekIndex}`} className="activity-week">
            {week.map((cell, dayIndex) => {
              if (cell.count < 0) {
                return <span key={cell.dateKey} className="activity-cell pad" aria-hidden="true" />
              }

              const level = heatmapLevel(cell.count, maxCount)
              return (
                <span
                  key={cell.dateKey}
                  className={`activity-cell level-${level}`}
                  role="img"
                  aria-label={`${cell.label}: ${cell.count} interview${cell.count === 1 ? '' : 's'}`}
                  title={`${cell.label}: ${cell.count} interview${cell.count === 1 ? '' : 's'}`}
                  data-row={dayIndex}
                />
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

function LandingCards() {
  return (
    <section className="flow-card landing-simple-card">
      <div className="landing-simple-grid">
        <div className="landing-hero-column">
          <div className="landing-simple-copy">
            <p className="section-eyebrow">Interview Practice</p>
            <h1>Practice the interview before it counts.</h1>
            <p className="support-copy">
              Build one preparation loop around your CV, the role you want, and the kind of interview
              you actually expect to face.
            </p>
          </div>

          <div className="landing-simple-highlights">
            <div className="landing-simple-highlight">
              <strong>Load real context</strong>
              <span>Start with the actual role, not a generic prompt library.</span>
            </div>
            <div className="landing-simple-highlight">
              <strong>Stay in one flow</strong>
              <span>Move from interview setup to live practice and review without switching tools.</span>
            </div>
          </div>
        </div>

        <div className="landing-simple-side">
          <article className="landing-showcase-panel landing-showcase-primary">
            <p className="section-eyebrow">Session Surface</p>
            <h2>A workspace built around one interview loop.</h2>
            <div className="landing-surface-list">
              <p>
                <strong>Practice:</strong> behavioral prompts, technical discussion, and an integrated coding round.
              </p>
              <p>
                <strong>Input:</strong> your CV, the target job description, and the company context you care about.
              </p>
              <p>
                <strong>Output:</strong> structured feedback, saved history, and a clearer next step after every session.
              </p>
            </div>
          </article>

          <div className="landing-panel-grid">
            <article className="landing-showcase-panel">
              <p className="section-eyebrow">Interview Flow</p>
              <h3>One session, multiple stages</h3>
              <p className="support-copy">
                Practice the full rhythm of an interview instead of isolated questions.
              </p>
            </article>

            <article className="landing-showcase-panel">
              <p className="section-eyebrow">Review Loop</p>
              <h3>Feedback you can revisit</h3>
              <p className="support-copy">
                Keep completed sessions, compare outcomes, and sharpen the next attempt.
              </p>
            </article>
          </div>
        </div>
      </div>
    </section>
  )
}

export default function HomePage() {
  const { isAuthenticated, isLoading: isAuthLoading } = useAuth()
  const [history, setHistory] = useState<InterviewHistoryItem[]>([])
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [isHistoryLoading, setIsHistoryLoading] = useState(false)

  useEffect(() => {
    if (!isAuthenticated) {
      setHistory([])
      setHistoryError(null)
      setIsHistoryLoading(false)
      return
    }

    let cancelled = false

    const loadHistory = async () => {
      setIsHistoryLoading(true)
      setHistoryError(null)

      try {
        const items = await listInterviewHistory()
        if (!cancelled) {
          setHistory(items)
        }
      } catch (err) {
        if (!cancelled) {
          setHistoryError(err instanceof Error ? err.message : 'Unable to load dashboard data')
        }
      } finally {
        if (!cancelled) {
          setIsHistoryLoading(false)
        }
      }
    }

    void loadHistory()

    return () => {
      cancelled = true
    }
  }, [isAuthenticated])

  const completedSessions = history
    .filter((item) => item.is_completed && typeof item.score === 'number')
    .sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at))
  const completedCount = history.filter((item) => item.is_completed).length
  const averageScore = completedSessions.length
    ? Math.round(completedSessions.reduce((sum, item) => sum + (item.score ?? 0), 0) / completedSessions.length)
    : null
  const totalPracticeSeconds = history.reduce(
    (sum, item) => sum + (item.practice_duration_seconds ?? 0),
    0,
  )
  const activityDays = new Set(history.map((item) => formatDateKey(new Date(item.created_at)))).size
  const bestScore = completedSessions.length
    ? Math.max(...completedSessions.map((item) => item.score ?? 0))
    : null
  const completionRate = history.length === 0 ? 0 : Math.round((completedCount / history.length) * 100)
  const scoreDelta =
    completedSessions.length >= 2
      ? (completedSessions[completedSessions.length - 1]?.score ?? 0) -
        (completedSessions[completedSessions.length - 2]?.score ?? 0)
      : null
  const lengthBreakdown = {
    short: history.filter((item) => item.interview_length === 'short').length,
    medium: history.filter((item) => item.interview_length === 'medium').length,
    long: history.filter((item) => item.interview_length === 'long').length,
  }
  const maxLengthCount = Math.max(1, lengthBreakdown.short, lengthBreakdown.medium, lengthBreakdown.long)
  const topCompanies = buildTopCompanies(history)
  const interviewsWithHelp = history.filter((item) => item.used_help).length
  const interviewsWithoutHelp = history.length - interviewsWithHelp
  const independentAnswerRatioValues = history
    .map((item) => item.independent_answer_ratio)
    .filter((value): value is number => value !== null)
  const averageIndependentAnswerRatio = independentAnswerRatioValues.length
    ? independentAnswerRatioValues.reduce((sum, value) => sum + value, 0) / independentAnswerRatioValues.length
    : null
  const totalFocusLossMinutes = Math.round(
    history.reduce((sum, item) => sum + item.focus_loss_seconds, 0) / 60,
  )
  const practiceInsights = buildPracticeInsights(history)

  return (
    <section className="home-layout">
      {isAuthenticated ? (
        <>
          {isAuthLoading || isHistoryLoading ? (
            <article className="flow-card">
              <p className="section-eyebrow">Dashboard</p>
              <h2>Loading your practice dashboard...</h2>
            </article>
          ) : historyError ? (
            <article className="flow-card">
              <p className="section-eyebrow">Dashboard</p>
              <h2>Dashboard unavailable</h2>
              <p className="support-copy">{historyError}</p>
            </article>
          ) : (
            <>
              <section className="dashboard-stats-grid">
                <article className="dashboard-stat-card">
                  <p>Total interviews</p>
                  <strong>{history.length}</strong>
                  <span>{completedCount} completed</span>
                </article>
                <article className="dashboard-stat-card">
                  <p>Average score</p>
                  <strong>{averageScore ?? '--'}</strong>
                  <span>
                    {scoreDelta === null
                      ? 'Need at least two completed interviews for a trend'
                      : `${scoreDelta >= 0 ? '+' : ''}${scoreDelta} vs previous session`}
                  </span>
                </article>
                <article className="dashboard-stat-card">
                  <p>Practice time</p>
                  <strong>{formatPracticeHours(totalPracticeSeconds)}</strong>
                  <span>Tracked while the interview page is active</span>
                </article>
                <article className="dashboard-stat-card">
                  <p>Practice days</p>
                  <strong>{activityDays}</strong>
                  <span>{completionRate}% completion rate</span>
                </article>
              </section>

              <section className="dashboard-grid">
                <article className="flow-card dashboard-panel chart-panel">
                  <div className="section-head">
                    <div>
                      <p className="section-eyebrow">Score Evolution</p>
                      <h2>See whether your answers are getting stronger</h2>
                    </div>
                    {bestScore !== null ? <span className="length-pill">Best {bestScore}</span> : null}
                  </div>
                  <ScoreTrendChart sessions={completedSessions} />
                </article>

                <article className="flow-card dashboard-panel activity-panel">
                  <div className="section-head">
                    <div>
                      <p className="section-eyebrow">Practice Rhythm</p>
                      <h2>Recent activity over the last 16 weeks</h2>
                    </div>
                  </div>
                  <div className="activity-panel-body">
                    <ActivityHeatmap history={history} />
                    <div className="activity-legend">
                      <span>Less</span>
                      <div className="activity-legend-scale">
                        <span className="activity-cell level-0" />
                        <span className="activity-cell level-1" />
                        <span className="activity-cell level-2" />
                        <span className="activity-cell level-3" />
                        <span className="activity-cell level-4" />
                      </div>
                      <span>More</span>
                    </div>
                  </div>
                </article>

                <article className="flow-card dashboard-panel mix-panel">
                  <p className="section-eyebrow">Interview Mix</p>
                  <h2>How you are distributing practice length</h2>
                  <div className="mix-chart">
                    {(['short', 'medium', 'long'] as const).map((length) => {
                      const value = lengthBreakdown[length]
                      const width = `${(value / maxLengthCount) * 100}%`
                      return (
                        <div key={length} className="mix-row">
                          <div className="mix-copy">
                            <strong>{LENGTH_LABELS[length]}</strong>
                            <span>{value} sessions</span>
                          </div>
                          <div className="mix-bar-track">
                            <div className={`mix-bar ${length}`} style={{ width }} />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </article>

                <article className="flow-card dashboard-panel insight-panel">
                  <p className="section-eyebrow">Recent Feedback</p>
                  <h2>What your latest practice pattern suggests</h2>
                  {practiceInsights.length === 0 ? (
                    <p className="support-copy">
                      Finish a few interviews to unlock trend-based coaching.
                    </p>
                  ) : (
                    <ul className="detail-list dashboard-insights">
                      {practiceInsights.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  )}
                </article>

                <article className="flow-card dashboard-panel insight-panel">
                  <p className="section-eyebrow">Independence</p>
                  <h2>How often you rely on help during practice</h2>
                  <div className="independence-grid">
                    <article className="independence-card">
                      <span className="independence-label">Without help</span>
                      <strong className="independence-value">{interviewsWithoutHelp}</strong>
                      <p className="independence-note">Sessions completed without using hints or model answers.</p>
                    </article>

                    <article className="independence-card">
                      <span className="independence-label">With help</span>
                      <strong className="independence-value">{interviewsWithHelp}</strong>
                      <p className="independence-note">Sessions where you relied on built-in support during practice.</p>
                    </article>

                    <article className="independence-card">
                      <span className="independence-label">Independent answer rate</span>
                      <strong className="independence-value">
                        {averageIndependentAnswerRatio === null
                          ? 'Unavailable'
                          : formatPercent(averageIndependentAnswerRatio)}
                      </strong>
                      <p className="independence-note">Average share of answered pre-coding prompts handled without help.</p>
                    </article>

                    <article className="independence-card">
                      <span className="independence-label">Focus loss time</span>
                      <strong className="independence-value">{totalFocusLossMinutes} min</strong>
                      <p className="independence-note">Estimated time spent away from the interview tab across saved sessions.</p>
                    </article>
                  </div>
                </article>

                <article className="flow-card dashboard-panel insight-panel">
                  <p className="section-eyebrow">Top Companies</p>
                  <h2>Where you focus most of your preparation</h2>
                  {topCompanies.length === 0 ? (
                    <p className="support-copy">
                      Start a company-specific interview to see which targets dominate your practice.
                    </p>
                  ) : (
                    <div className="company-usage-list">
                      {topCompanies.map((company) => (
                        <article key={company.name} className="company-usage-card">
                          <div>
                            <strong>{company.name}</strong>
                            <span>{company.count} session{company.count === 1 ? '' : 's'}</span>
                          </div>
                          <b>{company.averageScore ?? '--'}</b>
                        </article>
                      ))}
                    </div>
                  )}
                </article>
              </section>
            </>
          )}
        </>
      ) : (
        <LandingCards />
      )}
    </section>
  )
}
