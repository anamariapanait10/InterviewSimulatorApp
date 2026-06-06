import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import CodingInterviewStage from '../components/CodingInterviewStage'
import {
  createInterviewRealtimeSession,
  getInterview,
  getInterviewHint,
  getInterviewModelAnswer,
  recordPracticeDuration,
  skipInterviewQuestion,
  submitInterviewAnswer,
} from '../api'
import type { InterviewSession } from '../types'
import './InterviewFlow.css'

const PRACTICE_FLUSH_INTERVAL_MS = 15000
const SPEECH_SETTLE_MS = 5000
const INTERVIEWER_AUDIO_RESUME_DELAY_MS = 400

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function extractTranscriptText(event: Record<string, unknown>, defaultText = ''): string {
  if (typeof event.transcript === 'string' && event.transcript.trim()) {
    return event.transcript.trim()
  }
  if (typeof event.delta === 'string' && event.delta.trim()) {
    return event.delta
  }

  const item = event.item
  if (isRecord(item) && Array.isArray(item.content)) {
    for (const part of item.content) {
      if (!isRecord(part)) {
        continue
      }
      if (typeof part.transcript === 'string' && part.transcript.trim()) {
        return part.transcript.trim()
      }
      if (typeof part.text === 'string' && part.text.trim()) {
        return part.text.trim()
      }
    }
  }

  return defaultText
}

function buildReadAloudInstruction(text: string): string {
  return [
    'Read aloud exactly the text inside <verbatim> and nothing else.',
    'Do not answer it, explain it, continue it, summarize it, or add any extra words.',
    'If the text is a question, read it as a question and stop.',
    `<verbatim>${text}</verbatim>`,
  ].join('\n')
}

async function waitForIceGatheringComplete(peerConnection: RTCPeerConnection): Promise<void> {
  if (peerConnection.iceGatheringState === 'complete') {
    return
  }

  await new Promise<void>((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      peerConnection.removeEventListener('icegatheringstatechange', handleChange)
      reject(new Error('Timed out while preparing the voice connection'))
    }, 5000)

    const handleChange = () => {
      if (peerConnection.iceGatheringState !== 'complete') {
        return
      }
      window.clearTimeout(timeoutId)
      peerConnection.removeEventListener('icegatheringstatechange', handleChange)
      resolve()
    }

    peerConnection.addEventListener('icegatheringstatechange', handleChange)
  })
}

