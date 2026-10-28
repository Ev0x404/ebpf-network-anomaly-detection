import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import { Activity, RefreshCw, CheckCircle, XCircle, Globe, Server } from 'lucide-react'

const SERVICE_ICONS = {
  n8n:           <Globe size={18} />,
  ollama:        <Server size={18} />,
  'docker:n8n':  <Globe size={18} />,
  'docker:ollama': <Server size={18} />,
}

export default function ServicesPage() {
  const [items, setItems]     = useState([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    await apiGet('/api/services/status').then(setItems).catch(() => {})
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const onlineCount = items.filter(s => s.running).length

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Services</h1>
          <p className="page-subtitle">
            {loading ? 'Vérification…' : `${onlineCount}/${items.length} service${items.length !== 1 ? 's' : ''} en ligne`}
          </p>
        </div>
        <button className="btn btn-ghost" onClick={load} disabled={loading}>
          <RefreshCw className={loading ? 'spin' : ''} />
          Actualiser
        </button>
      </div>

      {/* Summary */}
      {!loading && items.length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
          <span className={`badge ${onlineCount === items.length ? 'badge-green' : onlineCount > 0 ? 'badge-orange' : 'badge-red'}`}>
            {onlineCount === items.length ? '✓ Tous opérationnels' : onlineCount > 0 ? `${onlineCount} / ${items.length} en ligne` : 'Tous hors ligne'}
          </span>
        </div>
      )}

      {/* Cards */}
      {loading ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 14 }}>
          {[0,1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 120 }} />)}
        </div>
      ) : items.length === 0 ? (
        <div className="card empty" style={{ padding: '60px 20px' }}>
          <Activity />
          <p>Aucun service configuré</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 14 }}>
          {items.map(item => (
            <div key={item.name} className={`service-card ${item.running ? 'is-online' : 'is-offline'}`}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                  <div style={{
                    width: 34, height: 34,
                    borderRadius: 8,
                    background: item.running ? 'rgba(0,255,136,0.08)' : 'rgba(255,68,102,0.07)',
                    border: `1px solid ${item.running ? 'rgba(0,255,136,0.18)' : 'rgba(255,68,102,0.15)'}`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: item.running ? 'var(--green)' : 'var(--red)',
                    flexShrink: 0,
                  }}>
                    {SERVICE_ICONS[item.name] ?? <Activity size={18} />}
                  </div>
                  <span style={{ fontWeight: 600, fontSize: 14 }}>{item.name}</span>
                </div>

                {item.running
                  ? <CheckCircle size={16} style={{ color: 'var(--green)', flexShrink: 0 }} />
                  : <XCircle    size={16} style={{ color: 'var(--red)',   flexShrink: 0 }} />}
              </div>

              {/* Status badge */}
              <span className={`badge ${item.running ? 'badge-green' : 'badge-red'}`} style={{ alignSelf: 'flex-start' }}>
                <span className={`status-dot ${item.running ? 'online' : 'offline'}`} />
                {item.running ? 'En ligne' : 'Hors ligne'}
              </span>

              {/* URL */}
              {item.detail && (
                <p style={{ fontSize: 11, color: 'var(--text-disabled)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.detail}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
