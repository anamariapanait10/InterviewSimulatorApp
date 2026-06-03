import { useEffect, useRef, useState } from 'react'

declare global {
  interface Window {
    monaco?: {
      editor: {
        create: (element: HTMLElement, options: Record<string, unknown>) => MonacoEditor
        setModelLanguage: (model: unknown, language: string) => void
      }
    }
    require?: {
      config: (options: Record<string, unknown>) => void
      (modules: string[], callback: () => void): void
    }
  }
}

interface MonacoEditor {
  getValue: () => string
  getModel: () => unknown
  setValue: (value: string) => void
  dispose: () => void
  onDidChangeModelContent: (listener: () => void) => { dispose: () => void }
}

interface CodeEditorProps {
  language: 'typescript' | 'javascript' | 'python' | 'java' | 'csharp'
  value: string
  onChange: (value: string) => void
  plainMode: boolean
}

const MONACO_LOADER_SRC =
  'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs/loader.min.js'
const MONACO_BASE_PATH =
  'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs'

function normalizeLanguage(language: CodeEditorProps['language']): string {
  if (language === 'csharp') {
    return 'csharp'
  }
  return language
}

let monacoLoaderPromise: Promise<void> | null = null

function ensureMonacoLoader(): Promise<void> {
  if (typeof window.monaco !== 'undefined' && typeof window.require !== 'undefined') {
    return Promise.resolve()
  }

  if (monacoLoaderPromise) {
    return monacoLoaderPromise
  }

  monacoLoaderPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${MONACO_LOADER_SRC}"]`)
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error('Failed to load Monaco editor')), {
        once: true,
      })
      return
    }

    const script = document.createElement('script')
    script.src = MONACO_LOADER_SRC
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Failed to load Monaco editor'))
    document.head.appendChild(script)
  })

  return monacoLoaderPromise
}

export default function CodeEditor({ language, value, onChange, plainMode }: CodeEditorProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const editorRef = useRef<MonacoEditor | null>(null)
  const changeSubscriptionRef = useRef<{ dispose: () => void } | null>(null)
  const onChangeRef = useRef(onChange)
  const [monacoReady, setMonacoReady] = useState(false)
  const [loadFailed, setLoadFailed] = useState(false)

  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  useEffect(() => {
    if (plainMode) {
      return
    }

    let cancelled = false

    const boot = async () => {
      try {
        await ensureMonacoLoader()
        if (!window.require) {
          throw new Error('Monaco loader is unavailable')
        }

        window.require.config({ paths: { vs: MONACO_BASE_PATH } })
        window.require(['vs/editor/editor.main'], () => {
          if (cancelled || !containerRef.current || !window.monaco) {
            return
          }

          editorRef.current?.dispose()
          editorRef.current = window.monaco.editor.create(containerRef.current, {
            value,
            language: normalizeLanguage(language),
            theme: 'vs-dark',
            automaticLayout: true,
            minimap: { enabled: false },
            fontSize: 15,
            lineNumbers: 'on',
            roundedSelection: true,
            scrollBeyondLastLine: false,
          })
          changeSubscriptionRef.current = editorRef.current.onDidChangeModelContent(() => {
            const nextValue = editorRef.current?.getValue() ?? ''
            onChangeRef.current(nextValue)
          })
          setMonacoReady(true)
        })
      } catch {
        if (!cancelled) {
          setLoadFailed(true)
        }
      }
    }

    void boot()

    return () => {
      cancelled = true
      changeSubscriptionRef.current?.dispose()
      editorRef.current?.dispose()
      changeSubscriptionRef.current = null
      editorRef.current = null
    }
  }, [language, plainMode])

  useEffect(() => {
    if (!editorRef.current) {
      return
    }

    const currentValue = editorRef.current.getValue()
    if (currentValue !== value) {
      editorRef.current.setValue(value)
    }
  }, [value])

  useEffect(() => {
    if (!editorRef.current || !window.monaco) {
      return
    }
    window.monaco.editor.setModelLanguage(editorRef.current.getModel(), normalizeLanguage(language))
  }, [language, monacoReady])

  if (plainMode || loadFailed) {
    return (
      <textarea
        className={plainMode ? 'code-editor plain' : 'code-editor basic'}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
        rows={18}
      />
    )
  }

  return <div ref={containerRef} className="code-editor monaco-host" aria-label="Coding editor" />
}
