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

export interface InterviewRuntimeTurn {
  id: string
  stage: 'behavioral' | 'technical' | 'coding' | 'completed'
  role: 'candidate' | 'interviewer' | 'system'
  agent_name: string | null
  kind:
    | 'question'
    | 'followup'
    | 'answer'
    | 'hint'
    | 'model_answer'
    | 'clarification'
    | 'coding_reply'
    | 'intervention'
    | 'transition'
  content: string
  metadata: Record<string, unknown>
  created_at: string
}

export interface InterviewHandoffTrace {
  from_agent: string
  to_agent: string
  stage: 'behavioral' | 'technical' | 'coding' | 'completed'
  reason: string
  created_at: string
}

export interface InterviewDecisionTrace {
  active_agent: string
  decision_type: string
  summary: string
  stage: 'behavioral' | 'technical' | 'coding' | 'completed'
  created_at: string
}

export interface InterviewSupportEntry {
  mode: 'hint' | 'model_answer'
  stage: 'behavioral' | 'technical' | 'coding'
  question_id: string | null
  content: string
  created_at: string
}

export interface InterviewBlueprint {
  role_title: string
  behavioral_goal: string
  technical_goal: string
  behavioral_target_questions: number
  technical_target_questions: number
  target_company: string | null
  focus_areas: string[]
}

export interface InterviewEvaluation {
  behavioral_score: number
  technical_score: number
  coding_score: number
  communication_score: number
  overall_score: number
  job_match_score: number | null
  behavioral_feedback: string
  technical_feedback: string
  coding_feedback: string
  communication_feedback: string
  job_match_feedback: string | null
  summary: string
  strengths: string[]
  improvements: string[]
  matched_requirements: string[]
  missing_requirements: string[]
  hire_recommendation: string
  recommendation: string
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
  current_mode?: 'reading' | 'discussion' | 'implementation' | 'select_problem' | null
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
  job_match_score: number | null
  job_match_feedback: string | null
  matched_requirements: string[]
  missing_requirements: string[]
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
  company_context?: string | null
  resume_text: string | null
  job_description_text: string | null
  interview_length: 'short' | 'medium' | 'long' | null
  role_title: string | null
  target_company: string | null
  voice_enabled: boolean
  preferred_language?: 'typescript' | 'javascript' | 'python' | 'java' | 'csharp'
  coding_difficulty?: 'easy' | 'medium' | 'hard'
  interviewer_mode?: 'warm' | 'neutral' | 'bar_raiser' | 'silent'
  current_stage: 'behavioral' | 'technical' | 'coding' | 'completed'
  active_agent: string | null
  interview_blueprint: InterviewBlueprint | null
  current_prompt: InterviewRuntimeTurn | null
  turn_log: InterviewRuntimeTurn[]
  handoff_history: InterviewHandoffTrace[]
  decision_trace: InterviewDecisionTrace[]
  support_history: InterviewSupportEntry[]
  questions: InterviewQuestion[]
  answers: InterviewAnswer[]
  current_question_index: number
  coding_round: CodingInterviewRound | null
  evaluation: InterviewEvaluation | null
  score: number | null
  report: InterviewReport | null
  is_completed: boolean
  practice_duration_seconds: number | null
  focus_loss_count?: number
  focus_loss_seconds?: number
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
  hint_count: number
  model_answer_count: number
  used_help: boolean
  independent_answer_ratio: number | null
  focus_loss_count: number
  focus_loss_seconds: number
  created_at: string
  completed_at: string | null
}

export interface ParsedDocumentResponse {
  file_name: string
  extracted_text: string
}

export interface ParsedJobUrlResponse {
  source_url: string
  title: string
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
