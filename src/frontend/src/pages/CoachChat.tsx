import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './CoachChat.css'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
}

interface StreamEvent {
  type: 'start' | 'delta' | 'done' | 'error'
  delta?: string
  error?: string
}

interface RealtimeEvent {
  type?: string
  transcript?: string
  text?: string
  delta?: string
  item?: {
    role?: 'user' | 'assistant'
  }
  response?: {
    output_text?: string
  }
}

const WELCOME_TEXT =
  "I'm your interview coach. Share your resume and job description, and I'll guide a realistic interview flow."

function createMessage(role: ChatMessage['role'], content: string): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content,
  }
}

async function readSseStream(
  response: Response,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  if (!response.body) {
    throw new Error('Missing response stream from server')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const emitBlock = (block: string) => {
    const dataLines = block
      .split('\n')
      .map((line) => line.trimStart())
      .filter((line) => line.startsWith('data:'))

    if (dataLines.length === 0) {
      return
    }

    const data = dataLines.map((line) => line.slice(5).trimStart()).join('\n').trim()
    if (!data) {
      return
    }

    try {
      const parsed = JSON.parse(data) as StreamEvent
      onEvent(parsed)
    } catch {
      // Ignore malformed SSE fragments instead of rendering protocol noise.
      return
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) {
      break
    }

    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const block of events) {
      emitBlock(block)
    }
  }

  if (buffer.trim().length > 0) {
    emitBlock(buffer)
  }
}

