import { useEffect, useState } from 'react'
import type { ChangeEvent, Dispatch, SetStateAction } from 'react'
import { useNavigate } from 'react-router-dom'
import { createInterview, listCompanies, parseDocument, parseJobUrl } from '../api'
import type { Company } from '../types'
import './InterviewFlow.css'

type InputMode = 'text' | 'file' | 'link'
type InterviewLength = 'short' | 'medium' | 'long'
type CodingDifficulty = 'easy' | 'medium' | 'hard'
type InterviewerMode = 'warm' | 'neutral' | 'bar_raiser' | 'silent'
type PreferredLanguage = 'typescript' | 'javascript' | 'python' | 'java' | 'csharp'

interface ParsedSourceState {
  mode: InputMode
  text: string
  fileName: string | null
  isParsing: boolean
  linkUrl: string
  importedFrom: string | null
}

const LENGTH_OPTIONS: Array<{
  value: InterviewLength
  title: string
  description: string
}> = [
  { value: 'short', title: 'Short', description: '2 behavioral and 2 technical questions' },
  { value: 'medium', title: 'Medium', description: '4 behavioral and 4 technical questions' },
  { value: 'long', title: 'Long', description: '6 behavioral and 6 technical questions' },
]

function normalizeCompanyLabel(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ')
}

