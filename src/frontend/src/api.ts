import { clearStoredAuthToken, getStoredAuthToken } from './authStorage'
import type {
  AuthResponse,
  CodingInterventionResponse,
  Company,
  CompanyKnowledgeSource,
  InterviewHelpResponse,
  InterviewHistoryItem,
  InterviewSession,
  ParsedDocumentResponse,
  RagSearchResult,
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
  target_company?: string
  company_id?: string | null
  coding_difficulty: 'easy' | 'medium' | 'hard'
  interviewer_mode: 'warm' | 'neutral' | 'bar_raiser' | 'silent'
  preferred_language: 'typescript' | 'javascript' | 'python' | 'java' | 'csharp'
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

export async function submitInterviewVoiceTurn(
  sessionId: string,
  transcriptText: string,
): Promise<InterviewSession> {
  const response = await fetch(`/api/interviews/${sessionId}/voice-turn`, {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ transcript_text: transcriptText }),
  })

  return parseJson<InterviewSession>(response)
}

export async function skipInterviewQuestion(sessionId: string): Promise<InterviewSession> {
  const response = await fetch(`/api/interviews/${sessionId}/skip`, {
    method: 'POST',
    headers: withAuthHeaders(),
  })

  return parseJson<InterviewSession>(response)
}

export async function recordPracticeDuration(
  sessionId: string,
  seconds: number,
  options?: { keepalive?: boolean },
): Promise<void> {
  const response = await fetch(`/api/interviews/${sessionId}/practice-duration`, {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ seconds }),
    keepalive: options?.keepalive ?? false,
  })

  await parseJson<InterviewSession>(response)
}

export async function finishInterview(
  sessionId: string,
  payload: {
    answer_text?: string
    code?: string
    language?: 'typescript' | 'javascript' | 'python' | 'java' | 'csharp'
    transcript_recent?: string
  },
): Promise<InterviewSession> {
  const response = await fetch(`/api/interviews/${sessionId}/finish`, {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
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

export async function appendCodingEvent(
  sessionId: string,
  payload: {
    event: {
      id: string
      type: 'code_changed' | 'candidate_spoke' | 'candidate_pause' | 'clarification_asked' | 'solution_explained'
      created_at: string
      transcript_excerpt?: string | null
      code_excerpt?: string | null
      metadata?: Record<string, unknown>
    }
    code?: string
    language?: 'typescript' | 'javascript' | 'python' | 'java' | 'csharp'
    transcript_append?: string
  },
): Promise<InterviewSession> {
  const response = await fetch(`/api/interviews/${sessionId}/coding/events`, {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  return parseJson<InterviewSession>(response)
}

export async function decideCodingIntervention(
  sessionId: string,
  payload: {
    problem_id: string
    code: string
    language: 'typescript' | 'javascript' | 'python' | 'java' | 'csharp'
    transcript_recent: string
    recent_events: Array<{
      id: string
      type: 'code_changed' | 'candidate_spoke' | 'candidate_pause' | 'clarification_asked' | 'solution_explained'
      created_at: string
      transcript_excerpt?: string | null
      code_excerpt?: string | null
      metadata?: Record<string, unknown>
    }>
    elapsed_time_seconds: number
  },
): Promise<CodingInterventionResponse> {
  const response = await fetch(`/api/interviews/${sessionId}/coding/intervention`, {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  return parseJson<CodingInterventionResponse>(response)
}

export async function createCodingRealtimeSession(
  sessionId: string,
  payload: {
    sdp: string
    voice?: string
  },
): Promise<{
  sdp: string
  model: string
  voice: string
  transcription_model: string
}> {
  const response = await fetch(`/api/interviews/${sessionId}/coding/realtime/session`, {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  return parseJson(response)
}

export async function createInterviewRealtimeSession(
  sessionId: string,
  payload: {
    sdp: string
    voice?: string
  },
): Promise<{
  sdp: string
  model: string
  voice: string
  transcription_model: string
}> {
  const response = await fetch(`/api/interviews/${sessionId}/realtime/session`, {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  return parseJson(response)
}


export async function listCompanies(): Promise<Company[]> {
  const response = await fetch('/api/companies', {
    headers: withAuthHeaders(),
  })
  return parseJson<Company[]>(response)
}

export async function createCompany(payload: {
  name: string
  description?: string
  website?: string
}): Promise<Company> {
  const response = await fetch('/api/companies', {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  return parseJson<Company>(response)
}

export async function getCompany(companyId: string): Promise<Company> {
  const response = await fetch(`/api/companies/${companyId}`, {
    headers: withAuthHeaders(),
  })
  return parseJson<Company>(response)
}

export async function listCompanyKnowledge(companyId: string): Promise<CompanyKnowledgeSource[]> {
  const response = await fetch(`/api/companies/${companyId}/knowledge`, {
    headers: withAuthHeaders(),
  })
  return parseJson<CompanyKnowledgeSource[]>(response)
}

export async function addCompanyKnowledgeText(
  companyId: string,
  payload: {
    title: string
    content: string
    source_type: 'manual' | 'official_page' | 'job_description' | 'engineering_blog' | 'interview_guide'
    metadata: {
      role?: string | null
      category?: string | null
      url?: string | null
    }
  },
): Promise<CompanyKnowledgeSource> {
  const response = await fetch(`/api/companies/${companyId}/knowledge/text`, {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  return parseJson<CompanyKnowledgeSource>(response)
}

export async function uploadCompanyKnowledge(
  companyId: string,
  payload: {
    file: File
    title?: string
    source_type: 'manual' | 'official_page' | 'job_description' | 'engineering_blog' | 'interview_guide'
    metadata?: {
      role?: string | null
      category?: string | null
      url?: string | null
    }
  },
): Promise<CompanyKnowledgeSource> {
  const formData = new FormData()
  formData.append('file', payload.file)
  formData.append('source_type', payload.source_type)
  if (payload.title) {
    formData.append('title', payload.title)
  }
  if (payload.metadata) {
    formData.append('metadata_json', JSON.stringify(payload.metadata))
  }

  const response = await fetch(`/api/companies/${companyId}/knowledge/upload`, {
    method: 'POST',
    headers: withAuthHeaders(),
    body: formData,
  })
  return parseJson<CompanyKnowledgeSource>(response)
}

export async function updateCompanyKnowledge(
  companyId: string,
  sourceId: string,
  payload: {
    title: string
    content: string
    source_type: 'manual' | 'official_page' | 'job_description' | 'engineering_blog' | 'interview_guide'
    metadata: {
      role?: string | null
      category?: string | null
      url?: string | null
    }
  },
): Promise<CompanyKnowledgeSource> {
  const response = await fetch(`/api/companies/${companyId}/knowledge/${sourceId}`, {
    method: 'PUT',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  return parseJson<CompanyKnowledgeSource>(response)
}

export async function deleteCompanyKnowledge(companyId: string, sourceId: string): Promise<void> {
  const response = await fetch(`/api/companies/${companyId}/knowledge/${sourceId}`, {
    method: 'DELETE',
    headers: withAuthHeaders(),
  })
  await parseJson<{ ok: boolean }>(response)
}

export async function searchCompanyKnowledge(
  companyId: string,
  payload: { query: string; top_k?: number },
): Promise<RagSearchResult[]> {
  const response = await fetch(`/api/companies/${companyId}/rag/search`, {
    method: 'POST',
    headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  return parseJson<RagSearchResult[]>(response)
}
