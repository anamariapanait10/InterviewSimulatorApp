import { useEffect, useState } from 'react'
import type { ChangeEvent, Dispatch, SetStateAction } from 'react'
import { useNavigate } from 'react-router-dom'
import { createInterview, listCompanies, parseDocument } from '../api'
import type { Company } from '../types'
import './InterviewFlow.css'

type InputMode = 'text' | 'file'
type InterviewLength = 'short' | 'medium' | 'long'
type CodingDifficulty = 'easy' | 'medium' | 'hard'
type InterviewerMode = 'warm' | 'neutral' | 'bar_raiser' | 'silent'
type PreferredLanguage = 'typescript' | 'javascript' | 'python' | 'java' | 'csharp'

interface ParsedSourceState {
  mode: InputMode
  text: string
  fileName: string | null
  isParsing: boolean
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

function SourceCard(props: {
  id: string
  label: string
  value: ParsedSourceState
  onModeChange: (mode: InputMode) => void
  onTextChange: (text: string) => void
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void
}) {
  const { id, label, value, onModeChange, onTextChange, onFileChange } = props

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
      ) : (
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
  })
  const [jobDescription, setJobDescription] = useState<ParsedSourceState>({
    mode: 'text',
    text: '',
    fileName: null,
    isParsing: false,
  })
  const [interviewLength, setInterviewLength] = useState<InterviewLength>('medium')
  const [targetCompany, setTargetCompany] = useState('')
  const [companies, setCompanies] = useState<Company[]>([])
  const [selectedCompanyId, setSelectedCompanyId] = useState('')
  const [codingDifficulty, setCodingDifficulty] = useState<CodingDifficulty>('medium')
  const [interviewerMode, setInterviewerMode] = useState<InterviewerMode>('neutral')
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

  const selectedCompany = companies.find((company) => company.id === selectedCompanyId) ?? null

  const handleFileParse = async (
    file: File | undefined,
    setter: Dispatch<SetStateAction<ParsedSourceState>>,
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
      }))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to parse document'
      setError(message)
      setter((previous) => ({ ...previous, isParsing: false }))
    }
  }

  const startInterview = async () => {
    const resumeText = resume.text.trim()
    const jobDescriptionText = jobDescription.text.trim()

    if (!resumeText || !jobDescriptionText) {
      setError('Both the CV and the job description are required before starting the interview.')
      return
    }

    setError(null)
    setIsSubmitting(true)

    try {
      const session = await createInterview({
        resume_text: resumeText,
        job_description_text: jobDescriptionText,
        interview_length: interviewLength,
        target_company: targetCompany.trim() || selectedCompany?.name || undefined,
        company_id: selectedCompanyId || undefined,
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
          onTextChange={(text) => setResume((previous) => ({ ...previous, text, fileName: null }))}
          onFileChange={(event) => void handleFileParse(event.target.files?.[0], setResume)}
        />

        <SourceCard
          id="job-description-input"
          label="Job Description"
          value={jobDescription}
          onModeChange={(mode) => setJobDescription((previous) => ({ ...previous, mode }))}
          onTextChange={(text) =>
            setJobDescription((previous) => ({ ...previous, text, fileName: null }))
          }
          onFileChange={(event) => void handleFileParse(event.target.files?.[0], setJobDescription)}
        />
      </div>

      <article className="flow-card">
        <div className="section-head">
          <div>
            <p className="section-eyebrow">Interview Length</p>
            <h2>Choose the interview length</h2>
          </div>
        </div>
        <div className="length-grid mt-2">
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
            <label htmlFor="company-select" className="field-label">
              Company knowledge workspace
            </label>
            <select
              id="company-select"
              className="text-input"
              value={selectedCompanyId}
              onChange={(event) => setSelectedCompanyId(event.target.value)}
            >
              <option value="">No company knowledge selected</option>
              {companies.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.name}
                </option>
              ))}
            </select>
            <p className="support-copy mt-2">
              Select a saved company to inject indexed interview knowledge into question generation.
            </p>

            <label htmlFor="company-input" className="field-label">
              Coding round target company
            </label>
            <input
              id="company-input"
              className="text-input"
              value={targetCompany}
              onChange={(event) => setTargetCompany(event.target.value)}
              placeholder={selectedCompany?.name ?? 'Google, Meta, Amazon...'}
            />
            <p className="support-copy mt-2">
              Leave this blank to reuse the selected company above, or type a custom company for coding-bank matching.
            </p>
          </div>

          <div>
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

        <div className="length-grid mt-2">
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

        <div className="length-grid mt-2">
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