function inferCompanyFromJobDescription(text: string): string | null {
  const trimmed = text.trim()
  if (!trimmed) {
    return null
  }

  const patterns = [
    /(?:company|organization)\s*:\s*([^\n|]+)/i,
    /join\s+([A-Z][A-Za-z0-9&.,' -]{1,60}?)(?:\s+as|\s+to|\s+for|\s+on|\s*,|\.)/i,
    /at\s+([A-Z][A-Za-z0-9&.,' -]{1,60}?)(?:\s+as|\s+to|\s+for|\s+on|\s*,|\.)/i,
  ]

  for (const pattern of patterns) {
    const match = trimmed.match(pattern)
    const company = match?.[1]?.trim()
    if (company) {
      return company
    }
  }

  const lines = trimmed
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 8)

  for (const line of lines) {
    if (/linkedin|about the job|responsibilities|requirements/i.test(line)) {
      continue
    }

    const compact = line.replace(/\s+/g, ' ').trim()
    if (/^[A-Z][A-Za-z0-9&.,' -]{1,60}$/.test(compact) && compact.split(' ').length <= 6) {
      return compact
    }
  }

  return null
}

function SourceCard(props: {
  id: string
  label: string
  value: ParsedSourceState
  onModeChange: (mode: InputMode) => void
  onTextChange: (text: string) => void
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void
  onLinkChange?: (text: string) => void
  onLinkImport?: () => void
  allowLink?: boolean
}) {
  const { id, label, value, onModeChange, onTextChange, onFileChange, onLinkChange, onLinkImport, allowLink } = props

  return (
    <article className="flow-card">
      <div className="section-head">
        <div>
          <p className="section-eyebrow">{label}</p>
          <h2>{value.mode === 'text' ? 'Paste content directly' : 'Upload a document'}</h2>
        </div>
        <div className="mode-toggle" role="tablist" aria-label={`${label} input mode`}>
          <button
            type="button"
            className={value.mode === 'text' ? 'toggle-option active' : 'toggle-option'}
            onClick={() => onModeChange('text')}
          >
            Text
          </button>
          <button
            type="button"
            className={value.mode === 'file' ? 'toggle-option active' : 'toggle-option'}
            onClick={() => onModeChange('file')}
          >
            File
          </button>
          {allowLink ? (
            <button
              type="button"
              className={value.mode === 'link' ? 'toggle-option active' : 'toggle-option'}
              onClick={() => onModeChange('link')}
            >
              Link
            </button>
          ) : null}
        </div>
      </div>

      {value.mode === 'text' ? (
        <>
          <label htmlFor={id} className="field-label">
            {label}
          </label>
          <textarea
            id={id}
            className="large-textarea"
            rows={12}
            placeholder={`Paste the ${label.toLowerCase()} here...`}
            value={value.text}
            onChange={(event) => onTextChange(event.target.value)}
          />
        </>
      ) : value.mode === 'file' ? (
        <div className="upload-panel">
          <label className="file-input">
            <input type="file" accept=".pdf,.doc,.docx,.txt,.md,.html" onChange={onFileChange} />
            <span>{value.isParsing ? 'Parsing document...' : 'Choose PDF or DOCX'}</span>
          </label>
          <p className="support-copy">
            Files are parsed into text before the interview starts so the generated questions can use
            their content.
          </p>
          {value.fileName && (
            <div className="parsed-preview">
              <strong>{value.fileName}</strong>
            </div>
          )}
        </div>
      ) : (
        <div className="upload-panel">
          <label htmlFor={`${id}-link`} className="field-label">
            {label} URL
          </label>
          <input
            id={`${id}-link`}
            className="text-input"
            type="url"
            placeholder="Paste the job post URL here..."
            value={value.linkUrl}
            onChange={(event) => onLinkChange?.(event.target.value)}
          />
          <button
            type="button"
            className="secondary-button"
            disabled={value.isParsing || !value.linkUrl.trim()}
            onClick={onLinkImport}
          >
            {value.isParsing ? 'AI is extracting the job post...' : 'Import job post'}
          </button>
          <p className="support-copy">
            Supports direct job links, including public LinkedIn job posts, and uses AI to extract the job description into the interview context.
          </p>
          {value.fileName && (
            <div className="parsed-preview">
              <strong>{value.fileName}</strong>
            </div>
          )}
        </div>
      )}
    </article>
  )
}

export default function InterviewSetupPage() {
  const navigate = useNavigate()
  const [resume, setResume] = useState<ParsedSourceState>({
    mode: 'text',
    text: '',
    fileName: null,
    isParsing: false,
    linkUrl: '',
    importedFrom: null,
  })
  const [jobDescription, setJobDescription] = useState<ParsedSourceState>({
    mode: 'text',
    text: '',
    fileName: null,
    isParsing: false,
    linkUrl: '',
    importedFrom: null,
  })
  const [interviewLength, setInterviewLength] = useState<InterviewLength>('medium')
  const [companies, setCompanies] = useState<Company[]>([])
  const [selectedCompanyId, setSelectedCompanyId] = useState('__custom__')
  const [customTargetCompany, setCustomTargetCompany] = useState('')
  const [companyTouched, setCompanyTouched] = useState(false)
  const [codingDifficulty, setCodingDifficulty] = useState<CodingDifficulty>('medium')
  const [interviewerMode, setInterviewerMode] = useState<InterviewerMode>('neutral')
  const [voiceEnabled, setVoiceEnabled] = useState(false)
  const [preferredLanguage, setPreferredLanguage] = useState<PreferredLanguage>('typescript')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false

    const loadCompanies = async () => {
      try {
        const items = await listCompanies()
        if (cancelled) {
          return
        }
        setCompanies(items)
      } catch {
        if (!cancelled) {
          setCompanies([])
        }
      }
    }

    void loadCompanies()
    return () => {
      cancelled = true
    }
  }, [])

  const applyDetectedCompany = (companyName: string | null) => {
    if (companyTouched || !companyName?.trim()) {
      return
    }

    const normalizedCandidate = normalizeCompanyLabel(companyName)
    const matchedCompany = companies.find(
      (company) => normalizeCompanyLabel(company.name) === normalizedCandidate,
    )

    if (matchedCompany) {
      setSelectedCompanyId(matchedCompany.id)
      setCustomTargetCompany('')
      return
    }

    setSelectedCompanyId('__custom__')
    setCustomTargetCompany(companyName.trim())
  }

  useEffect(() => {
    if (companyTouched || companies.length === 0 || !customTargetCompany.trim()) {
      return
    }

    const matchedCompany = companies.find(
      (company) => normalizeCompanyLabel(company.name) === normalizeCompanyLabel(customTargetCompany),
    )

    if (matchedCompany) {
      setSelectedCompanyId(matchedCompany.id)
      setCustomTargetCompany('')
    }
  }, [companies, companyTouched, customTargetCompany])

  const selectedCompany = companies.find((company) => company.id === selectedCompanyId) ?? null
  const isCustomCompany = selectedCompanyId === '__custom__'
  const resolvedTargetCompany = isCustomCompany
    ? customTargetCompany.trim()
    : (selectedCompany?.name ?? '').trim()

  const handleFileParse = async (
    file: File | undefined,
    setter: Dispatch<SetStateAction<ParsedSourceState>>,
    options?: { detectTargetCompany?: boolean },
  ) => {
    if (!file) {
      return
    }

    setError(null)
    setter((previous) => ({ ...previous, isParsing: true }))

    try {
      const parsed = await parseDocument(file)
      setter((previous) => ({
        ...previous,
        fileName: parsed.file_name,
        text: parsed.extracted_text,
        isParsing: false,
        importedFrom: null,
      }))
      if (options?.detectTargetCompany) {
        applyDetectedCompany(inferCompanyFromJobDescription(parsed.extracted_text))
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to parse document'
      setError(message)
      setter((previous) => ({ ...previous, isParsing: false }))
    }
  }

  const handleJobLinkImport = async (url?: string): Promise<string | null> => {
    const nextUrl = (url ?? jobDescription.linkUrl).trim()
    if (!nextUrl) {
      setError('Paste a job post URL before importing it.')
      return null
    }

    setError(null)
    setJobDescription((previous) => ({ ...previous, isParsing: true }))

    try {
      const parsed = await parseJobUrl(nextUrl)
      setJobDescription((previous) => ({
        ...previous,
        text: parsed.extracted_text,
        fileName: parsed.title,
        importedFrom: parsed.source_url,
        isParsing: false,
      }))
      applyDetectedCompany(inferCompanyFromJobDescription(parsed.extracted_text) ?? parsed.title)
      return parsed.extracted_text
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to import the job post')
      setJobDescription((previous) => ({ ...previous, isParsing: false }))
      return null
    }
  }

  const startInterview = async () => {
    const resumeText = resume.text.trim()
    let jobDescriptionText = jobDescription.text.trim()

    if (jobDescription.mode === 'link') {
      const linkUrl = jobDescription.linkUrl.trim()
      if (!linkUrl) {
        setError('The job post link is required before starting the interview.')
        return
      }
      if (!jobDescriptionText || jobDescription.importedFrom !== linkUrl) {
        const importedText = await handleJobLinkImport(linkUrl)
        if (!importedText) {
          return
        }
        jobDescriptionText = importedText.trim()
      }
    }

    if (!resumeText || !jobDescriptionText) {
      setError('Both the CV and the job description are required before starting the interview.')
      return
    }

    if (!resolvedTargetCompany) {
      setError('Choose a target company or enter a custom company before starting the interview.')
      return
    }

    setError(null)
    setIsSubmitting(true)

    try {
      const session = await createInterview({
        resume_text: resumeText,
        job_description_text: jobDescriptionText,
        job_description_link: jobDescription.mode === 'link' ? jobDescription.linkUrl.trim() || undefined : undefined,
        interview_length: interviewLength,
        target_company: resolvedTargetCompany,
        company_id: !isCustomCompany ? selectedCompanyId || undefined : undefined,
        voice_enabled: voiceEnabled,
        coding_difficulty: codingDifficulty,
        interviewer_mode: interviewerMode,
        preferred_language: preferredLanguage,
      })
      navigate(`/interviews/${session.id}/run`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create interview')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className="setup-layout">
      <article className="flow-card intro-card">
        <p className="section-eyebrow">Interview Setup</p>
        <h1>Configure the interview parameters.</h1>
        <p className="support-copy mt-2">
          Load the candidate context, choose the interview format, and include the live coding round.
        </p>
      </article>

      <div className="setup-grid">
        <SourceCard
          id="resume-input"
          label="CV"
          value={resume}
          onModeChange={(mode) => setResume((previous) => ({ ...previous, mode }))}
          onTextChange={(text) =>
            setResume((previous) => ({ ...previous, text, fileName: null, importedFrom: null }))
          }
          onFileChange={(event) => void handleFileParse(event.target.files?.[0], setResume)}
        />

        <SourceCard
          id="job-description-input"
          label="Job Description"
          value={jobDescription}
          onModeChange={(mode) => setJobDescription((previous) => ({ ...previous, mode }))}
          onTextChange={(text) => {
            setJobDescription((previous) => ({ ...previous, text, fileName: null, importedFrom: null }))
            applyDetectedCompany(inferCompanyFromJobDescription(text))
          }}
          onFileChange={(event) =>
            void handleFileParse(event.target.files?.[0], setJobDescription, { detectTargetCompany: true })
          }
          onLinkChange={(text) =>
            setJobDescription((previous) => ({
              ...previous,
              linkUrl: text,
              importedFrom: previous.importedFrom === text.trim() ? previous.importedFrom : null,
            }))
          }
          onLinkImport={() => void handleJobLinkImport()}
          allowLink
        />
      </div>

      <article className="flow-card">
        <div className="section-head">
          <div>
            <p className="section-eyebrow">Interview Format</p>
            <h2>Choose the interview length and voice mode</h2>
          </div>
        </div>
        <div className="triple-option-grid mt-2">
          {LENGTH_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={interviewLength === option.value ? 'length-option active' : 'length-option'}
              onClick={() => setInterviewLength(option.value)}
            >
              <strong style={{ color: "white" }}>{option.title}</strong>
              <span>{option.description}</span>
            </button>
          ))}
        </div>

        <div className="subsection-head mt-2">
          <div>
            <p className="section-eyebrow">Voice Mode</p>
            <h3>Choose whether voice stays available during the interview</h3>
          </div>
        </div>
        <div className="mt-2">
          <button
            type="button"
            className={voiceEnabled ? 'voice-toggle-button active' : 'voice-toggle-button'}
            onClick={() => setVoiceEnabled((current) => !current)}
            aria-pressed={voiceEnabled}
          >
            <span className="voice-toggle-track" aria-hidden="true">
              <span className="voice-toggle-thumb" />
            </span>
            <span className="voice-toggle-copy">
              <strong style={{ color: 'white' }}>{voiceEnabled ? 'Voice on' : 'Voice off'}</strong>
              <span>
                {voiceEnabled
                  ? 'The interviewer can speak and microphone controls stay available during the interview.'
                  : 'The interview stays fully text-based from start to finish.'}
              </span>
            </span>
          </button>
        </div>
      </article>

      <article className="flow-card">
        <div className="section-head">
          <div>
            <p className="section-eyebrow">Coding Round</p>
            <h2>Configure the live coding stage</h2>
          </div>
        </div>

        <div className="setup-grid coding-config-grid">
          <div className="company-select-wrap">
            <div className="form-field-stack">
              <label htmlFor="company-select" className="field-label">
                Target company
              </label>
              <select
                id="company-select"
                className="text-input"
                value={selectedCompanyId}
                onChange={(event) => {
                  setCompanyTouched(true)
                  setSelectedCompanyId(event.target.value)
                }}
              >
                <option value="__custom__">Custom...</option>
                {companies.map((company) => (
                  <option key={company.id} value={company.id}>
                    {company.name}
                  </option>
                ))}
              </select>
            </div>
            {isCustomCompany ? (
              <div className="form-field-stack">
                <input
                  id="company-input"
                  className="text-input"
                  value={customTargetCompany}
                  onChange={(event) => {
                    setCompanyTouched(true)
                    setCustomTargetCompany(event.target.value)
                  }}
                  placeholder="Google, Meta, Amazon..."
                />
              </div>
            ) : null}
            <p className="support-copy mt-2">
              {isCustomCompany
                ? 'Enter a custom company name for interview style and coding problem matching.'
                : 'Uses the saved company knowledge workspace and the same company name for coding problem selection.'}
            </p>
          </div>

          <div className="form-field-stack">
            <label htmlFor="language-select" className="field-label">
              Preferred language
            </label>
            <select
              id="language-select"
              className="text-input"
              value={preferredLanguage}
              onChange={(event) => setPreferredLanguage(event.target.value as PreferredLanguage)}
            >
              <option value="typescript">TypeScript</option>
              <option value="javascript">JavaScript</option>
              <option value="python">Python</option>
              <option value="java">Java</option>
              <option value="csharp">C#</option>
            </select>
          </div>
        </div>

        <div className="subsection-head mt-2">
          <div>
            <p className="section-eyebrow">Coding Difficulty</p>
            <h3>Choose the coding challenge level</h3>
          </div>
        </div>
        <div className="triple-option-grid mt-2">
          {(['easy', 'medium', 'hard'] as CodingDifficulty[]).map((option) => (
            <button
              key={option}
              type="button"
              className={codingDifficulty === option ? 'length-option active' : 'length-option'}
              onClick={() => setCodingDifficulty(option)}
            >
              <strong style={{ color: 'white' }}>{option}</strong>
              <span>
                {option === 'hard'
                  ? 'Plain editor, no syntax highlighting'
                  : 'Monaco editor with full coding support'}
              </span>
            </button>
          ))}
        </div>

        <div className="subsection-head mt-2">
          <div>
            <p className="section-eyebrow">Interviewer Style</p>
            <h3>Choose how strict the interviewer feels</h3>
          </div>
        </div>
        <div className="quad-option-grid mt-2">
          {(['warm', 'neutral', 'bar_raiser', 'silent'] as InterviewerMode[]).map((option) => (
            <button
              key={option}
              type="button"
              className={interviewerMode === option ? 'length-option active' : 'length-option'}
              onClick={() => setInterviewerMode(option)}
            >
              <strong style={{ color: 'white' }}>{option.replace('_', ' ')}</strong>
              <span>
                {option === 'warm' && 'Short prompts, a little more supportive'}
                {option === 'neutral' && 'Balanced FAANG-style interviewer'}
                {option === 'bar_raiser' && 'Sharper follow-ups and stricter standards'}
                {option === 'silent' && 'Intervenes rarely, only on strong signals'}
              </span>
            </button>
          ))}
        </div>
      </article>

      {error && (
        <p className="status-banner error" role="alert">
          {error}
        </p>
      )}

      <div className="footer-actions">
        <button type="button" className="primary-button" disabled={isSubmitting} onClick={() => void startInterview()}>
          {isSubmitting ? 'Preparing interview...' : 'Start Interview'}
        </button>
      </div>
    </section>
  )
}
