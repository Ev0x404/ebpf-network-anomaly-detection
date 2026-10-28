import { useCallback, useEffect, useState } from 'react'
import { apiDelete, apiGet } from '../api/client'
import { Shield, RefreshCw, Search, X, Trash2, ListX } from 'lucide-react'

function SeverityBadge({ severity }) {
  const map = { critical: 'badge-red', high: 'badge-orange', medium: 'badge-yellow', low: 'badge-cyan' }
  return <span className={`badge ${map[severity?.toLowerCase()] ?? 'badge-gray'}`}>{severity ?? '—'}</span>
}

function ScoreBar({ score }) {
  if (score == null) return <span className="muted">—</span>
  const pct = Math.min(100, score * 100)
  const color = pct > 80 ? 'var(--red)' : pct > 50 ? 'var(--orange)' : 'var(--cyan)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ width: 60, height: 4, background: 'var(--surface)', borderRadius: 99, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 99 }} />
      </div>
      <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{score.toFixed(2)}</span>
    </div>
  )
}

export default function DetectionsPage() {
  const [items, setItems]             = useState([])
  const [detectedIps, setDetectedIps] = useState([])
  const [loading, setLoading]         = useState(true)
  const [search, setSearch]           = useState('')
  const [filter, setFilter]           = useState('all')
  const [deletingIp, setDeletingIp]   = useState(null)
  const [clearing, setClearing]       = useState(false)
  const [error, setError]             = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [detections, ips] = await Promise.all([
        apiGet('/api/detections'),
        apiGet('/api/detections/ips'),
      ])
      setItems(detections)
      setDetectedIps(ips)
    } catch {
      setError('Impossible de charger les détections')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [])

  const handleDeleteIp = async (ip) => {
    if (!window.confirm(`Supprimer toutes les détections associées à ${ip} ?`)) return

    setDeletingIp(ip)
    setError(null)
    try {
      await apiDelete(`/api/detections/ips/${encodeURIComponent(ip)}`)
      setDetectedIps(prev => prev.filter(item => item.src_ip !== ip))
      setItems(prev => prev.filter(item => item.src_ip !== ip))
    } catch (e) {
      setError(`Impossible de supprimer ${ip} : ${e.message}`)
    } finally {
      setDeletingIp(null)
    }
  }

  const handleClear = async () => {
    if (!window.confirm('Supprimer toutes les détections enregistrées ?')) return

    setClearing(true)
    setError(null)
    try {
      await apiDelete('/api/detections')
      setDetectedIps([])
      setItems([])
    } catch (e) {
      setError(`Impossible de vider les détections : ${e.message}`)
    } finally {
      setClearing(false)
    }
  }

  const severities = ['all', 'critical', 'high', 'medium', 'low']

  const filtered = items.filter(it => {
    const matchSev = filter === 'all' || it.severity?.toLowerCase() === filter
    const q = search.toLowerCase()
    const matchSearch = !q || [it.src_ip, it.type, it.severity, it.detail]
      .some(v => v?.toLowerCase().includes(q))
    return matchSev && matchSearch
  })

  const counts = { critical: 0, high: 0, medium: 0, low: 0 }
  items.forEach(it => {
    const s = it.severity?.toLowerCase()
    if (s in counts) counts[s]++
  })

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Détections</h1>
          <p className="page-subtitle">
            {items.length} événement{items.length !== 1 ? 's' : ''} · {detectedIps.length} IP{detectedIps.length !== 1 ? 's' : ''} détectée{detectedIps.length !== 1 ? 's' : ''}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn btn-ghost" onClick={handleClear} disabled={loading || clearing || items.length === 0}>
            <ListX size={14} />
            {clearing ? '…' : 'Clear'}
          </button>
          <button className="btn btn-ghost" onClick={load} disabled={loading}>
            <RefreshCw className={loading ? 'spin' : ''} />
            Actualiser
          </button>
        </div>
      </div>

      {error && (
        <div className="card" style={{ color: 'var(--red)', marginBottom: 16 }}>{error}</div>
      )}

      {/* Summary badges */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 18, flexWrap: 'wrap' }}>
        {counts.critical > 0 && <span className="badge badge-red">🔴 {counts.critical} critiques</span>}
        {counts.high     > 0 && <span className="badge badge-orange">🟠 {counts.high} hauts</span>}
        {counts.medium   > 0 && <span className="badge badge-yellow">🟡 {counts.medium} moyens</span>}
        {counts.low      > 0 && <span className="badge badge-cyan">🔵 {counts.low} bas</span>}
        {items.length === 0 && !loading && <span className="badge badge-green">Aucune détection</span>}
      </div>

      <div className="card" style={{ marginBottom: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginBottom: 14 }}>
          <div>
            <h2 style={{ fontSize: 15, margin: 0 }}>IPs détectées</h2>
            <p className="muted" style={{ fontSize: 12, margin: '4px 0 0' }}>
              Liste agrégée depuis l'historique des détections
            </p>
          </div>
          <span className="badge badge-violet">{detectedIps.length} IP{detectedIps.length !== 1 ? 's' : ''}</span>
        </div>

        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[0,1,2].map(i => <div key={i} className="skeleton" style={{ height: 36 }} />)}
          </div>
        ) : detectedIps.length === 0 ? (
          <div className="empty"><Shield /><p>Aucune IP détectée</p></div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>IP source</th>
                  <th>Événements</th>
                  <th>Dernier type</th>
                  <th>Sévérité max</th>
                  <th>Dernière vue</th>
                  <th>Détail</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {detectedIps.map(item => (
                  <tr key={item.src_ip}>
                    <td className="mono" style={{ fontWeight: 600 }}>{item.src_ip}</td>
                    <td>{item.count}</td>
                    <td><span className="badge badge-violet">{item.latest_type ?? '—'}</span></td>
                    <td><SeverityBadge severity={item.max_severity} /></td>
                    <td className="muted mono" style={{ whiteSpace: 'nowrap' }}>{item.last_seen ?? '—'}</td>
                    <td className="muted" style={{ maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.latest_detail ?? '—'}
                    </td>
                    <td>
                      <button
                        className="btn btn-ghost"
                        title={`Supprimer ${item.src_ip} de la liste`}
                        style={{ padding: '4px 8px', color: 'var(--red)' }}
                        onClick={() => handleDeleteIp(item.src_ip)}
                        disabled={deletingIp === item.src_ip}
                      >
                        <Trash2 size={13} />
                        {deletingIp === item.src_ip ? '…' : ''}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        {/* Toolbar */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          {/* Search */}
          <div style={{ position: 'relative', flex: 1, minWidth: 180 }}>
            <Search size={13} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-disabled)', pointerEvents: 'none' }} />
            <input
              placeholder="Rechercher…"
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

          {/* Severity filter */}
          <div style={{ display: 'flex', gap: 4 }}>
            {severities.map(s => (
              <button
                key={s}
                onClick={() => setFilter(s)}
                className={`btn ${filter === s ? 'btn-primary' : 'btn-ghost'}`}
                style={{ padding: '5px 10px', fontSize: 11 }}
              >
                {s === 'all' ? 'Tous' : s}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[0,1,2,3,4].map(i => <div key={i} className="skeleton" style={{ height: 36 }} />)}
          </div>
        ) : filtered.length === 0 ? (
          <div className="empty"><Shield /><p>Aucune détection{search ? ' pour cette recherche' : ''}</p></div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Horodatage</th>
                  <th>IP source</th>
                  <th>Type</th>
                  <th>Sévérité</th>
                  <th>Score</th>
                  <th>Détail</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((it, idx) => (
                  <tr key={idx}>
                    <td className="muted mono" style={{ whiteSpace: 'nowrap' }}>{it.timestamp ?? '—'}</td>
                    <td className="mono">{it.src_ip ?? '—'}</td>
                    <td><span className="badge badge-violet">{it.type ?? '—'}</span></td>
                    <td><SeverityBadge severity={it.severity} /></td>
                    <td><ScoreBar score={it.score} /></td>
                    <td className="muted" style={{ maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {it.detail ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {filtered.length > 0 && (
          <p style={{ marginTop: 12, fontSize: 11, color: 'var(--text-disabled)' }}>
            {filtered.length} résultat{filtered.length !== 1 ? 's' : ''}
            {filter !== 'all' || search ? ` (filtrés sur ${items.length})` : ''}
          </p>
        )}
      </div>
    </div>
  )
}
