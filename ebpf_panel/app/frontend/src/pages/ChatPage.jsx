import { useState, useRef, useEffect, useCallback } from 'react'
import { apiGet, apiPost, apiPut, apiDelete } from '../api/client'
import {
  Send, MessageSquare, Trash2, Plus, Bot,
  User, AlertCircle, Pencil, Check, X,
} from 'lucide-react'

// ── helpers ───────────────────────────────────────────────────────────────────

function formatDate(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const now = new Date()
  const diffDays = Math.floor((now - d) / 86400000)
  if (diffDays === 0) return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  if (diffDays === 1) return 'Hier'
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })
}

// ── ThinkingDots ──────────────────────────────────────────────────────────────

function ThinkingDots() {
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
      {[0, 1, 2].map(i => (
        <span key={i} style={{
          width: 6, height: 6, borderRadius: '50%',
          background: 'var(--violet)', display: 'inline-block',
          animation: `dot-pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
        }} />
      ))}
    </span>
  )
}

// ── ChatPage ──────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId]           = useState(null)
  const [messages, setMessages]           = useState([])
  const [input, setInput]                 = useState('')
  const [loading, setLoading]             = useState(false)
  const [loadingConvs, setLoadingConvs]   = useState(true)
  const [editingId, setEditingId]         = useState(null)
  const [editTitle, setEditTitle]         = useState('')
  const [error, setError]                 = useState(null)
  const [models, setModels]               = useState([])
  const [selectedModel, setSelectedModel] = useState('')
  const [deletingIds, setDeletingIds]     = useState({})

  const messagesRef = useRef(null)
  const inputRef    = useRef(null)
  const activeIdRef = useRef(activeId)
  const messagesSnapshotRef = useRef(messages)
  const pendingSendRef = useRef(0)

  useEffect(() => { activeIdRef.current = activeId }, [activeId])
  useEffect(() => { messagesSnapshotRef.current = messages }, [messages])

  // ── scroll to bottom ───────────────────────────────────────────────────────
  useEffect(() => {
    if (messagesRef.current)
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
  }, [messages, loading])

  // ── load conversations list ────────────────────────────────────────────────
  const loadConversations = useCallback(async () => {
    setLoadingConvs(true)
    try {
      const list = await apiGet('/api/chat/conversations')
      setConversations(list)
    } catch {
      setConversations([])
    } finally {
      setLoadingConvs(false)
    }
  }, [])

  useEffect(() => { loadConversations() }, [loadConversations])

  // ── load models ────────────────────────────────────────────────────────────
  useEffect(() => {
    apiGet('/api/chat/models').then(list => {
      setModels(list)
      if (list.length > 0) setSelectedModel(list[0])
    }).catch(() => {})
  }, [])

  // ── open conversation ──────────────────────────────────────────────────────
  async function openConversation(id) {
    if (id === activeId) return
    pendingSendRef.current += 1
    setActiveId(id)
    activeIdRef.current = id
    setLoading(false)
    setError(null)
    try {
      const conv = await apiGet(`/api/chat/conversations/${id}`)
      setMessages(conv.messages ?? [])
    } catch {
      setMessages([])
    }
  }

  // ── new conversation ───────────────────────────────────────────────────────
  async function newConversation() {
    try {
      pendingSendRef.current += 1
      const conv = await apiPost('/api/chat/conversations', {})
      setConversations(prev => [conv, ...prev])
      setActiveId(conv.id)
      activeIdRef.current = conv.id
      setLoading(false)
      setMessages([])
      setError(null)
    } catch {
      setError('Impossible de créer une conversation.')
    }
  }

  // ── delete conversation ────────────────────────────────────────────────────
  async function deleteConversation(e, id, title) {
    e.stopPropagation()
    if (deletingIds[id]) return

    const confirmed = window.confirm(`Supprimer définitivement la conversation "${title}" ?`)
    if (!confirmed) return

    setDeletingIds(prev => ({ ...prev, [id]: true }))
    setError(null)
    try {
      await apiDelete(`/api/chat/conversations/${id}`)
      setConversations(prev => prev.filter(c => c.id !== id))
      if (activeId === id) {
        pendingSendRef.current += 1
        setActiveId(null)
        activeIdRef.current = null
        setLoading(false)
        setMessages([])
      }
      await loadConversations()
    } catch (e) {
      const detail = (() => {
        try { return JSON.parse(e.message)?.detail ?? e.message }
        catch { return e.message }
      })()
      setError(`Suppression impossible : ${detail}`)
    } finally {
      setDeletingIds(prev => {
        const next = { ...prev }
        delete next[id]
        return next
      })
    }
  }

  // ── rename conversation ────────────────────────────────────────────────────
  async function saveTitle(id) {
    if (!editTitle.trim()) return
    await apiPut(`/api/chat/conversations/${id}/title`, { title: editTitle })
    setConversations(prev => prev.map(c => c.id === id ? { ...c, title: editTitle } : c))
    setEditingId(null)
  }

  // ── send message ───────────────────────────────────────────────────────────
  async function send() {
    const content = input.trim()
    if (!content || loading) return

    // On résout l'ID localement pour ne pas dépendre du state React
    // qui ne se met à jour qu'au prochain rendu.
    let convId = activeId
    if (!convId) {
      try {
        const conv = await apiPost('/api/chat/conversations', {})
        setConversations(prev => [conv, ...prev])
        setActiveId(conv.id)
        activeIdRef.current = conv.id
        setMessages([])
        setError(null)
        convId = conv.id
      } catch {
        setError('Impossible de créer une conversation.')
        return
      }
    }

    const baseMessageCount = messagesSnapshotRef.current.length
    const sendId = pendingSendRef.current + 1
    pendingSendRef.current = sendId

    const isCurrentSend = () => (
      pendingSendRef.current === sendId && activeIdRef.current === convId
    )

    let pollTimer = null
    let syncedFromServer = false

    const syncIfAssistantSaved = async () => {
      if (!isCurrentSend()) {
        if (pollTimer) window.clearInterval(pollTimer)
        return false
      }

      const conv = await apiGet(`/api/chat/conversations/${convId}`)
      const serverMessages = conv.messages ?? []
      for (let i = baseMessageCount; i < serverMessages.length - 1; i += 1) {
        const userMessage = serverMessages[i]
        const assistantMessage = serverMessages[i + 1]
        if (
          userMessage?.role === 'user' &&
          userMessage?.content === content &&
          assistantMessage?.role === 'assistant'
        ) {
          syncedFromServer = true
          if (pollTimer) window.clearInterval(pollTimer)
          if (isCurrentSend()) {
            setMessages(serverMessages)
            setLoading(false)
            setError(null)
            loadConversations()
          }
          return true
        }
      }
      return false
    }

    setMessages(prev => [...prev, { role: 'user', content, ts: Date.now() / 1000 }])
    setInput('')
    setLoading(true)
    setError(null)

    try {
      pollTimer = window.setInterval(() => {
        syncIfAssistantSaved().catch(() => {})
      }, 1200)

      const res = await apiPost(`/api/chat/conversations/${convId}/message`, { content, model: selectedModel || undefined })
      if (pollTimer) window.clearInterval(pollTimer)

      const synced = await syncIfAssistantSaved().catch(() => false)
      if (!synced && !syncedFromServer && isCurrentSend()) {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: res.content ?? res.response ?? '',
          ts: Date.now() / 1000,
        }])
      }
      loadConversations()
    } catch (e) {
      if (pollTimer) window.clearInterval(pollTimer)
      if (syncedFromServer) return

      const detail = (() => {
        try { return JSON.parse(e.message)?.detail ?? e.message }
        catch { return e.message }
      })()
      if (isCurrentSend()) {
        setError(detail)
        setMessages(prev => prev.slice(0, -1))
        setInput(content)
      }
    } finally {
      if (isCurrentSend()) setLoading(false)
    }
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  const activeConv = conversations.find(c => c.id === activeId)

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 14, height: 'calc(100vh - 90px)' }}>
      <style>{`
        @keyframes dot-pulse {
          0%, 100% { opacity: 0.25; transform: scale(0.8); }
          50%       { opacity: 1;   transform: scale(1.15); }
        }
      `}</style>

      {/* ── LEFT: conversations sidebar ─────────────────────────────────────── */}
      <div className="card" style={{ padding: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Header */}
        <div style={{ padding: '14px 14px 10px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
            Conversations
          </span>
          <button className="btn btn-primary" style={{ padding: '5px 10px', fontSize: 11 }} onClick={newConversation}>
            <Plus size={13} /> Nouvelle
          </button>
        </div>

        {/* List */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
          {loadingConvs ? (
            [0,1,2].map(i => <div key={i} className="skeleton" style={{ height: 48, marginBottom: 4 }} />)
          ) : conversations.length === 0 ? (
            <div className="empty" style={{ padding: '32px 12px' }}>
              <MessageSquare />
              <p style={{ fontSize: 12 }}>Aucune conversation</p>
            </div>
          ) : (
            conversations.map(c => (
              <div
                key={c.id}
                onClick={() => openConversation(c.id)}
                className={`list-item ${c.id === activeId ? 'selected' : ''}`}
                style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 3, padding: '8px 10px', marginBottom: 2 }}
              >
                {editingId === c.id ? (
                  <div style={{ display: 'flex', gap: 4, width: '100%' }} onClick={e => e.stopPropagation()}>
                    <input
                      value={editTitle}
                      onChange={e => setEditTitle(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') saveTitle(c.id); if (e.key === 'Escape') setEditingId(null) }}
                      style={{ flex: 1, fontSize: 12, padding: '3px 6px' }}
                      autoFocus
                    />
                    <button onClick={() => saveTitle(c.id)} style={{ background: 'none', border: 'none', color: 'var(--green)', cursor: 'pointer', padding: 2 }}><Check size={13} /></button>
                    <button onClick={() => setEditingId(null)} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: 2 }}><X size={13} /></button>
                  </div>
                ) : (
                  <div style={{ display: 'flex', alignItems: 'center', width: '100%', gap: 6 }}>
                    <span style={{ flex: 1, fontSize: 12, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {c.title}
                    </span>
                    <button onClick={e => { e.stopPropagation(); setEditingId(c.id); setEditTitle(c.title) }}
                      style={{ background: 'none', border: 'none', color: 'var(--text-disabled)', cursor: 'pointer', padding: 2, opacity: 0, transition: '0.1s' }}
                      className="conv-edit-btn">
                      <Pencil size={11} />
                    </button>
                    <button
                      onClick={e => deleteConversation(e, c.id, c.title)}
                      disabled={Boolean(deletingIds[c.id])}
                      title="Supprimer la conversation"
                      style={{ background: 'none', border: 'none', color: 'var(--text-disabled)', cursor: deletingIds[c.id] ? 'wait' : 'pointer', padding: 2, opacity: deletingIds[c.id] ? 0.45 : 1 }}
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                )}
                <span style={{ fontSize: 10, color: 'var(--text-disabled)' }}>
                  {c.message_count} msg · {formatDate(c.updated_at)}
                </span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── RIGHT: chat ──────────────────────────────────────────────────────── */}
      <div className="card" style={{ padding: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Header */}
        <div style={{ padding: '12px 18px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          <h1 className="page-title" style={{ fontSize: 16, marginBottom: 2 }}>
            {activeConv ? activeConv.title : 'Chat IA'}
          </h1>
          <p className="page-subtitle">Assistant Ollama local pour l'analyse eBPF</p>
        </div>

        {/* Error banner */}
        {error && (
          <div style={{ margin: '10px 16px 0', padding: '10px 14px', borderRadius: 8, background: 'rgba(255,68,102,0.08)', border: '1px solid rgba(255,68,102,0.2)', color: 'var(--red)', fontSize: 12, display: 'flex', alignItems: 'flex-start', gap: 8 }}>
            <AlertCircle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
            {error}
          </div>
        )}

        {/* Messages */}
        <div className="chat-messages" ref={messagesRef} style={{ flex: 1 }}>
          {!activeId ? (
            <div className="empty" style={{ flex: 1 }}>
              <MessageSquare />
              <p style={{ fontWeight: 500 }}>Sélectionne ou crée une conversation</p>
              <button className="btn btn-primary" style={{ marginTop: 8 }} onClick={newConversation}>
                <Plus size={13} /> Nouvelle conversation
              </button>
            </div>
          ) : messages.length === 0 && !loading ? (
            <div className="empty" style={{ flex: 1 }}>
              <Bot />
              <p>Pose ta première question</p>
            </div>
          ) : (
            <>
              {messages.map((m, i) => (
                <div key={i} className={`bubble ${m.role}`}>
                  <div style={{ fontSize: 10, color: m.role === 'assistant' ? 'var(--violet)' : 'var(--cyan)', marginBottom: 5, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: 5 }}>
                    {m.role === 'assistant' ? <Bot size={11} /> : <User size={11} />}
                    {m.role === 'assistant' ? 'Ollama IA' : 'Toi'}
                  </div>
                  {m.content}
                </div>
              ))}
              {loading && (
                <div className="bubble thinking">
                  <div style={{ fontSize: 10, color: 'var(--violet)', marginBottom: 5, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: 5 }}>
                    <Bot size={11} /> Ollama IA
                  </div>
                  <ThinkingDots />
                </div>
              )}
            </>
          )}
        </div>

        {/* Input */}
        <div className="chat-input-area" style={{ flexDirection: 'column', gap: 8 }}>
          {/* Model selector row */}
          {models.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, color: 'var(--text-secondary)', flexShrink: 0 }}>Modèle :</span>
              <select
                value={selectedModel}
                onChange={e => setSelectedModel(e.target.value)}
                style={{
                  fontSize: 11, padding: '3px 8px', borderRadius: 6,
                  background: 'var(--surface)', border: '1px solid var(--border)',
                  color: 'var(--text-primary)', cursor: 'pointer',
                }}
              >
                {models.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
          )}
          {models.length === 0 && (
            <div style={{ fontSize: 11, color: 'var(--red)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <AlertCircle size={12} /> Ollama inaccessible ou aucun modèle installé
            </div>
          )}
          {/* Message row */}
          <div style={{ display: 'flex', gap: 10, width: '100%' }}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder={activeId ? 'Écris un message… (Entrée pour envoyer)' : 'Crée ou sélectionne une conversation…'}
              rows={2}
              disabled={!activeId}
              style={{ flex: 1, minHeight: 56, maxHeight: 140 }}
            />
            <button
              className="btn btn-primary"
              onClick={send}
              disabled={loading || !input.trim() || !activeId}
              style={{ alignSelf: 'flex-end', paddingLeft: 18, paddingRight: 18 }}
            >
              <Send size={14} />
              Envoyer
            </button>
          </div>
        </div>
      </div>

      <style>{`
        .list-item:hover .conv-edit-btn { opacity: 1 !important; }
      `}</style>
    </div>
  )
}