export default function CoachChat() {
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID())
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [attachedFile, setAttachedFile] = useState<File | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isStartingVoice, setIsStartingVoice] = useState(false)
  const [isVoiceActive, setIsVoiceActive] = useState(false)
  const [voiceStatus, setVoiceStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)
  const voicePeerRef = useRef<RTCPeerConnection | null>(null)
  const voiceAudioRef = useRef<HTMLAudioElement | null>(null)
  const voiceChannelRef = useRef<RTCDataChannel | null>(null)

  const messageHistory = useMemo(
    () => messages.filter((message) => message.role !== 'system'),
    [messages],
  )

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messageHistory, isStreaming])

  const resetConversation = async () => {
    setError(null)
    setIsStreaming(false)
    setAttachedFile(null)
    setDraft('')

    try {
      const response = await fetch('/api/session/new', { method: 'POST' })
      if (!response.ok) {
        throw new Error(`Session reset failed (${response.status})`)
      }

      const data = (await response.json()) as { sessionId: string; systemPrompt: string }
      setSessionId(data.sessionId)
      setMessages([
        createMessage('system', data.systemPrompt),
        createMessage('system', `Session ID: ${data.sessionId}`),
        createMessage('assistant', WELCOME_TEXT),
      ])
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to start a new session'
      setError(message)
    }
  }

  useEffect(() => {
    void resetConversation()
  }, [])

  const stopVoiceMode = () => {
    const dataChannel = voiceChannelRef.current
    if (dataChannel) {
      dataChannel.close()
      voiceChannelRef.current = null
    }

    const peer = voicePeerRef.current
    if (peer) {
      peer.getSenders().forEach((sender) => sender.track?.stop())
      peer.close()
      voicePeerRef.current = null
    }

    const remoteAudio = voiceAudioRef.current
    if (remoteAudio) {
      remoteAudio.pause()
      remoteAudio.srcObject = null
      voiceAudioRef.current = null
    }

    setIsVoiceActive(false)
    setVoiceStatus('Voice mode stopped')
  }

  const appendRealtimeMessage = (role: 'user' | 'assistant', content: string) => {
    const clean = content.trim()
    if (!clean) {
      return
    }

    setMessages((previous) => {
      const last = previous[previous.length - 1]
      if (last && last.role === role && last.content.trim() === clean) {
        return previous
      }
      return [...previous, createMessage(role, clean)]
    })
  }

  const handleRealtimeEvent = (eventPayload: RealtimeEvent) => {
    const eventType = eventPayload.type ?? ''

    if (eventType === 'conversation.item.input_audio_transcription.completed') {
      const text = eventPayload.transcript ?? eventPayload.text ?? ''
      appendRealtimeMessage('user', text)
      return
    }

    if (eventType === 'response.audio_transcript.done') {
      appendRealtimeMessage('assistant', eventPayload.transcript ?? '')
      return
    }

    if (eventType === 'response.output_text.done') {
      appendRealtimeMessage('assistant', eventPayload.text ?? eventPayload.response?.output_text ?? '')
      return
    }

    if (eventType === 'error') {
      setError('Voice stream error from realtime session')
      return
    }
  }

  useEffect(() => {
    return () => {
      stopVoiceMode()
    }
  }, [])

  const startVoiceMode = async () => {
    if (isVoiceActive) {
      return
    }

    setError(null)
    setVoiceStatus(null)
    setIsStartingVoice(true)

    try {
      const response = await fetch('/api/voice/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          voice: 'alloy',
          model: 'gpt-4o-realtime-preview',
        }),
      })

      if (!response.ok) {
        throw new Error(`Voice session failed (${response.status})`)
      }

      const payload = (await response.json()) as {
        id?: string
        model?: string
        client_secret?: { value?: string } | string
      }

      const ephemeralKey =
        typeof payload.client_secret === 'string'
          ? payload.client_secret
          : payload.client_secret?.value

      if (!ephemeralKey) {
        throw new Error('Voice session did not include an ephemeral key')
      }

      const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const peerConnection = new RTCPeerConnection()

      audioStream.getTracks().forEach((track) => {
        peerConnection.addTrack(track, audioStream)
      })

      const remoteAudio = new Audio()
      remoteAudio.autoplay = true
      peerConnection.ontrack = (event) => {
        remoteAudio.srcObject = event.streams[0]
      }

      const dataChannel = peerConnection.createDataChannel('oai-events')
      dataChannel.onopen = () => {
        setVoiceStatus('Voice session live')
      }
      dataChannel.onerror = () => {
        setError('Voice data channel error')
      }
      dataChannel.onclose = () => {
        setVoiceStatus('Voice channel closed')
      }
      dataChannel.onmessage = (event) => {
        try {
          const parsed = JSON.parse(String(event.data)) as RealtimeEvent
          handleRealtimeEvent(parsed)
        } catch {
          return
        }
      }

      const offer = await peerConnection.createOffer()
      await peerConnection.setLocalDescription(offer)

      const realtimeResponse = await fetch(
        `https://api.openai.com/v1/realtime?model=${encodeURIComponent(payload.model ?? 'gpt-4o-realtime-preview')}`,
        {
          method: 'POST',
          body: offer.sdp,
          headers: {
            Authorization: `Bearer ${ephemeralKey}`,
            'Content-Type': 'application/sdp',
            'OpenAI-Beta': 'realtime=v1',
          },
        },
      )

      if (!realtimeResponse.ok) {
        throw new Error(`Realtime negotiation failed (${realtimeResponse.status})`)
      }

      const answerSdp = await realtimeResponse.text()
      await peerConnection.setRemoteDescription({ type: 'answer', sdp: answerSdp })

      voicePeerRef.current = peerConnection
      voiceAudioRef.current = remoteAudio
      voiceChannelRef.current = dataChannel
      setIsVoiceActive(true)
      setVoiceStatus(payload.id ? `Voice session connected (${payload.id})` : 'Voice session connected')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to start voice mode'
      setError(message)
      stopVoiceMode()
    } finally {
      setIsStartingVoice(false)
    }
  }

  const uploadAttachment = async (file: File): Promise<string> => {
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      throw new Error(`Upload failed (${response.status})`)
    }

    const payload = (await response.json()) as { url?: string }
    if (!payload.url) {
      throw new Error('Upload response did not include file URL')
    }

    return payload.url
  }

  const submitMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isStreaming) {
      return
    }

    setError(null)
    const rawText = draft.trim()
    if (!rawText && !attachedFile) {
      return
    }

    try {
      let composedText = rawText
      if (attachedFile) {
        const fileUrl = await uploadAttachment(attachedFile)
        composedText = [rawText, `Attachment URL: ${fileUrl}`].filter(Boolean).join('\n\n')
      }

      const userMessage = createMessage('user', composedText)
      const assistantMessage = createMessage('assistant', '')

      const nextMessages = [...messageHistory, userMessage, assistantMessage]
      setMessages((previous) => [
        ...previous.filter((message) => message.role === 'system'),
        ...nextMessages,
      ])
      setDraft('')
      setAttachedFile(null)
      setIsStreaming(true)

      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sessionId,
          message: composedText,
          history: messages
            .filter((message) => message.content.trim().length > 0)
            .filter((message) => !(message.role === 'assistant' && message.content === WELCOME_TEXT))
            .map((message) => ({
              role: message.role,
              content: message.content,
            })),
        }),
      })

      if (!response.ok) {
        throw new Error(`Chat request failed (${response.status})`)
      }

      await readSseStream(response, (eventPayload) => {
        if (eventPayload.type === 'delta' && eventPayload.delta) {
          setMessages((previous) =>
            previous.map((item) =>
              item.id === assistantMessage.id
                ? { ...item, content: `${item.content}${eventPayload.delta}` }
                : item,
            ),
          )
        }

        if (eventPayload.type === 'error') {
          setError(eventPayload.error ?? 'Agent stream failed')
        }
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to send message'
      setError(message)
    } finally {
      setIsStreaming(false)
    }
  }

  return (
    <section className="coach-chat-page">
      <main className="chat-panel">
        <div className="chat-header">
          <div className="coach-header-info">
            <p className="eyebrow">Interview Simulator</p>
            <h1>Interview Coach</h1>
          </div>
          <div className="chat-header-right">
            <div className="chat-actions">
              <button type="button" onClick={() => void resetConversation()} className="action-button">
                New Chat
              </button>
              {isVoiceActive ? (
                <button type="button" onClick={stopVoiceMode} className="action-button active">
                  Stop Voice
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void startVoiceMode()}
                  className="action-button"
                  disabled={isStartingVoice}
                >
                  {isStartingVoice ? 'Starting Voice...' : 'Start Voice'}
                </button>
              )}
            </div>
            {voiceStatus && (
              <span className="voice-status" role="status" aria-live="polite">
                {voiceStatus}
              </span>
            )}
          </div>
          <p className="session-id">Session: {sessionId}</p>
        </div>

        <section className="messages" aria-label="Chat messages">
          {messageHistory.length === 0 ? (
            <div className="empty-state">{WELCOME_TEXT}</div>
          ) : (
            messageHistory.map((message) => (
              <article key={message.id} className={`bubble bubble-${message.role}`}>
                <p className="bubble-role">{message.role === 'assistant' ? 'Coach' : 'You'}</p>
                <p>{message.content || (isStreaming && message.role === 'assistant' ? 'Thinking...' : '')}</p>
              </article>
            ))
          )}
          <div ref={endRef} />
        </section>

        {error && (
          <p className="status-banner error" role="alert" aria-live="polite">
            {error}
          </p>
        )}

        <form className="composer" onSubmit={submitMessage}>
          <label htmlFor="message-input" className="sr-only">
            Your message
          </label>
          <textarea
            id="message-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Answer the latest question or ask for targeted interview practice"
            rows={3}
            disabled={isStreaming}
          />

          <div className="composer-row">
            <label className="file-picker">
              <input
                type="file"
                accept=".pdf,.docx,.doc,.txt,.md,.html"
                onChange={(event) => setAttachedFile(event.target.files?.[0] ?? null)}
                disabled={isStreaming}
              />
              Attach File
            </label>

            <button type="submit" disabled={isStreaming || (!draft.trim() && !attachedFile)}>
              {isStreaming ? 'Streaming...' : 'Send'}
            </button>
          </div>

          {attachedFile && (
            <p className="file-chip">
              {attachedFile.name}
              <button type="button" onClick={() => setAttachedFile(null)} disabled={isStreaming}>
                Remove
              </button>
            </p>
          )}
        </form>
      </main>
    </section>
  )
}
