import { clearStoredAuthToken, getStoredAuthToken } from './authStorage'
import type {
  AuthResponse,
  InterviewHelpResponse,
  InterviewHistoryItem,
  InterviewSession,
  ParsedDocumentResponse,
  User,
} from './types'

class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

function withAuthHeaders(headers: HeadersInit = {}): HeadersInit {
  const token = getStoredAuthToken()
  if (!token) {
    return headers
  }

  return {
    ...headers,
    Authorization: `Bearer ${token}`,
  }
}

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

    if (response.status === 401) {
      clearStoredAuthToken()
    }

    throw new ApiError(detail, response.status)
  }

  return (await response.json()) as T
}

export { ApiError }

export async function registerUser(email: string, password: string): Promise<AuthResponse> {
  const response = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  return parseJson<AuthResponse>(response)
}

export async function loginUser(email: string, password: string): Promise<AuthResponse> {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  return parseJson<AuthResponse>(response)
}

export async function getCurrentUser(): Promise<User> {
  const response = await fetch('/api/auth/me', {
    headers: withAuthHeaders(),
  })
  return parseJson<User>(response)
}

export async function logoutUser(): Promise<void> {
  const response = await fetch('/api/auth/logout', {
    method: 'POST',
    headers: withAuthHeaders(),
  })
  await parseJson<{ ok: boolean }>(response)
}

export async function parseDocument(file: File): Promise<ParsedDocumentResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch('/api/interviews/parse-document', {
    method: 'POST',
    headers: withAuthHeaders(),
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
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })

  return parseJson<InterviewSession>(response)
}

export async function getInterview(sessionId: string): Promise<InterviewSession> {
  const response = await fetch(`/api/interviews/${sessionId}`, {
    headers: withAuthHeaders(),
  })
  return parseJson<InterviewSession>(response)
}

export async function listInterviewHistory(): Promise<InterviewHistoryItem[]> {
  const response = await fetch('/api/interviews', {
    headers: withAuthHeaders(),
  })
  return parseJson<InterviewHistoryItem[]>(response)
}

export async function deleteInterview(sessionId: string): Promise<void> {
  const response = await fetch(`/api/interviews/${sessionId}`, {
    method: 'DELETE',
    headers: withAuthHeaders(),
  })
  await parseJson<{ ok: boolean }>(response)
}

export async function submitInterviewAnswer(
  sessionId: string,
  answerText: string,
): Promise<InterviewSession> {
  const response = await fetch(`/api/interviews/${sessionId}/answer`, {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ answer_text: answerText }),
  })

  return parseJson<InterviewSession>(response)
}

export async function finishInterview(sessionId: string, answerText: string): Promise<InterviewSession> {
  const response = await fetch(`/api/interviews/${sessionId}/finish`, {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ answer_text: answerText }),
  })

  return parseJson<InterviewSession>(response)
}

export async function getInterviewHint(sessionId: string): Promise<InterviewHelpResponse> {
  const response = await fetch(`/api/interviews/${sessionId}/hint`, {
    method: 'POST',
    headers: withAuthHeaders(),
  })
  return parseJson<InterviewHelpResponse>(response)
}

export async function getInterviewModelAnswer(sessionId: string): Promise<InterviewHelpResponse> {
  const response = await fetch(`/api/interviews/${sessionId}/model-answer`, {
    method: 'POST',
    headers: withAuthHeaders(),
  })
  return parseJson<InterviewHelpResponse>(response)
}