export default function InterviewRunPage() {
  const { sessionId = '' } = useParams()
  const navigate = useNavigate()
  const [session, setSession] = useState<InterviewSession | null>(null)
  const [answer, setAnswer] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [hint, setHint] = useState<string | null>(null)
  const [modelAnswer, setModelAnswer] = useState<string | null>(null)
  const [isLoadingHint, setIsLoadingHint] = useState(false)
  const [isLoadingModelAnswer, setIsLoadingModelAnswer] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [voiceFeedbackEnabled, setVoiceFeedbackEnabled] = useState(true)
  const [voiceStatus, setVoiceStatus] = useState<string | null>(null)
  const [voiceDraft, setVoiceDraft] = useState('')
  const sessionRef = useRef<InterviewSession | null>(null)
  const activeStartedAtRef = useRef<number | null>(null)
  const pendingPracticeMsRef = useRef(0)
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null)
  const dataChannelRef = useRef<RTCDataChannel | null>(null)
  const localStreamRef = useRef<MediaStream | null>(null)
  const localTrackRef = useRef<MediaStreamTrack | null>(null)
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null)
  const shouldKeepListeningRef = useRef(false)
  const speakingResponseActiveRef = useRef(false)
  const latestPromptReadRef = useRef('')
  const realtimeTranscriptionModelRef = useRef('gpt-realtime-whisper')
  const pendingSpeechRef = useRef('')
  const interimTranscriptRef = useRef('')
  const pendingSpeechTimeoutRef = useRef<number | null>(null)
  const realtimeVoiceRef = useRef('marin')

  const captureElapsedPractice = () => {
    if (activeStartedAtRef.current === null) {
      return
    }

    const now = Date.now()
    pendingPracticeMsRef.current += Math.max(now - activeStartedAtRef.current, 0)
    activeStartedAtRef.current = now
  }

  const stopPracticeTracking = () => {
    if (activeStartedAtRef.current === null) {
      return
    }

    captureElapsedPractice()
    activeStartedAtRef.current = null
  }

  const shouldTrackPractice = () => {
    const currentSession = sessionRef.current
    if (!currentSession || currentSession.is_completed) {
      return false
    }

    return document.visibilityState === 'visible' && document.hasFocus()
  }

  const syncPracticeTrackingState = () => {
    if (shouldTrackPractice()) {
      if (activeStartedAtRef.current === null) {
        activeStartedAtRef.current = Date.now()
      }
      return
    }

    stopPracticeTracking()
  }

  const flushPracticeDuration = async (options?: {
    keepalive?: boolean
    forceStop?: boolean
  }) => {
    if (options?.forceStop) {
      stopPracticeTracking()
    }

    const currentSession = sessionRef.current
    if (!currentSession || currentSession.is_completed) {
      pendingPracticeMsRef.current = 0
      return
    }

    const wholeSeconds = Math.floor(pendingPracticeMsRef.current / 1000)
    if (wholeSeconds <= 0) {
      return
    }

    pendingPracticeMsRef.current -= wholeSeconds * 1000

    try {
      await recordPracticeDuration(currentSession.id, wholeSeconds, {
        keepalive: options?.keepalive,
      })
      setSession((previous) =>
        previous && previous.id === currentSession.id
          ? {
              ...previous,
              practice_duration_seconds: (previous.practice_duration_seconds ?? 0) + wholeSeconds,
            }
          : previous,
      )
    } catch {
      pendingPracticeMsRef.current += wholeSeconds * 1000
    }
  }

  useEffect(() => {
    let cancelled = false

    const loadSession = async () => {
      setIsLoading(true)
      setError(null)

      try {
        const nextSession = await getInterview(sessionId)
        if (cancelled) {
          return
        }
        setSession(nextSession)
        setHint(null)
        setModelAnswer(null)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load interview')
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void loadSession()

    return () => {
      cancelled = true
    }
  }, [sessionId])

  useEffect(() => {
    if (session?.is_completed) {
      navigate(`/interviews/${session.id}/summary`, { replace: true })
    }
  }, [navigate, session])

  useEffect(() => {
    sessionRef.current = session
    syncPracticeTrackingState()
  }, [session])

  const hasRealtimeConnection = () => {
    return (
      peerConnectionRef.current !== null &&
      dataChannelRef.current !== null &&
      dataChannelRef.current.readyState === 'open'
    )
  }

  const setLocalMicEnabled = (enabled: boolean) => {
    if (localTrackRef.current) {
      localTrackRef.current.enabled = enabled
    }
  }

  const syncVoiceDraft = () => {
    const composed = [pendingSpeechRef.current, interimTranscriptRef.current].filter(Boolean).join(' ').trim()
    setVoiceDraft(composed)
  }

  const closeRealtimeResources = (status?: string) => {
    dataChannelRef.current?.close()
    dataChannelRef.current = null

    peerConnectionRef.current?.close()
    peerConnectionRef.current = null

    localStreamRef.current?.getTracks().forEach((track) => track.stop())
    localStreamRef.current = null
    localTrackRef.current = null

    if (remoteAudioRef.current) {
      remoteAudioRef.current.pause()
      remoteAudioRef.current.srcObject = null
    }

    speakingResponseActiveRef.current = false
    setIsListening(false)
    if (status) {
      setVoiceStatus(status)
    }
  }

  const flushVoiceTurn = async () => {
    const transcript = pendingSpeechRef.current.trim()
    if (!transcript) {
      return
    }

    pendingSpeechRef.current = ''
    interimTranscriptRef.current = ''
    if (pendingSpeechTimeoutRef.current !== null) {
      window.clearTimeout(pendingSpeechTimeoutRef.current)
      pendingSpeechTimeoutRef.current = null
    }
    setVoiceDraft('')
    setAnswer((previous) => {
      const trimmedPrevious = previous.trimEnd()
      if (!trimmedPrevious) {
        return transcript
      }
      const separator = /[\s\n]$/.test(previous) ? '' : ' '
      return `${previous}${separator}${transcript}`
    })
    setVoiceStatus('Transcribed into your answer')
  }

  const scheduleVoiceFlush = () => {
    if (pendingSpeechTimeoutRef.current !== null) {
      window.clearTimeout(pendingSpeechTimeoutRef.current)
    }
    pendingSpeechTimeoutRef.current = window.setTimeout(() => {
      pendingSpeechTimeoutRef.current = null
      void flushVoiceTurn()
    }, SPEECH_SETTLE_MS)
  }

  const stopListeningSession = (status?: string) => {
    shouldKeepListeningRef.current = false
    if (pendingSpeechTimeoutRef.current !== null) {
      window.clearTimeout(pendingSpeechTimeoutRef.current)
      pendingSpeechTimeoutRef.current = null
    }
    if (pendingSpeechRef.current.trim()) {
      void flushVoiceTurn()
    }
    closeRealtimeResources(status ?? 'Microphone stopped')
  }

  const speakPrompt = (prompt: string) => {
    const dataChannel = dataChannelRef.current
    if (!prompt.trim() || !voiceFeedbackEnabled) {
      return
    }

    if (!dataChannel || dataChannel.readyState !== 'open') {
      return
    }

    try {
      if (speakingResponseActiveRef.current) {
        dataChannel.send(JSON.stringify({ type: 'response.cancel' }))
        dataChannel.send(JSON.stringify({ type: 'output_audio_buffer.clear' }))
      }

      speakingResponseActiveRef.current = true
      setLocalMicEnabled(false)
      setVoiceStatus('Interviewer speaking')
      dataChannel.send(
        JSON.stringify({
          type: 'response.create',
          response: {
            conversation: 'none',
            output_modalities: ['audio'],
            instructions:
              'You are in strict read-aloud mode. Read the supplied text naturally and exactly as written. Do not answer the text. Do not add, remove, paraphrase, or continue anything.',
            audio: {
              output: {
                voice: realtimeVoiceRef.current,
              },
            },
            input: [
              {
                type: 'message',
                role: 'user',
                content: [
                  {
                    type: 'input_text',
                    text: buildReadAloudInstruction(prompt),
                  },
                ],
              },
            ],
          },
        }),
      )
    } catch {
      speakingResponseActiveRef.current = false
      setLocalMicEnabled(true)
      setVoiceStatus('Unable to play interviewer audio')
    }
  }

  const sendRealtimeSessionUpdate = (dataChannel: RTCDataChannel) => {
    if (dataChannel.readyState !== 'open') {
      return
    }

    dataChannel.send(
      JSON.stringify({
        type: 'session.update',
        session: {
          type: 'realtime',
          instructions:
            "You are the voice transport layer for an interview application. Continuously transcribe the candidate's speech. Do not proactively answer the candidate or ask questions on your own. The application will decide interviewer replies separately. When the application explicitly requests audio output, read the provided interviewer text naturally and keep the wording exact.",
          output_modalities: ['audio'],
          audio: {
            input: {
              turn_detection: {
                type: 'server_vad',
                create_response: false,
                interrupt_response: false,
                silence_duration_ms: 900,
                prefix_padding_ms: 300,
              },
              transcription: {
                model: realtimeTranscriptionModelRef.current,
                language: 'en',
              },
            },
            output: {
              voice: realtimeVoiceRef.current,
            },
          },
        },
      }),
    )
  }

  const handleRealtimeServerEvent = (event: Record<string, unknown>) => {
    const eventType = typeof event.type === 'string' ? event.type : ''
    switch (eventType) {
      case 'input_audio_buffer.speech_started': {
        if (!speakingResponseActiveRef.current) {
          setVoiceStatus('Listening')
        }
        break
      }
      case 'input_audio_buffer.speech_stopped': {
        if (!speakingResponseActiveRef.current) {
          setVoiceStatus('Processing speech')
        }
        break
      }
      case 'conversation.item.input_audio_transcription.delta': {
        const delta = extractTranscriptText(event)
        if (!delta) {
          break
        }
        interimTranscriptRef.current = `${interimTranscriptRef.current}${delta}`
        syncVoiceDraft()
        break
      }
      case 'conversation.item.input_audio_transcription.completed': {
        const transcript = extractTranscriptText(event, interimTranscriptRef.current).trim()
        interimTranscriptRef.current = ''
        if (!transcript) {
          syncVoiceDraft()
          break
        }
        pendingSpeechRef.current = pendingSpeechRef.current
          ? `${pendingSpeechRef.current} ${transcript}`.trim()
          : transcript
        setVoiceStatus('Listening')
        syncVoiceDraft()
        scheduleVoiceFlush()
        break
      }
      case 'response.done': {
        const response = isRecord(event.response) ? event.response : null
        const status = typeof response?.status === 'string' ? response.status : ''
        if (status && status !== 'completed' && status !== 'cancelled') {
          const statusDetails = isRecord(response?.status_details) ? response.status_details : null
          const realtimeMessage =
            isRecord(statusDetails?.error) && typeof statusDetails.error.message === 'string'
              ? statusDetails.error.message
              : `Realtime audio response ended with status: ${status}`
          setError(realtimeMessage)
        }
        break
      }
      case 'output_audio_buffer.started': {
        speakingResponseActiveRef.current = true
        setLocalMicEnabled(false)
        setVoiceStatus('Interviewer speaking')
        break
      }
      case 'output_audio_buffer.stopped':
      case 'output_audio_buffer.cleared': {
        speakingResponseActiveRef.current = false
        window.setTimeout(() => {
          if (!shouldKeepListeningRef.current) {
            return
          }
          setLocalMicEnabled(true)
          setVoiceStatus('Listening')
        }, INTERVIEWER_AUDIO_RESUME_DELAY_MS)
        break
      }
      case 'error': {
        const message =
          typeof event.error === 'string'
            ? event.error
            : isRecord(event.error) && typeof event.error.message === 'string'
              ? event.error.message
              : 'Realtime voice session failed'
        shouldKeepListeningRef.current = false
        closeRealtimeResources()
        setError(message)
        break
      }
      default:
        break
    }
  }

  const startListeningSession = async () => {
    if (!window.isSecureContext) {
      setError('Voice mode needs a secure page. Open the app on localhost or HTTPS.')
      return
    }

    if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === 'undefined') {
      setError('Realtime voice is not available in this browser.')
      return
    }

    setError(null)
    setIsListening(true)
    setVoiceStatus('Connecting voice session')

    let localStream: MediaStream | null = null
    let peerConnection: RTCPeerConnection | null = null
    let dataChannel: RTCDataChannel | null = null

    try {
      localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })

      peerConnection = new RTCPeerConnection()
      peerConnection.addTransceiver('audio', { direction: 'recvonly' })
      dataChannel = peerConnection.createDataChannel('oai-events')

      peerConnection.ontrack = (event) => {
        if (!remoteAudioRef.current) {
          return
        }
        remoteAudioRef.current.srcObject = event.streams[0]
        void remoteAudioRef.current.play().catch(() => {
          setVoiceStatus('Click Start mic again if browser blocked speaker playback')
        })
      }

      peerConnection.onconnectionstatechange = () => {
        if (peerConnection?.connectionState === 'failed' || peerConnection?.connectionState === 'disconnected') {
          shouldKeepListeningRef.current = false
          closeRealtimeResources('Voice session disconnected')
          setError('Realtime voice connection dropped. Start the mic again.')
        }
      }

      dataChannel.onopen = () => {
        setIsListening(true)
        setVoiceStatus('Listening')
        setError(null)
        sendRealtimeSessionUpdate(dataChannel as RTCDataChannel)
      }
      dataChannel.onclose = () => {
        if (!shouldKeepListeningRef.current) {
          closeRealtimeResources('Microphone stopped')
          return
        }
        shouldKeepListeningRef.current = false
        closeRealtimeResources('Voice session ended')
        setError('Realtime voice session ended. Start the mic again.')
      }
      dataChannel.onerror = () => {
        shouldKeepListeningRef.current = false
        closeRealtimeResources('Voice session error')
        setError('Realtime voice channel failed.')
      }
      dataChannel.onmessage = (messageEvent) => {
        try {
          const payload = JSON.parse(String(messageEvent.data)) as Record<string, unknown>
          handleRealtimeServerEvent(payload)
        } catch {
          // Ignore malformed realtime events.
        }
      }

      localStream.getTracks().forEach((track) => peerConnection?.addTrack(track, localStream as MediaStream))
      localStreamRef.current = localStream
      localTrackRef.current = localStream.getAudioTracks()[0] ?? null

      const offer = await peerConnection.createOffer()
      await peerConnection.setLocalDescription(offer)
      await waitForIceGatheringComplete(peerConnection)

      const answer = await createInterviewRealtimeSession(sessionId, {
        sdp: peerConnection.localDescription?.sdp ?? offer.sdp ?? '',
      })
      realtimeVoiceRef.current = answer.voice
      realtimeTranscriptionModelRef.current = answer.transcription_model
      await peerConnection.setRemoteDescription({
        type: 'answer',
        sdp: answer.sdp,
      })

      peerConnectionRef.current = peerConnection
      dataChannelRef.current = dataChannel
      if (dataChannel.readyState === 'open') {
        sendRealtimeSessionUpdate(dataChannel)
      }
    } catch (err) {
      shouldKeepListeningRef.current = false
      localStream?.getTracks().forEach((track) => track.stop())
      dataChannel?.close()
      peerConnection?.close()
      closeRealtimeResources()
      setError(err instanceof Error ? err.message : 'Unable to start realtime voice session')
    }
  }

  const toggleListening = async () => {
    if (hasRealtimeConnection() || isListening) {
      stopListeningSession('Microphone stopped')
      return
    }

    shouldKeepListeningRef.current = true
    await startListeningSession()
  }

  useEffect(() => {
    if (!session || session.is_completed) {
      return
    }

    const handleVisibilityChange = () => {
      syncPracticeTrackingState()
      if (document.visibilityState !== 'visible') {
        void flushPracticeDuration({ forceStop: true })
      }
    }

    const handleWindowFocus = () => {
      syncPracticeTrackingState()
    }

    const handleWindowBlur = () => {
      syncPracticeTrackingState()
      void flushPracticeDuration({ forceStop: true })
    }

    const handlePageHide = () => {
      void flushPracticeDuration({ forceStop: true, keepalive: true })
    }

    const intervalId = window.setInterval(() => {
      if (activeStartedAtRef.current !== null) {
        captureElapsedPractice()
      }
      void flushPracticeDuration()
    }, PRACTICE_FLUSH_INTERVAL_MS)

    document.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('focus', handleWindowFocus)
    window.addEventListener('blur', handleWindowBlur)
    window.addEventListener('pagehide', handlePageHide)
    syncPracticeTrackingState()

    return () => {
      window.clearInterval(intervalId)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      window.removeEventListener('focus', handleWindowFocus)
      window.removeEventListener('blur', handleWindowBlur)
      window.removeEventListener('pagehide', handlePageHide)
      void flushPracticeDuration({ forceStop: true, keepalive: true })
    }
  }, [session?.id, session?.is_completed])

  useEffect(() => {
    if (!session || session.current_stage === 'coding' || session.current_stage === 'completed') {
      stopListeningSession('Microphone stopped')
    }
  }, [session?.current_stage])

  useEffect(() => {
    const latestPrompt = session?.current_prompt?.content?.trim() ?? ''
    if (!latestPrompt) {
      return
    }
    if (latestPrompt === latestPromptReadRef.current) {
      return
    }
    if (!voiceFeedbackEnabled || !hasRealtimeConnection()) {
      latestPromptReadRef.current = latestPrompt
      speakPrompt(latestPrompt)
      return
    }
    latestPromptReadRef.current = latestPrompt
    speakPrompt(latestPrompt)
  }, [session?.current_prompt?.content, voiceFeedbackEnabled, isListening])

  useEffect(() => {
    return () => {
      shouldKeepListeningRef.current = false
      if (pendingSpeechTimeoutRef.current !== null) {
        window.clearTimeout(pendingSpeechTimeoutRef.current)
      }
      closeRealtimeResources()
    }
  }, [])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!session) {
      return
    }

    const trimmedAnswer = answer.trim()
    if (!trimmedAnswer) {
      setError('Write an answer before moving forward.')
      return
    }

    setError(null)
    setIsSubmitting(true)

    try {
      stopListeningSession('Microphone stopped')
      await flushPracticeDuration({ forceStop: true })
      const updated = await submitInterviewAnswer(session.id, trimmedAnswer)
      setSession(updated)
      setAnswer('')
      setHint(null)
      setModelAnswer(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save your answer')
    } finally {
      setIsSubmitting(false)
    }
  }

  const loadHint = async () => {
    if (!session) {
      return
    }

    setError(null)
    setIsLoadingHint(true)
    try {
      const response = await getInterviewHint(session.id)
      setHint(response.content)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load hint')
    } finally {
      setIsLoadingHint(false)
    }
  }

  const loadModelAnswer = async () => {
    if (!session) {
      return
    }

    setError(null)
    setIsLoadingModelAnswer(true)
    try {
      const response = await getInterviewModelAnswer(session.id)
      setModelAnswer(response.content)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load model answer')
    } finally {
      setIsLoadingModelAnswer(false)
    }
  }

  const skipQuestion = async () => {
    if (!session) {
      return
    }

    setError(null)
    setIsSubmitting(true)
    try {
      stopListeningSession('Microphone stopped')
      await flushPracticeDuration({ forceStop: true })
      const updated = await skipInterviewQuestion(session.id)
      setSession(updated)
      setAnswer('')
      setHint(null)
      setModelAnswer(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to skip this question')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (isLoading) {
    return (
      <section className="flow-card">
        <p className="section-eyebrow">Interview Runner</p>
        <h1>Loading interview...</h1>
      </section>
    )
  }

  if (!session) {
    return (
      <section className="flow-card">
        <p className="section-eyebrow">Interview Runner</p>
        <h1>Interview unavailable</h1>
        <p className="support-copy">{error ?? 'The requested interview could not be found.'}</p>
      </section>
    )
  }

  const questionStageComplete = session.current_stage === 'coding' || session.current_stage === 'completed'
  const lastHandoff =
    session.handoff_history.length > 0
      ? session.handoff_history[session.handoff_history.length - 1]
      : null
  const currentQuestion =
    questionStageComplete
      ? null
      : session.current_prompt ?? session.questions[session.current_question_index] ?? null
  const currentPromptText = !currentQuestion
    ? null
    : 'content' in currentQuestion
      ? currentQuestion.content
      : currentQuestion.prompt
  const answeredCount = session.answers.length
  const stageCount = session.questions.length + (session.coding_round ? 1 : 0)
  const completedStageCount = answeredCount + (session.is_completed && session.coding_round ? 1 : 0)
  const progressValue = stageCount === 0 ? 0 : (completedStageCount / stageCount) * 100

  return (
    <section className="runner-layout">
      <audio ref={remoteAudioRef} autoPlay playsInline hidden />
      <article className="flow-card runner-header">
        <div className="section-head">
          <div>
            <p className="section-eyebrow">Interview In Progress</p>
            <h1>{session.role_title ?? 'Mock interview'}</h1>
          </div>
          <span className="length-pill">{session.interview_length}</span>
        </div>

        <div className="progress-copy">
          <span>{answeredCount} question answers saved</span>
          <span>{Math.max(0, stageCount - completedStageCount)} steps remaining</span>
        </div>
        <div className="progress-copy">
          <span>Stage: {session.current_stage}</span>
          <span>Active agent: {session.active_agent ?? 'orchestrator'}</span>
        </div>
        {lastHandoff && (
          <p className="support-copy">
            Routed from {lastHandoff.from_agent} to {lastHandoff.to_agent}: {lastHandoff.reason}
          </p>
        )}
        <div className="progress-track" aria-hidden="true">
          <div className="progress-fill" style={{ width: `${progressValue}%` }} />
        </div>
      </article>

      {!questionStageComplete ? (
        currentQuestion ? (
        <article className="flow-card question-stage">
          <div className="question-stage-head">
            <span className={`tag ${session.current_stage}`}>{session.current_stage}</span>
            <strong>
              {session.current_prompt?.kind === 'followup' ? 'Follow-up prompt' : 'Current prompt'}
            </strong>
          </div>
          <h2>{currentPromptText}</h2>
          <p className="support-copy">
            Answer this part first. The orchestrator will decide whether to continue this stage or move forward.
          </p>

          <div className="helper-actions">
            <button
              type="button"
              className="secondary-button"
              disabled={isSubmitting || isLoadingHint || isLoadingModelAnswer}
              onClick={() => void loadHint()}
            >
              {isLoadingHint ? 'Loading hint...' : 'Give Me a Hint'}
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={isSubmitting || isLoadingHint || isLoadingModelAnswer}
              onClick={() => void loadModelAnswer()}
            >
              {isLoadingModelAnswer ? 'Loading answer...' : "I Don't Know the Answer"}
            </button>
            <button type="button" className="secondary-button" onClick={() => void toggleListening()}>
              {isListening ? 'Stop mic' : 'Start mic'}
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => setVoiceFeedbackEnabled((current) => !current)}
            >
              {voiceFeedbackEnabled ? 'Voice On' : 'Voice Off'}
            </button>
          </div>

          {voiceStatus && !error && (
            <p className="status-banner info" role="status">
              {voiceStatus}
            </p>
          )}

          {voiceDraft && (
            <article className="helper-card">
              <p className="section-eyebrow">Live transcript</p>
              <p>{voiceDraft}</p>
            </article>
          )}

          {hint && (
            <article className="helper-card">
              <p className="section-eyebrow">Hint</p>
              <p>{hint}</p>
            </article>
          )}

          {modelAnswer && (
            <article className="helper-card">
              <p className="section-eyebrow">Suggested Answer</p>
              <p>{modelAnswer}</p>
            </article>
          )}

          <form className="answer-form" onSubmit={submit}>
            <label htmlFor="answer-input" className="field-label">
              Your answer
            </label>
            <textarea
              id="answer-input"
              className="large-textarea"
              rows={10}
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder="Write your answer here..."
              disabled={isSubmitting}
            />

            {error && (
              <p className="status-banner error" role="alert">
                {error}
              </p>
            )}

            <div className="footer-actions">
              <button type="submit" className="primary-button" disabled={isSubmitting}>
                {isSubmitting
                  ? 'Saving answer...'
                  : session.current_stage === 'technical'
                    ? 'Continue Interview'
                    : 'Next Prompt'}
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={isSubmitting}
                onClick={() => void skipQuestion()}
              >
                {isSubmitting ? 'Working...' : 'Skip Question'}
              </button>
            </div>
          </form>
        </article>
        ) : (
          <article className="flow-card question-stage">
            <p className="section-eyebrow">Interview Stage</p>
            <h2>Preparing the next prompt...</h2>
            <p className="support-copy">
              The orchestrator is selecting the next step for this stage.
            </p>
          </article>
        )
      ) : (
        <CodingInterviewStage session={session} onSessionChange={setSession} />
      )}
    </section>
  )
}
