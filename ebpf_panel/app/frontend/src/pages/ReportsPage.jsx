import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import { FileText, RefreshCw, Search, X, Clock, HardDrive } from 'lucide-react'

function formatSize(bytes) {
  if (bytes < 1024)       return `${bytes} o`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`
}

function formatDate(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleDateString('fr-FR', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

export default function ReportsPage() {
  const [reports, setReports]     = useState([])
  const [selected, setSelected]   = useState(null)
  const [content, setContent]     = useState('')
  const [loading, setLoading]     = useState(true)
  const [loadingContent, setLoadingContent] = useState(false)
  const [search, setSearch]       = useState('')
  const [error, setError]         = useState(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const list = await apiGet('/api/reports')
      setReports(list)
    } catch (e) {
      setReports([])
      setError(e.message || 'Impossible de charger les rapports.')
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  async function openReport(r) {
    setSelected(r)
    setLoadingContent(true)
    setError(null)
    try {
      const encodedName = r.name.split('/').map(encodeURIComponent).join('/')
      const res  = await fetch(`/api/reports/${encodedName}`)
      if (!res.ok) throw new Error(await res.text())
      const text = await res.text()
      setContent(text)
    } catch (e) {
      setContent('Erreur lors du chargement du rapport.')
      setError(e.message || 'Impossible de charger ce rapport.')
    } finally {
      setLoadingContent(false)
    }
  }

  const filtered = reports.filter(r =>
    !search || r.name.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Rapports</h1>
          <p className="page-subtitle">{reports.length} rapport{reports.length !== 1 ? 's' : ''} disponible{reports.length !== 1 ? 's' : ''}</p>
        </div>
        <button className="btn btn-ghost" onClick={load} disabled={loading}>
          <RefreshCw className={loading ? 'spin' : ''} />
          Actualiser
        </button>
      </div>

      {error && (
        <div style={{ marginBottom: 12, padding: '10px 14px', borderRadius: 8, background: 'rgba(255,68,102,0.08)', border: '1px solid rgba(255,68,102,0.2)', color: 'var(--red)', fontSize: 12 }}>
          {error}
        </div>
      )}

      <div className="split">
        {/* Left — list */}
        <div className="card" style={{ padding: 14 }}>
          {/* Search */}
          <div style={{ position: 'relative', marginBottom: 12 }}>
            <Search size={13} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-disabled)', pointerEvents: 'none' }} />
            <input
              placeholder="Filtrer les rapports…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ paddingLeft: 32, paddingRight: search ? 32 : 11 }}
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: 2, display: 'flex' }}
              >
                <X size={12} />
              </button>
            )}
          </div>

          {loading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[0,1,2,3,4].map(i => <div key={i} className="skeleton" style={{ height: 44 }} />)}
            </div>
          ) : filtered.length === 0 ? (
            <div className="empty"><FileText /><p>Aucun rapport</p></div>
          ) : (
            filtered.map(r => (
              <button
                key={r.name}
                onClick={() => openReport(r)}
                className={`list-item ${selected?.name === r.name ? 'selected' : ''}`}
              >
                <FileText size={13} style={{ flexShrink: 0 }} />
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <div style={{ fontSize: 12, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.name}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-disabled)', display: 'flex', gap: 8, marginTop: 2 }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                      <HardDrive size={10} />{formatSize(r.size_bytes)}
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                      <Clock size={10} />{formatDate(r.modified_at)}
                    </span>
                  </div>
                </div>
              </button>
            ))
          )}
        </div>

        {/* Right — content */}
        <div className="card" style={{ minHeight: 400 }}>
          {!selected ? (
            <div className="empty" style={{ height: '100%', minHeight: 300 }}>
              <FileText />
              <p>Sélectionne un rapport</p>
              <p style={{ fontSize: 11 }}>Le contenu s'affichera ici</p>
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, gap: 10, flexWrap: 'wrap' }}>
                <div>
                  <p style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)' }}>{selected.name}</p>
                  <p style={{ fontSize: 11, color: 'var(--text-disabled)', marginTop: 2 }}>
                    {formatSize(selected.size_bytes)} · {formatDate(selected.modified_at)}
                  </p>
                </div>
              </div>
              {loadingContent ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {[0,1,2,3,4,5].map(i => <div key={i} className="skeleton" style={{ height: 18 }} />)}
                </div>
              ) : (
                <div className="code-block" style={{ color: 'var(--text-primary)', maxHeight: 560 }}>
                  {content}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
