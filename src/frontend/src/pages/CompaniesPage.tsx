import { useEffect, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import {
  addCompanyKnowledgeText,
  createCompany,
  deleteCompanyKnowledge,
  listCompanies,
  listCompanyKnowledge,
  searchCompanyKnowledge,
  updateCompanyKnowledge,
  uploadCompanyKnowledge,
} from '../api'
import type {
  Company,
  CompanyKnowledgeMetadata,
  CompanyKnowledgeSource,
  RagSearchResult,
} from '../types'
import './InterviewFlow.css'

type KnowledgeSourceType =
  | 'manual'
  | 'official_page'
  | 'job_description'
  | 'engineering_blog'
  | 'interview_guide'

const SOURCE_TYPE_OPTIONS: Array<{ value: KnowledgeSourceType; label: string }> = [
  { value: 'manual', label: 'Manual notes' },
  { value: 'official_page', label: 'Official page' },
  { value: 'job_description', label: 'Job description' },
  { value: 'engineering_blog', label: 'Engineering blog' },
  { value: 'interview_guide', label: 'Interview guide' },
]

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<Company[]>([])
  const [selectedCompanyId, setSelectedCompanyId] = useState<string>('')
  const [knowledge, setKnowledge] = useState<CompanyKnowledgeSource[]>([])
  const [searchResults, setSearchResults] = useState<RagSearchResult[]>([])
  const [isLoadingCompanies, setIsLoadingCompanies] = useState(true)
  const [isLoadingKnowledge, setIsLoadingKnowledge] = useState(false)
  const [isSubmittingCompany, setIsSubmittingCompany] = useState(false)
  const [isSubmittingKnowledge, setIsSubmittingKnowledge] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [companyForm, setCompanyForm] = useState({
    name: '',
    description: '',
    website: '',
  })
  const [knowledgeMode, setKnowledgeMode] = useState<'text' | 'upload'>('text')
  const [knowledgeForm, setKnowledgeForm] = useState({
    title: '',
    content: '',
    sourceType: 'manual' as KnowledgeSourceType,
    role: '',
    category: '',
    url: '',
    file: null as File | null,
  })
  const [searchQuery, setSearchQuery] = useState('')
  const [editingSourceId, setEditingSourceId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const loadCompanies = async () => {
      setIsLoadingCompanies(true)
      setError(null)
      try {
        const items = await listCompanies()
        if (cancelled) {
          return
        }
        setCompanies(items)
        setSelectedCompanyId((previous) => previous || items[0]?.id || '')
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load companies')
        }
      } finally {
        if (!cancelled) {
          setIsLoadingCompanies(false)
        }
      }
    }

    void loadCompanies()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedCompanyId) {
      setKnowledge([])
      setSearchResults([])
      setEditingSourceId(null)
      return
    }

    let cancelled = false

    const loadKnowledge = async () => {
      setIsLoadingKnowledge(true)
      setError(null)
      try {
        const items = await listCompanyKnowledge(selectedCompanyId)
        if (!cancelled) {
          setKnowledge(items)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load company knowledge')
        }
      } finally {
        if (!cancelled) {
          setIsLoadingKnowledge(false)
        }
      }
    }

    void loadKnowledge()
    return () => {
      cancelled = true
    }
  }, [selectedCompanyId])

  const selectedCompany = companies.find((company) => company.id === selectedCompanyId) ?? null

  const resetKnowledgeForm = () => {
    setKnowledgeForm({
      title: '',
      content: '',
      sourceType: 'manual',
      role: '',
      category: '',
      url: '',
      file: null,
    })
    setKnowledgeMode('text')
    setEditingSourceId(null)
  }

  const handleCreateCompany = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!companyForm.name.trim()) {
      setError('Company name is required.')
      return
    }

    setIsSubmittingCompany(true)
    setError(null)
    try {
      const created = await createCompany({
        name: companyForm.name.trim(),
        description: companyForm.description.trim() || undefined,
        website: companyForm.website.trim() || undefined,
      })
      setCompanies((previous) => [created, ...previous])
      setSelectedCompanyId(created.id)
      setCompanyForm({ name: '', description: '', website: '' })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create company')
    } finally {
      setIsSubmittingCompany(false)
    }
  }

  const handleAddKnowledge = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedCompanyId) {
      setError('Choose a company first.')
      return
    }
    if (!knowledgeForm.title.trim()) {
      setError('Knowledge title is required.')
      return
    }

    setIsSubmittingKnowledge(true)
    setError(null)
    try {
      const metadata: CompanyKnowledgeMetadata = {
        role: knowledgeForm.role.trim() || undefined,
        category: knowledgeForm.category.trim() || undefined,
        url: knowledgeForm.url.trim() || undefined,
      }

      if (editingSourceId) {
        const updated = await updateCompanyKnowledge(selectedCompanyId, editingSourceId, {
          title: knowledgeForm.title.trim(),
          content: knowledgeForm.content.trim(),
          source_type: knowledgeForm.sourceType,
          metadata,
        })
        setKnowledge((previous) =>
          previous.map((item) => (item.id === updated.id ? updated : item)),
        )
      } else {
        const created =
          knowledgeMode === 'text'
            ? await addCompanyKnowledgeText(selectedCompanyId, {
                title: knowledgeForm.title.trim(),
                content: knowledgeForm.content.trim(),
                source_type: knowledgeForm.sourceType,
                metadata,
              })
            : await uploadCompanyKnowledge(selectedCompanyId, {
                file: knowledgeForm.file as File,
                title: knowledgeForm.title.trim(),
                source_type: knowledgeForm.sourceType,
                metadata,
              })

        setKnowledge((previous) => [created, ...previous])
      }

      resetKnowledgeForm()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to add knowledge')
    } finally {
      setIsSubmittingKnowledge(false)
    }
  }

  const beginEditing = (source: CompanyKnowledgeSource) => {
    setKnowledgeMode('text')
    setEditingSourceId(source.id)
    setKnowledgeForm({
      title: source.title,
      content: source.content,
      sourceType: source.source_type,
      role: source.metadata.role ?? '',
      category: source.metadata.category ?? '',
      url: source.metadata.url ?? '',
      file: null,
    })
    setError(null)
  }

  const handleDeleteKnowledge = async (source: CompanyKnowledgeSource) => {
    if (!selectedCompanyId) {
      return
    }

    setError(null)
    try {
      await deleteCompanyKnowledge(selectedCompanyId, source.id)
      setKnowledge((previous) => previous.filter((item) => item.id !== source.id))
      if (editingSourceId === source.id) {
        resetKnowledgeForm()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to delete knowledge')
    }
  }

  const handleSearch = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedCompanyId || !searchQuery.trim()) {
      return
    }

    setIsSearching(true)
    setError(null)
    try {
      const results = await searchCompanyKnowledge(selectedCompanyId, {
        query: searchQuery.trim(),
        top_k: 5,
      })
      setSearchResults(results)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to search knowledge')
    } finally {
      setIsSearching(false)
    }
  }

  if (isLoadingCompanies) {
    return (
      <section className="page-stack">
        <article className="flow-card">
          <p className="section-eyebrow">Companies</p>
          <h1>Loading company knowledge workspace...</h1>
        </article>
      </section>
    )
  }

  return (
    <section className="page-stack">
      <article className="hero-card companies-hero">
        <p className="section-eyebrow">Company Knowledge</p>
        <h1>Build interview prep context around real companies.</h1>
        <p className="support-copy">
          Create company profiles, ingest official or manual knowledge, and test semantic retrieval
          before using that context in interview generation.
        </p>
      </article>

      {error && (
        <p className="status-banner error" role="alert">
          {error}
        </p>
      )}

      <section className="companies-layout">
        <article className="flow-card companies-sidebar">
          <p className="section-eyebrow">Companies</p>
          <h2>Knowledge workspaces</h2>
          <div className="company-list">
            {companies.length === 0 ? (
              <p className="support-copy">Create your first company to start indexing preparation material.</p>
            ) : (
              companies.map((company) => (
                <button
                  key={company.id}
                  type="button"
                  className={selectedCompanyId === company.id ? 'company-chip active' : 'company-chip'}
                  onClick={() => setSelectedCompanyId(company.id)}
                >
                  <strong>{company.name}</strong>
                  <span>{company.description || 'No description yet'}</span>
                </button>
              ))
            )}
          </div>

          <form className="company-form" onSubmit={handleCreateCompany}>
            <p className="section-eyebrow">New Company</p>
            <input
              className="text-input"
              placeholder="Company name"
              value={companyForm.name}
              onChange={(event) => setCompanyForm((previous) => ({ ...previous, name: event.target.value }))}
            />
            <input
              className="text-input"
              placeholder="Website"
              value={companyForm.website}
              onChange={(event) => setCompanyForm((previous) => ({ ...previous, website: event.target.value }))}
            />
            <textarea
              className="large-textarea"
              rows={4}
              placeholder="Short description"
              value={companyForm.description}
              onChange={(event) =>
                setCompanyForm((previous) => ({ ...previous, description: event.target.value }))
              }
            />
            <button type="submit" className="primary-button" disabled={isSubmittingCompany}>
              {isSubmittingCompany ? 'Creating...' : 'Create Company'}
            </button>
          </form>
        </article>

        <div className="companies-main">
          <article className="flow-card">
            <div className="section-head">
              <div>
                <p className="section-eyebrow">Selected Company</p>
                <h2>{selectedCompany?.name ?? 'Pick a company to continue'}</h2>
              </div>
            </div>
            {selectedCompany ? (
              <div className="meta-grid compact">
                <div>
                  <span>Website</span>
                  <strong>{selectedCompany.website || 'Not set'}</strong>
                </div>
                <div>
                  <span>Sources</span>
                  <strong>{knowledge.length}</strong>
                </div>
                <div>
                  <span>Created</span>
                  <strong>{new Date(selectedCompany.created_at).toLocaleDateString()}</strong>
                </div>
              </div>
            ) : (
              <p className="support-copy">Create a company or pick one from the left column.</p>
            )}
          </article>

          <article className="flow-card">
            <div className="section-head">
              <div>
                <p className="section-eyebrow">Add Knowledge</p>
                <h2>{editingSourceId ? 'Refine indexed knowledge' : 'Ingest company-specific material'}</h2>
              </div>
              {editingSourceId ? (
                <button type="button" className="secondary-button" onClick={resetKnowledgeForm}>
                  Cancel edit
                </button>
              ) : (
                <div className="mode-toggle">
                  <button
                    type="button"
                    className={knowledgeMode === 'text' ? 'toggle-option active' : 'toggle-option'}
                    onClick={() => setKnowledgeMode('text')}
                  >
                    Text
                  </button>
                  <button
                    type="button"
                    className={knowledgeMode === 'upload' ? 'toggle-option active' : 'toggle-option'}
                    onClick={() => setKnowledgeMode('upload')}
                  >
                    Upload
                  </button>
                </div>
              )}
            </div>

            <form className="company-form" onSubmit={handleAddKnowledge}>
              <input
                className="text-input"
                placeholder="Title"
                value={knowledgeForm.title}
                onChange={(event) => setKnowledgeForm((previous) => ({ ...previous, title: event.target.value }))}
              />
              <select
                className="text-input"
                value={knowledgeForm.sourceType}
                onChange={(event) =>
                  setKnowledgeForm((previous) => ({
                    ...previous,
                    sourceType: event.target.value as KnowledgeSourceType,
                  }))
                }
              >
                {SOURCE_TYPE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <div className="setup-grid">
                <input
                  className="text-input"
                  placeholder="Role (optional)"
                  value={knowledgeForm.role}
                  onChange={(event) => setKnowledgeForm((previous) => ({ ...previous, role: event.target.value }))}
                />
                <input
                  className="text-input"
                  placeholder="Category (optional)"
                  value={knowledgeForm.category}
                  onChange={(event) =>
                    setKnowledgeForm((previous) => ({ ...previous, category: event.target.value }))
                  }
                />
              </div>
              <input
                className="text-input"
                placeholder="Source URL (optional)"
                value={knowledgeForm.url}
                onChange={(event) => setKnowledgeForm((previous) => ({ ...previous, url: event.target.value }))}
              />

              {knowledgeMode === 'text' ? (
                <textarea
                  className="large-textarea"
                  rows={10}
                  placeholder="Paste company knowledge here..."
                  value={knowledgeForm.content}
                  onChange={(event) =>
                    setKnowledgeForm((previous) => ({ ...previous, content: event.target.value }))
                  }
                />
              ) : (
                <label className="file-input compact-upload">
                  <input
                    type="file"
                    accept=".pdf,.doc,.docx,.txt,.md,.html"
                    onChange={(event: ChangeEvent<HTMLInputElement>) =>
                      setKnowledgeForm((previous) => ({
                        ...previous,
                        file: event.target.files?.[0] ?? null,
                      }))
                    }
                  />
                  <span>{knowledgeForm.file ? knowledgeForm.file.name : 'Choose knowledge file'}</span>
                </label>
              )}

              <button
                type="submit"
                className="primary-button"
                disabled={
                  isSubmittingKnowledge ||
                  !selectedCompanyId ||
                  (editingSourceId
                    ? !knowledgeForm.content.trim()
                    : knowledgeMode === 'text'
                      ? !knowledgeForm.content.trim()
                      : !knowledgeForm.file)
                }
              >
                {isSubmittingKnowledge
                  ? editingSourceId
                    ? 'Saving...'
                    : 'Indexing...'
                  : editingSourceId
                    ? 'Save Changes'
                    : 'Save Knowledge'}
              </button>
            </form>
          </article>

          <article className="flow-card">
            <p className="section-eyebrow">RAG Search</p>
            <h2>Probe retrieval quality</h2>
            <form className="company-form" onSubmit={handleSearch}>
              <input
                className="text-input"
                placeholder="Search query, for example: frontend performance interview topics"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
              <button type="submit" className="secondary-button" disabled={isSearching || !selectedCompanyId}>
                {isSearching ? 'Searching...' : 'Search Knowledge'}
              </button>
            </form>

            {searchResults.length > 0 && (
              <div className="question-review-list">
                {searchResults.map((result, index) => (
                  <article key={`${result.metadata.title}-${index}`} className="question-review-item">
                    <div className="question-review-head">
                      <span className="tag technical">{result.metadata.source_type || 'context'}</span>
                      <strong>{result.metadata.title || `Match ${index + 1}`}</strong>
                    </div>
                    <p className="review-feedback">{result.content}</p>
                  </article>
                ))}
              </div>
            )}
          </article>

          <article className="flow-card">
            <p className="section-eyebrow">Knowledge Library</p>
            <h2>Stored company sources</h2>
            {isLoadingKnowledge ? (
              <p className="support-copy">Loading indexed sources...</p>
            ) : knowledge.length === 0 ? (
              <p className="support-copy">No indexed sources yet for this company.</p>
            ) : (
              <div className="question-review-list">
                {knowledge.map((source) => (
                  <article key={source.id} className="question-review-item">
                    <div className="question-review-head">
                      <span className="tag behavioral">{source.source_type.replace('_', ' ')}</span>
                      <strong>{source.title}</strong>
                    </div>
                    <div className="knowledge-card-meta">
                      <span>{source.metadata.role || 'General role'}</span>
                      <span>{source.metadata.category || 'General category'}</span>
                    </div>
                    <p className="review-feedback knowledge-preview">{source.content}</p>
                    <div className="knowledge-card-actions">
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => beginEditing(source)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="secondary-button danger-button"
                        onClick={() => void handleDeleteKnowledge(source)}
                      >
                        Delete
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </article>
        </div>
      </section>
    </section>
  )
}
