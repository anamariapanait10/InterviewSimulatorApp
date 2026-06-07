import { useEffect, useMemo, useRef, useState } from 'react'
import CodeEditor from './CodeEditor'
import { createCodingRealtimeSession, decideCodingIntervention, finishInterview, resumeCodingStage } from '../api'
import type { CodingConversationTurn, CodingInterviewEvent, InterviewSession } from '../types'

interface CodingInterviewStageProps {
  session: InterviewSession
  onSessionChange: (session: InterviewSession) => void
}

const LONG_PAUSE_THRESHOLD_MS = 45_000
const SPEECH_SETTLE_MS = 4_500
const INTERVIEWER_AUDIO_RESUME_DELAY_MS = 400
const READING_GRACE_PERIOD_MS = 10_000
const INTERVIEWER_SPEAKING_WATCHDOG_MS = 12_000

function buildEvent(
  type: CodingInterviewEvent['type'],
  values?: Partial<Omit<CodingInterviewEvent, 'id' | 'type' | 'created_at'>>,
): CodingInterviewEvent {
  return {
    id: crypto.randomUUID(),
    type,
    created_at: new Date().toISOString(),
    transcript_excerpt: values?.transcript_excerpt ?? null,
    code_excerpt: values?.code_excerpt ?? null,
    metadata: values?.metadata ?? {},
  }
}

function formatReason(reason: string | null): string {
  if (!reason) {
    return 'monitoring'
  }
  return reason.replace(/_/g, ' ')
}

function looksLikeClarification(transcript: string): boolean {
  return /clarify|clarification|constraint|allowed|guaranteed|help me understand|understand (the )?(problem|prompt|statement)|problem statement|explain (the )?(problem|prompt|statement)|restate the problem|walk me through (the )?(problem|prompt)|what does .* mean|enunt/i.test(
    transcript,
  )
}

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

function buildCandidateConversationTurn(
  content: string,
  sourceEventType: CodingInterviewEvent['type'],
): CodingConversationTurn {
  return {
    role: 'candidate',
    content,
    created_at: new Date().toISOString(),
    kind: 'message',
    source_event_type: sourceEventType,
    severity: null,
  }
}

function buildReadAloudInstruction(text: string): string {
  return [
    'Read aloud exactly the text inside <verbatim> and nothing else.',
    'Do not answer it, explain it, continue it, summarize it, or add any extra words.',
    'If the text is a question, read it as a question and stop.',
    `<verbatim>${text}</verbatim>`,
  ].join('\n')
}

