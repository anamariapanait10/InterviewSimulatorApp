import { useState } from 'react'
import type { ChangeEvent, Dispatch, SetStateAction } from 'react'
import { useNavigate } from 'react-router-dom'
import { createInterview, parseDocument } from '../api'
import './InterviewFlow.css'

type InputMode = 'text' | 'file'
type InterviewLength = 'short' | 'medium' | 'long'

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
              <p>{value.text.slice(0, 260)}{value.text.length > 260 ? '...' : ''}</p>
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
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

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
        <h1>Build the interview before the first question appears.</h1>
        <p className="support-copy">
          Load your candidate context, select the pacing, and start a deterministic interview flow with
          one question per step.
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
            <h2>Choose the pacing</h2>
          </div>
        </div>
        <div className="length-grid">
          {LENGTH_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={interviewLength === option.value ? 'length-option active' : 'length-option'}
              onClick={() => setInterviewLength(option.value)}
            >
              <strong>{option.title}</strong>
              <span>{option.description}</span>
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
