export interface User {
  id: string
  email: string
  created_at: string
}

export interface AuthResponse {
  token: string
  user: User
}

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

export interface CodingProblemExample {
  input: string
  output: string
  explanation: string | null
}

export interface CodingProblem {
  id: string
  title: string
  company: string
  difficulty: 'easy' | 'medium' | 'hard'
  prompt: string
  constraints: string[]
  examples: CodingProblemExample[]
  starter_code: Record<string, string>
  expected_topics: string[]
  style_tags: string[]
  complexity_target: string | null
  edge_case_hints: string[]
}

export interface CodingInterviewEvent {
  id: string
  type:
    | 'code_changed'
    | 'candidate_spoke'
    | 'candidate_pause'
    | 'clarification_asked'
    | 'solution_explained'
  created_at: string
  transcript_excerpt: string | null
  code_excerpt: string | null
  metadata: Record<string, unknown>
}

export interface CodingIntervention {
  question: string
  reason: string
  severity: 'low' | 'medium' | 'high' | 'none'
  created_at: string
  prompt_key: string | null
}

export interface CodingConversationTurn {
  role: 'candidate' | 'interviewer'
  content: string
  created_at: string
  kind: 'message' | 'reply' | 'intervention' | 'opening'
  source_event_type: string | null
  severity: 'low' | 'medium' | 'high' | 'none' | null
}

export interface CodingEvaluation {
  communication: number
  problem_solving: number
  coding: number
  complexity_analysis: number
  debugging: number
  edge_cases: number
  overall_score: number
  hire_recommendation: string
  summary: string
  strengths: string[]
  concerns: string[]
}

export interface CodingInterviewRound {
  enabled: boolean
  target_company: string | null
  matched_company: string | null
  selection_strategy: string
  interviewer_mode: 'warm' | 'neutral' | 'bar_raiser' | 'silent'
  difficulty: 'easy' | 'medium' | 'hard'
  problem: CodingProblem | null
  language: 'typescript' | 'javascript' | 'python' | 'java' | 'csharp'
  editor_mode: 'monaco' | 'plain'
  current_code: string
  transcript: string
  interviewer_prompt: string | null
  event_log: CodingInterviewEvent[]
  conversation: CodingConversationTurn[]
  interventions: CodingIntervention[]
  cooldown_seconds: number
  last_intervention_at: string | null
  latest_reason: string | null
  evaluation: CodingEvaluation | null
  started_at: string
  completed_at: string | null
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
  coding_feedback: string
  coding_evaluation: CodingEvaluation | null
  hire_recommendation: string
}

export interface InterviewSession {
  id: string
  user_id: string | null
  company_id: string | null
  company_name: string | null
  resume_text: string | null
  job_description_text: string | null
  interview_length: 'short' | 'medium' | 'long' | null
  role_title: string | null
  target_company: string | null
  questions: InterviewQuestion[]
  answers: InterviewAnswer[]
  current_question_index: number
  coding_round: CodingInterviewRound | null
  score: number | null
  report: InterviewReport | null
  is_completed: boolean
  practice_duration_seconds: number | null
  created_at: string
  completed_at: string | null
}

export interface InterviewHistoryItem {
  id: string
  role_title: string
  interview_length: 'short' | 'medium' | 'long' | null
  target_company: string | null
  company_id: string | null
  company_name: string | null
  question_count: number
  answered_count: number
  is_completed: boolean
  score: number | null
  practice_duration_seconds: number | null
  created_at: string
  completed_at: string | null
}

export interface ParsedDocumentResponse {
  file_name: string
  extracted_text: string
}

export interface InterviewHelpResponse {
  question_id: string
  content: string
}

export interface CodingInterventionResponse {
  should_interrupt: boolean
  reason: string | null
  question: string | null
  severity: 'low' | 'medium' | 'high' | 'none'
  reply: string | null
  coding_round: CodingInterviewRound | null
}


export interface Company {
  id: string
  name: string
  description: string | null
  website: string | null
  created_at: string
}

export interface CompanyKnowledgeMetadata {
  role?: string | null
  category?: string | null
  url?: string | null
}

export interface CompanyKnowledgeSource {
  id: string
  company_id: string
  title: string
  source_type: 'manual' | 'official_page' | 'job_description' | 'engineering_blog' | 'interview_guide'
  content: string
  metadata: CompanyKnowledgeMetadata
  created_at: string
}

export interface RagSearchResult {
  content: string
  metadata: Record<string, string>
  distance: number | null
}