function buildProblemReadAloudText(session: InterviewSession): string {
  const problem = session.coding_round?.problem
  if (!problem) {
    return ''
  }

  return [`Coding problem: ${problem.title}.`, problem.prompt].filter(Boolean).join(' ')
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

export default function CodingInterviewStage({
  session,
  onSessionChange,
}: CodingInterviewStageProps) {
  const codingRound = session.coding_round
  const [code, setCode] = useState(codingRound?.current_code ?? '')
  const [language, setLanguage] = useState(codingRound?.language ?? 'typescript')
  const [speechDraft, setSpeechDraft] = useState('')
  const [isWorking, setIsWorking] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [voiceStatus, setVoiceStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const peerConnectionRef = useRef<RTCPeerConnection | null>(null)
  const dataChannelRef = useRef<RTCDataChannel | null>(null)
  const localStreamRef = useRef<MediaStream | null>(null)
  const localTrackRef = useRef<MediaStreamTrack | null>(null)
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null)
  const assistantThreadRef = useRef<HTMLDivElement | null>(null)
  const realtimeVoiceRef = useRef('marin')
  const realtimeTranscriptionModelRef = useRef('gpt-realtime-whisper')
  const shouldKeepListeningRef = useRef(false)
  const autoVoiceStartedRef = useRef<string | null>(null)
  const readingPromptTimerRef = useRef<number | null>(null)
  const speakingResponseActiveRef = useRef(false)
  const micStreamingRef = useRef(false)
  const latestSpokenTurnRef = useRef('')
  const lastActivityAtRef = useRef(Date.now())
  const lastPauseAtRef = useRef(0)
  const lastCodeSentRef = useRef(code)
  const localCodeRef = useRef(code)
  const syncedProblemIdRef = useRef<string | null>(codingRound?.problem?.id ?? null)
  const pendingSpeechRef = useRef('')
  const pendingSpeechTypeRef = useRef<CodingInterviewEvent['type']>('candidate_spoke')
  const pendingSpeechTimeoutRef = useRef<number | null>(null)
  const interimTranscriptRef = useRef('')
  const interviewerSpeakingWatchdogRef = useRef<number | null>(null)
  const problemReadAloudRef = useRef<string | null>(null)
  const pendingSpeechResumeMarkerRef = useRef(false)
  const isVoiceEnabled = session.voice_enabled !== false

  useEffect(() => {
    const incomingCode = codingRound?.current_code ?? ''
    const incomingLanguage = codingRound?.language ?? 'typescript'
    const incomingProblemId = codingRound?.problem?.id ?? null

    setLanguage(incomingLanguage)

    if (incomingProblemId !== syncedProblemIdRef.current) {
      syncedProblemIdRef.current = incomingProblemId
      localCodeRef.current = incomingCode
      lastCodeSentRef.current = incomingCode
      setCode(incomingCode)
      return
    }

    if (incomingCode === localCodeRef.current) {
      lastCodeSentRef.current = incomingCode
      return
    }

    if (incomingCode !== lastCodeSentRef.current) {
      logRealtimeDebugEvent(
        'editor.ignore_stale_server_code',
        `incoming=${incomingCode.length}; lastSent=${lastCodeSentRef.current.length}; local=${localCodeRef.current.length}`,
      )
      return
    }

    if (localCodeRef.current !== lastCodeSentRef.current) {
      return
    }

    localCodeRef.current = incomingCode
    lastCodeSentRef.current = incomingCode
    setCode(incomingCode)
  }, [codingRound?.current_code, codingRound?.language, codingRound?.problem?.id])

  const startedAtMs = useMemo(() => {
    if (!codingRound) {
      return Date.now()
    }
    return new Date(codingRound.started_at).getTime()
  }, [codingRound])

  const syncDraftFromRealtimeBuffer = () => {
    const composed = [pendingSpeechRef.current, interimTranscriptRef.current].filter(Boolean).join(' ').trim()
    setSpeechDraft(composed)
  }

  const hasRealtimeConnection = () => {
    return (
      peerConnectionRef.current !== null &&
      dataChannelRef.current !== null &&
      dataChannelRef.current.readyState === 'open'
    )
  }

  const setLocalMicEnabled = (enabled: boolean) => {
    logRealtimeDebugEvent('rtc.mic_track', enabled ? 'enabled' : 'disabled')
    if (localTrackRef.current) {
      localTrackRef.current.enabled = enabled
    }
    localStreamRef.current?.getAudioTracks().forEach((track) => {
      track.enabled = enabled
    })
  }

  const clearReadingPromptTimer = () => {
    if (readingPromptTimerRef.current !== null) {
      window.clearTimeout(readingPromptTimerRef.current)
      readingPromptTimerRef.current = null
    }
  }

  const clearInterviewerSpeakingWatchdog = () => {
    if (interviewerSpeakingWatchdogRef.current !== null) {
      window.clearTimeout(interviewerSpeakingWatchdogRef.current)
      interviewerSpeakingWatchdogRef.current = null
    }
  }

  const logRealtimeDebugEvent = (type: string, details?: string) => {
    const timestamp = new Date().toISOString()
    if (details) {
      console.log(`[coding-voice][${timestamp}] ${type}: ${details}`)
      return
    }
    console.log(`[coding-voice][${timestamp}] ${type}`)
  }

  const updateVoiceStatus = (nextStatus: string | null) => {
    setVoiceStatus(nextStatus)
    logRealtimeDebugEvent('ui.voice_status', nextStatus ?? 'null')
  }

  const updateListeningState = (nextListening: boolean) => {
    setIsListening(nextListening)
    logRealtimeDebugEvent('ui.is_listening', nextListening ? 'true' : 'false')
  }

  const restoreAfterInterviewerSpeech = () => {
    clearInterviewerSpeakingWatchdog()
    speakingResponseActiveRef.current = false
    lastActivityAtRef.current = Date.now()
    window.setTimeout(() => {
      const canResume =
        shouldKeepListeningRef.current ||
        (dataChannelRef.current !== null && dataChannelRef.current.readyState === 'open')
      logRealtimeDebugEvent(
        'ui.restore_after_speech_attempt',
        `canResume=${canResume}; keep=${shouldKeepListeningRef.current}; mic=${micStreamingRef.current}; channel=${dataChannelRef.current?.readyState ?? 'none'}`,
      )
      if (!canResume) {
        return
      }
      setLocalMicEnabled(micStreamingRef.current)
      updateListeningState(micStreamingRef.current)
      updateVoiceStatus(micStreamingRef.current ? 'Listening' : 'Voice ready')
      logRealtimeDebugEvent('ui.restore_after_speech_applied', micStreamingRef.current ? 'listening' : 'voice_ready')
    }, INTERVIEWER_AUDIO_RESUME_DELAY_MS)
  }

  const armInterviewerSpeakingWatchdog = () => {
    clearInterviewerSpeakingWatchdog()
    logRealtimeDebugEvent('ui.speaking_watchdog_armed')
    interviewerSpeakingWatchdogRef.current = window.setTimeout(() => {
      interviewerSpeakingWatchdogRef.current = null
      if (!speakingResponseActiveRef.current) {
        return
      }
      logRealtimeDebugEvent('ui.speaking_watchdog_fired')
      restoreAfterInterviewerSpeech()
    }, INTERVIEWER_SPEAKING_WATCHDOG_MS)
  }

  const sendEvent = async (
    event: CodingInterviewEvent,
    transcriptRecent = event.transcript_excerpt ?? '',
  ) => {
    if (!codingRound?.problem) {
      return
    }

    const currentCode = localCodeRef.current

    if (transcriptRecent.trim()) {
      clearReadingPromptTimer()
    }

    setIsWorking(true)
    setError(null)
    const startedAt = performance.now()
    logRealtimeDebugEvent(
      'app.send_event.start',
      `type=${event.type}; transcriptChars=${transcriptRecent.length}; codeChars=${currentCode.length}`,
    )
    try {
      const response = await decideCodingIntervention(session.id, {
        problem_id: codingRound.problem.id,
        code: currentCode,
        language,
        transcript_recent: transcriptRecent,
        recent_events: [event],
        elapsed_time_seconds: Math.max(0, Math.floor((Date.now() - startedAtMs) / 1000)),
      })

      if (response.coding_round) {
        onSessionChange({ ...session, coding_round: response.coding_round })
      }
      if (response.reply) {
        setVoiceStatus(hasRealtimeConnection() ? 'Interviewer replied' : 'Interviewer replied in chat')
      }
      logRealtimeDebugEvent(
        'app.send_event.done',
        `type=${event.type}; durationMs=${Math.round(performance.now() - startedAt)}; hasReply=${response.reply ? 'true' : 'false'}`,
      )
    } catch (err) {
      logRealtimeDebugEvent(
        'app.send_event.error',
        `type=${event.type}; durationMs=${Math.round(performance.now() - startedAt)}; message=${err instanceof Error ? err.message : 'unknown error'}`,
      )
      setError(err instanceof Error ? err.message : 'Unable to update the coding round')
    } finally {
      setIsWorking(false)
    }
  }

  const flushPendingSpeech = async () => {
    const transcript = pendingSpeechRef.current.trim()
    if (!transcript) {
      return
    }

    const eventType = pendingSpeechTypeRef.current
    logRealtimeDebugEvent('speech.flush.start', `type=${eventType}; transcriptChars=${transcript.length}`)
    pendingSpeechRef.current = ''
    pendingSpeechTypeRef.current = 'candidate_spoke'
    pendingSpeechResumeMarkerRef.current = false
    interimTranscriptRef.current = ''
    if (pendingSpeechTimeoutRef.current !== null) {
      window.clearTimeout(pendingSpeechTimeoutRef.current)
      pendingSpeechTimeoutRef.current = null
    }

    setSpeechDraft(transcript)
    await sendEvent(
      buildEvent(eventType, {
        transcript_excerpt: transcript,
        code_excerpt: localCodeRef.current.slice(-600),
      }),
      transcript,
    )
    setSpeechDraft('')
  }

  const schedulePendingSpeechFlush = () => {
    if (pendingSpeechTimeoutRef.current !== null) {
      window.clearTimeout(pendingSpeechTimeoutRef.current)
    }

    pendingSpeechResumeMarkerRef.current = false
    logRealtimeDebugEvent('speech.flush.scheduled', `delayMs=${SPEECH_SETTLE_MS}`)
    pendingSpeechTimeoutRef.current = window.setTimeout(() => {
      pendingSpeechTimeoutRef.current = null
      pendingSpeechResumeMarkerRef.current = false
      logRealtimeDebugEvent('speech.flush.fire')
      void flushPendingSpeech()
    }, SPEECH_SETTLE_MS)
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
    clearInterviewerSpeakingWatchdog()
    logRealtimeDebugEvent('ui.close_realtime_resources', status)
    updateListeningState(false)
    micStreamingRef.current = false
    if (status) {
      updateVoiceStatus(status)
    }
  }

  const stopListeningSession = (status?: string) => {
    shouldKeepListeningRef.current = false
    clearReadingPromptTimer()
    if (pendingSpeechTimeoutRef.current !== null) {
      window.clearTimeout(pendingSpeechTimeoutRef.current)
      pendingSpeechTimeoutRef.current = null
    }
    if (pendingSpeechRef.current.trim()) {
      void flushPendingSpeech()
    }
    closeRealtimeResources(status ?? 'Microphone stopped')
  }

  const speakInterviewerReply = (reply: string) => {
    const dataChannel = dataChannelRef.current
    if (!reply.trim() || !isVoiceEnabled) {
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
      lastActivityAtRef.current = Date.now()
      setLocalMicEnabled(false)
      updateVoiceStatus('Interviewer speaking')
      logRealtimeDebugEvent('ui.speak_interviewer_reply', reply.slice(0, 80))
      armInterviewerSpeakingWatchdog()

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
                    text: buildReadAloudInstruction(reply),
                  },
                ],
              },
            ],
          },
        }),
      )
    } catch {
      speakingResponseActiveRef.current = false
      setLocalMicEnabled(micStreamingRef.current)
      updateVoiceStatus('Unable to play interviewer audio')
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
            "You are the voice transport layer for a coding interview application. Continuously transcribe the candidate's speech. Do not proactively answer the candidate or ask questions on your own. The application will decide interviewer replies separately. When the application explicitly requests audio output, read the provided interviewer text naturally and keep the wording exact.",
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
    logRealtimeDebugEvent(
      eventType || 'unknown',
      eventType === 'error'
        ? (
            typeof event.error === 'string'
              ? event.error
              : isRecord(event.error) && typeof event.error.message === 'string'
                ? event.error.message
                : undefined
          )
        : undefined,
    )
    switch (eventType) {
      case 'input_audio_buffer.speech_started': {
        if (pendingSpeechTimeoutRef.current !== null) {
          pendingSpeechResumeMarkerRef.current = true
          logRealtimeDebugEvent('speech.flush.resume_detected')
        }
        lastActivityAtRef.current = Date.now()
        if (!speakingResponseActiveRef.current) {
          updateVoiceStatus('Listening')
        }
        break
      }
      case 'input_audio_buffer.speech_stopped': {
        lastActivityAtRef.current = Date.now()
        if (!speakingResponseActiveRef.current) {
          updateVoiceStatus('Processing speech')
        }
        break
      }
      case 'conversation.item.input_audio_transcription.delta': {
        const delta = extractTranscriptText(event)
        if (!delta) {
          break
        }
        if (pendingSpeechTimeoutRef.current !== null && pendingSpeechResumeMarkerRef.current) {
          window.clearTimeout(pendingSpeechTimeoutRef.current)
          pendingSpeechTimeoutRef.current = null
          pendingSpeechResumeMarkerRef.current = false
          logRealtimeDebugEvent('speech.flush.cancelled_on_new_transcript')
        }
        interimTranscriptRef.current = `${interimTranscriptRef.current}${delta}`
        lastActivityAtRef.current = Date.now()
        syncDraftFromRealtimeBuffer()
        break
      }
      case 'conversation.item.input_audio_transcription.completed': {
        const transcript = extractTranscriptText(event, interimTranscriptRef.current).trim()
        interimTranscriptRef.current = ''
        if (!transcript) {
          syncDraftFromRealtimeBuffer()
          break
        }
        if (pendingSpeechTimeoutRef.current !== null && pendingSpeechResumeMarkerRef.current) {
          window.clearTimeout(pendingSpeechTimeoutRef.current)
          pendingSpeechTimeoutRef.current = null
          pendingSpeechResumeMarkerRef.current = false
          logRealtimeDebugEvent('speech.flush.cancelled_on_completed_transcript')
        }

        const nextTranscript = pendingSpeechRef.current
          ? `${pendingSpeechRef.current} ${transcript}`.trim()
          : transcript
        const clarificationDetected =
          pendingSpeechTypeRef.current === 'clarification_asked' || looksLikeClarification(nextTranscript)

        pendingSpeechRef.current = nextTranscript
        pendingSpeechTypeRef.current = clarificationDetected ? 'clarification_asked' : 'candidate_spoke'
        lastActivityAtRef.current = Date.now()
        updateVoiceStatus('Listening')
        syncDraftFromRealtimeBuffer()
        schedulePendingSpeechFlush()
        break
      }
      case 'response.created': {
        break
      }
      case 'response.done': {
        lastActivityAtRef.current = Date.now()
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
        if (speakingResponseActiveRef.current) {
          restoreAfterInterviewerSpeech()
        }
        break
      }
      case 'output_audio_buffer.started': {
        speakingResponseActiveRef.current = true
        lastActivityAtRef.current = Date.now()
        setLocalMicEnabled(false)
        updateVoiceStatus('Interviewer speaking')
        armInterviewerSpeakingWatchdog()
        break
      }
      case 'output_audio_buffer.stopped':
      case 'output_audio_buffer.cleared': {
        restoreAfterInterviewerSpeech()
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

  const startListeningSession = async (startMicEnabled: boolean) => {
    if (!window.isSecureContext) {
      setError('Voice mode needs a secure page. Open the app on localhost or HTTPS.')
      return
    }

    if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === 'undefined') {
      setError('Realtime voice is not available in this browser.')
      return
    }

    setError(null)
    updateVoiceStatus('Connecting voice session')

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
          updateVoiceStatus('Click Start mic again if browser blocked speaker playback')
        })
      }

      peerConnection.onconnectionstatechange = () => {
        logRealtimeDebugEvent('rtc.connection_state', peerConnection?.connectionState ?? 'unknown')
        if (peerConnection?.connectionState === 'failed' || peerConnection?.connectionState === 'disconnected') {
          shouldKeepListeningRef.current = false
          closeRealtimeResources('Voice session disconnected')
          setError('Realtime voice connection dropped. Start the mic again.')
        }
      }

      dataChannel.onopen = () => {
        logRealtimeDebugEvent('rtc.data_channel_open', startMicEnabled ? 'mic_on' : 'mic_off')
        shouldKeepListeningRef.current = true
        micStreamingRef.current = startMicEnabled
        setLocalMicEnabled(startMicEnabled)
        updateListeningState(startMicEnabled)
        updateVoiceStatus(startMicEnabled ? 'Listening' : 'Voice ready')
        setError(null)
        sendRealtimeSessionUpdate(dataChannel as RTCDataChannel)
      }
      dataChannel.onclose = () => {
        logRealtimeDebugEvent('rtc.data_channel_close')
        if (!shouldKeepListeningRef.current) {
          closeRealtimeResources('Microphone stopped')
          return
        }
        shouldKeepListeningRef.current = false
        closeRealtimeResources('Voice session ended')
        setError('Realtime voice session ended. Start the mic again.')
      }
      dataChannel.onerror = () => {
        logRealtimeDebugEvent('rtc.data_channel_error')
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
      setLocalMicEnabled(startMicEnabled)
      logRealtimeDebugEvent('rtc.local_stream_ready')

      const offer = await peerConnection.createOffer()
      await peerConnection.setLocalDescription(offer)
      await waitForIceGatheringComplete(peerConnection)
      logRealtimeDebugEvent('rtc.ice_complete')

      const answer = await createCodingRealtimeSession(session.id, {
        sdp: peerConnection.localDescription?.sdp ?? offer.sdp ?? '',
      })
      logRealtimeDebugEvent('rtc.session_created', answer.voice)
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
      lastActivityAtRef.current = Date.now()
    } catch (err) {
      logRealtimeDebugEvent('rtc.start_failed', err instanceof Error ? err.message : 'unknown error')
      shouldKeepListeningRef.current = false
      localStream?.getTracks().forEach((track) => track.stop())
      dataChannel?.close()
      peerConnection?.close()
      closeRealtimeResources()
      setError(err instanceof Error ? err.message : 'Unable to start realtime voice session')
    }
  }

  const toggleListening = async () => {
    if (hasRealtimeConnection()) {
      const nextMicEnabled = !micStreamingRef.current
      shouldKeepListeningRef.current = true
      micStreamingRef.current = nextMicEnabled
      logRealtimeDebugEvent('ui.toggle_mic', nextMicEnabled ? 'on' : 'off')
      setLocalMicEnabled(nextMicEnabled)
      updateListeningState(nextMicEnabled)
      updateVoiceStatus(nextMicEnabled ? 'Listening' : 'Voice ready')
      return
    }

    shouldKeepListeningRef.current = true
    logRealtimeDebugEvent('ui.toggle_mic', 'start_session_with_mic_on')
    await startListeningSession(true)
  }

  const submitSpeech = async (eventType?: CodingInterviewEvent['type']) => {
    const trimmed = speechDraft.trim()
    if (!trimmed) {
      return
    }

    const resolvedEventType =
      eventType ?? (looksLikeClarification(trimmed) ? 'clarification_asked' : 'candidate_spoke')

    lastActivityAtRef.current = Date.now()
    clearReadingPromptTimer()
    if (session.coding_round) {
      onSessionChange({
        ...session,
        coding_round: {
          ...session.coding_round,
          conversation: [
            ...session.coding_round.conversation,
            buildCandidateConversationTurn(trimmed, resolvedEventType),
          ],
        },
      })
    }
    setSpeechDraft('')
    await sendEvent(
      buildEvent(resolvedEventType, {
        transcript_excerpt: trimmed,
        code_excerpt: localCodeRef.current.slice(-600),
      }),
      trimmed,
    )
  }

  useEffect(() => {
    if (!isVoiceEnabled && (isListening || hasRealtimeConnection())) {
      stopListeningSession('Microphone stopped')
    }
  }, [isVoiceEnabled, isListening])

  useEffect(() => {
    if (!codingRound?.problem || !isVoiceEnabled) {
      return
    }

    if (hasRealtimeConnection()) {
      return
    }

    if (autoVoiceStartedRef.current === codingRound.problem.id) {
      return
    }

    autoVoiceStartedRef.current = codingRound.problem.id
    shouldKeepListeningRef.current = true
    void startListeningSession(false)
  }, [codingRound?.problem?.id, isVoiceEnabled])

  useEffect(() => {
    if (!codingRound?.problem || !isVoiceEnabled) {
      return
    }

    if (!hasRealtimeConnection()) {
      return
    }

    if (problemReadAloudRef.current === codingRound.problem.id) {
      return
    }

    if (voiceStatus !== 'Voice ready') {
      return
    }

    problemReadAloudRef.current = codingRound.problem.id
    const readAloudText = buildProblemReadAloudText(session)
    if (!readAloudText.trim()) {
      return
    }
    speakInterviewerReply(readAloudText)
  }, [codingRound?.problem?.id, isVoiceEnabled, session, voiceStatus])

  useEffect(() => {
    const latestReply = [...(codingRound?.conversation ?? [])]
      .map((turn, index) => ({ turn, index }))
      .reverse()
      .find((entry) => entry.turn.role === 'interviewer')

    if (!latestReply) {
      return
    }

    const latestReplyKey = `${latestReply.turn.created_at}-${latestReply.index}-${latestReply.turn.kind}`

    if (latestReplyKey === latestSpokenTurnRef.current) {
      return
    }

    if (!isVoiceEnabled) {
      latestSpokenTurnRef.current = latestReplyKey
      return
    }

    latestSpokenTurnRef.current = latestReplyKey
    speakInterviewerReply(latestReply.turn.content)
  }, [codingRound?.conversation, isListening, isVoiceEnabled])

  useEffect(() => {
    clearReadingPromptTimer()

    if (!codingRound?.problem || codingRound.current_mode !== 'reading') {
      return
    }

    readingPromptTimerRef.current = window.setTimeout(() => {
      readingPromptTimerRef.current = null
      void (async () => {
        try {
          const updated = await resumeCodingStage(session.id)
          onSessionChange(updated)
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Unable to continue the coding round')
        }
      })()
    }, READING_GRACE_PERIOD_MS)

    return () => {
      clearReadingPromptTimer()
    }
  }, [codingRound?.problem?.id, codingRound?.current_mode, onSessionChange, session.id])

  useEffect(() => {
    if (!assistantThreadRef.current) {
      return
    }

    assistantThreadRef.current.scrollTo({
      top: assistantThreadRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [codingRound?.conversation.length])

  useEffect(() => {
    return () => {
      shouldKeepListeningRef.current = false
      clearReadingPromptTimer()
      clearInterviewerSpeakingWatchdog()
      if (pendingSpeechTimeoutRef.current !== null) {
        window.clearTimeout(pendingSpeechTimeoutRef.current)
      }
      closeRealtimeResources()
    }
  }, [])

  useEffect(() => {
    if (!codingRound) {
      return
    }

    if (code === lastCodeSentRef.current) {
      return
    }

    const timeout = window.setTimeout(() => {
      lastActivityAtRef.current = Date.now()
      clearReadingPromptTimer()
      lastCodeSentRef.current = code
      void sendEvent(
        buildEvent('code_changed', {
          code_excerpt: localCodeRef.current.slice(-600),
          metadata: { code_length: code.length },
        }),
      )
    }, 1200)

    return () => {
      window.clearTimeout(timeout)
    }
  }, [code, codingRound, session.id])

  useEffect(() => {
    if (!codingRound) {
      return
    }

    const interval = window.setInterval(() => {
      if (speakingResponseActiveRef.current) {
        return
      }

      const now = Date.now()
      const inactiveFor = now - lastActivityAtRef.current
      const sinceLastPause = now - lastPauseAtRef.current

      if (inactiveFor < LONG_PAUSE_THRESHOLD_MS || sinceLastPause < LONG_PAUSE_THRESHOLD_MS) {
        return
      }

      lastPauseAtRef.current = now
      void sendEvent(
        buildEvent('candidate_pause', {
          metadata: { duration_seconds: Math.floor(inactiveFor / 1000) },
        }),
      )
    }, 5000)

    return () => {
      window.clearInterval(interval)
    }
  }, [codingRound, code, language])

  const finishRound = async () => {
    const recentTranscript =
      speechDraft.trim() || pendingSpeechRef.current.trim() || interimTranscriptRef.current.trim()
    stopListeningSession('Microphone stopped')
    setIsWorking(true)
    setError(null)
    try {
      const updated = await finishInterview(session.id, {
        code,
        language,
        transcript_recent: recentTranscript,
      })
      onSessionChange(updated)
      setSpeechDraft('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to finish the coding round')
    } finally {
      setIsWorking(false)
    }
  }

  if (!codingRound?.problem) {
    return (
      <article className="flow-card">
        <p className="section-eyebrow">Coding Round</p>
        <h2>Coding round unavailable</h2>
      </article>
    )
  }

  return (
    <section className="coding-stage">
      <audio ref={remoteAudioRef} autoPlay playsInline hidden />
      <article className="flow-card coding-stage-header">
        <div className="section-head">
          <div>
            <p className="section-eyebrow">Coding Interview</p>
            <h2>{codingRound.problem.title}</h2>
          </div>
          <div className="coding-pill-row">
            <span className="length-pill">{codingRound.problem.difficulty}</span>
            <span className="length-pill">{codingRound.interviewer_mode}</span>
          </div>
        </div>
        <div className="meta-grid compact">
          <div>
            <span>Target company</span>
            <strong>{codingRound.target_company ?? 'Closest available style'}</strong>
          </div>
          <div>
            <span>Matched bank</span>
            <strong>{codingRound.matched_company ?? codingRound.problem.company}</strong>
          </div>
          <div>
            <span>Editor</span>
            <strong>{codingRound.editor_mode === 'monaco' ? 'Monaco' : 'Plain text'}</strong>
          </div>
        </div>
      </article>

      <article className="flow-card coding-problem-card">
        <p className="section-eyebrow">Prompt</p>
        <h3>{codingRound.problem.prompt}</h3>
        <div className="coding-copy-grid">
          <section>
            <h4>Constraints</h4>
            <ul className="detail-list">
              {codingRound.problem.constraints.map((constraint) => (
                <li key={constraint}>{constraint}</li>
              ))}
            </ul>
          </section>
          <section>
            <h4>Focus areas</h4>
            <ul className="detail-list">
              {codingRound.problem.expected_topics.map((topic) => (
                <li key={topic}>{topic}</li>
              ))}
            </ul>
          </section>
        </div>
        {codingRound.problem.complexity_target && (
          <p className="support-copy">Target: {codingRound.problem.complexity_target}</p>
        )}
        <div className="example-grid">
          {codingRound.problem.examples.map((example, index) => (
            <article key={`${example.input}-${index}`} className="helper-card">
              <p className="section-eyebrow">Example {index + 1}</p>
              <p>
                <strong>Input:</strong> {example.input}
              </p>
              <p>
                <strong>Output:</strong> {example.output}
              </p>
              {example.explanation && (
                <p>
                  <strong>Why:</strong> {example.explanation}
                </p>
              )}
            </article>
          ))}
        </div>
      </article>

      <div className="coding-workbench">
        <article className="flow-card coding-editor-card">
          <div className="section-head">
            <div>
              <p className="section-eyebrow">Workspace</p>
              <h3>Write the solution</h3>
            </div>
            <select
              className="text-input language-select"
              value={language}
              onChange={(event) =>
                setLanguage(
                  event.target.value as 'typescript' | 'javascript' | 'python' | 'java' | 'csharp',
                )
              }
            >
              <option value="typescript">TypeScript</option>
              <option value="javascript">JavaScript</option>
              <option value="python">Python</option>
              <option value="java">Java</option>
              <option value="csharp">C#</option>
            </select>
          </div>
          <CodeEditor
            language={language}
            value={code}
            onChange={(nextValue) => {
              localCodeRef.current = nextValue
              setCode(nextValue)
              lastActivityAtRef.current = Date.now()
            }}
            plainMode={codingRound.editor_mode === 'plain'}
          />
        </article>

        <article className="flow-card coding-interviewer-card">
          <div className="section-head">
            <div>
              <p className="section-eyebrow">AI Interviewer</p>
              <h3>Short live follow-ups</h3>
            </div>
          </div>

          <div ref={assistantThreadRef} className="assistant-thread">
            {codingRound.conversation.length === 0 ? (
              <article className="intervention-card neutral">
                <strong>Interviewer</strong>
                <p>I&apos;ll engage as you explain your thinking and ask for clarification.</p>
              </article>
            ) : (
              codingRound.conversation.map((turn, index) => (
                <article
                  key={`${turn.created_at}-${index}`}
                  className={`intervention-card ${turn.role === 'candidate' ? 'candidate' : turn.severity ?? 'neutral'}`}
                >
                  <div className="question-review-head">
                    <strong>{turn.role === 'candidate' ? 'You' : 'Interviewer'}</strong>
                    {turn.role === 'interviewer' && turn.kind === 'intervention' ? (
                      <span className="status-dot pending">{formatReason(codingRound.latest_reason)}</span>
                    ) : (
                      <span className="status-dot pending">
                        {turn.source_event_type ? formatReason(turn.source_event_type) : turn.kind}
                      </span>
                    )}
                  </div>
                  <p>{turn.content}</p>
                </article>
              ))
            )}
          </div>

          <label htmlFor="speech-draft" className="field-label">
            Spoken explanation
          </label>
          <div className="speech-composer">
            <textarea
              id="speech-draft"
              className="large-textarea speech-note speech-note-with-send"
              rows={5}
              value={speechDraft}
              onChange={(event) => setSpeechDraft(event.target.value)}
              placeholder="Use the mic for live speech or paste a recent explanation here."
            />
            <button
              type="button"
              className="secondary-button send-message-button"
              aria-label="Send message"
              title="Send message"
              disabled={isWorking}
              onClick={() => void submitSpeech()}
            >
              <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
                className="send-message-icon"
              >
                <path
                  d="M4 19.5L20 12L4 4.5L4 10.5L14 12L4 13.5L4 19.5Z"
                  fill="currentColor"
                />
              </svg>
            </button>
          </div>

          <div className={`helper-actions coding-primary-actions ${!isVoiceEnabled ? 'single-action' : ''}`}>
            {isVoiceEnabled ? (
              <button type="button" className="primary-button" onClick={() => void toggleListening()}>
                {isListening ? 'Stop mic' : 'Start mic'}
              </button>
            ) : null}
            <button
              type="button"
              className={`primary-button finish-round-button ${!isVoiceEnabled ? 'full-width-button' : ''}`}
              disabled={isWorking}
              onClick={() => void finishRound()}
            >
              {isWorking ? 'Saving...' : 'Finish Interview'}
            </button>
          </div>

          {isVoiceEnabled && voiceStatus && !error && (
            <p className="status-banner info" role="status">
              {voiceStatus}
            </p>
          )}

          {error && (
            <p className="status-banner error" role="alert">
              {error}
            </p>
          )}

          {codingRound.evaluation && (
            <article className="helper-card">
              <p className="section-eyebrow">Latest evaluation</p>
              <p>{codingRound.evaluation.summary}</p>
            </article>
          )}
        </article>
      </div>
    </section>
  )
}
