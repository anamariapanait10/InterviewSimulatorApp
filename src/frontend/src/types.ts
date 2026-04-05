export interface InterviewQuestion {
  id: string
  order: number
  category: 'behavioral' | 'technical'
  prompt: string
}

export interface InterviewAnswer {
  question_id: string
  question_order: number
  category: 'behavioral' | 'technical'
  question_prompt: string
  answer_text: string
  submitted_at: string
}

export interface InterviewQuestionFeedback {
  question_id: string
  score: number
  feedback: string
}

export interface InterviewReport {
  summary: string
  strengths: string[]
  improvements: string[]
  behavioral_feedback: string
  technical_feedback: string
  communication_feedback: string
  recommendation: string
  question_feedback: InterviewQuestionFeedback[]
}

export interface InterviewSession {
  id: string
  resume_text: string | null
  job_description_text: string | null
  interview_length: 'short' | 'medium' | 'long' | null
  role_title: string | null
  questions: InterviewQuestion[]
  answers: InterviewAnswer[]
  current_question_index: number
  score: number | null
  report: InterviewReport | null
  is_completed: boolean
  created_at: string
  completed_at: string | null
}

export interface InterviewHistoryItem {
  id: string
  role_title: string
  interview_length: 'short' | 'medium' | 'long' | null
  question_count: number
  answered_count: number
  is_completed: boolean
  score: number | null
  created_at: string
  completed_at: string | null
}

export interface ParsedDocumentResponse {
  file_name: string
  extracted_text: string
}
