import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'

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

  while (true) {
    const { value, done } = await reader.read()
    if (done) {
      break
    }

    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const block of events) {
      const dataLine = block
        .split('\n')
        .map((line) => line.trim())
        .find((line) => line.startsWith('data:'))

      if (!dataLine) {
        continue
      }

      const data = dataLine.slice(5).trim()
      if (!data) {
        continue
      }

      try {
        const parsed = JSON.parse(data) as StreamEvent
        onEvent(parsed)
      } catch {
        onEvent({ type: 'delta', delta: data })
      }
    }
  }
}

function App() {
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID())
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [attachedFile, setAttachedFile] = useState<File | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)

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
    <div className="coach-shell">
      <header className="coach-header">
        <div>
          <p className="eyebrow">Interview Simulator</p>
          <h1>Interview Coach</h1>
          <p className="session-id">Session: {sessionId}</p>
        </div>
        <button type="button" onClick={() => void resetConversation()} className="new-chat-button">
          New Chat
        </button>
      </header>

      <main className="chat-panel">
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
          <p className="error-banner" role="alert" aria-live="polite">
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
    </div>
  )
}

export default App
