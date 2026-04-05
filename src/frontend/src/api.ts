import type { InterviewHistoryItem, InterviewSession, ParsedDocumentResponse } from './types'

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) {
        detail = payload.detail
      }
    } catch {
      // Ignore malformed error payloads and fall back to status text.
    }
    throw new Error(detail)
  }

  return (await response.json()) as T
}

export async function parseDocument(file: File): Promise<ParsedDocumentResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch('/api/interviews/parse-document', {
    method: 'POST',
    body: formData,
  })

  return parseJson<ParsedDocumentResponse>(response)
}

export async function createInterview(payload: {
  resume_text: string
  job_description_text: string
  interview_length: 'short' | 'medium' | 'long'
}): Promise<InterviewSession> {
  const response = await fetch('/api/interviews', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  return parseJson<InterviewSession>(response)
}

export async function getInterview(sessionId: string): Promise<InterviewSession> {
  const response = await fetch(`/api/interviews/${sessionId}`)
  return parseJson<InterviewSession>(response)
}

export async function listInterviewHistory(): Promise<InterviewHistoryItem[]> {
  const response = await fetch('/api/interviews')
  return parseJson<InterviewHistoryItem[]>(response)
}

export async function submitInterviewAnswer(
  sessionId: string,
  answerText: string,
): Promise<InterviewSession> {
  const response = await fetch(`/api/interviews/${sessionId}/answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer_text: answerText }),
  })

  return parseJson<InterviewSession>(response)
}

export async function finishInterview(sessionId: string, answerText: string): Promise<InterviewSession> {
  const response = await fetch(`/api/interviews/${sessionId}/finish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer_text: answerText }),
  })

  return parseJson<InterviewSession>(response)
}
