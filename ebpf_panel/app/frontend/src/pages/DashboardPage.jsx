import { useEffect, useState, useRef } from 'react'
import { apiGet } from '../api/client'
import { FileText, Shield, Activity, RefreshCw, AlertTriangle } from 'lucide-react'

// ── Rotating arc card (StudyForge style) ──────────────────────────────────────
// Draws a glowing arc that travels around the rounded-rect border.
const RADIUS   = 12   // matches border-radius in CSS
const ARC_FRAC = 0.22 // visible arc = 22% of perimeter
const CONFIGS = [
  { color: '#00f0ff', duration: 7,   startFrac: 0 },    // cyan   – Rapports
  { color: '#ff4466', duration: 8,   startFrac: 0.33 }, // red    – Détections
  { color: '#00ff88', duration: 8.5, startFrac: 0.66 }, // green  – Services
]

function perimeter(w, h, r) {
  return 2 * (w - 2 * r) + 2 * (h - 2 * r) + 2 * Math.PI * r
}

function GlowCard({ children, index }) {
  const wrapRef = useRef(null)
  const [dims, setDims] = useState(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const obs = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setDims({ w: Math.round(width), h: Math.round(height) })
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  const cfg = CONFIGS[index % CONFIGS.length]
  let arcLen = 0, gapLen = 0, fromOffset = '0', toOffset = '0'

  if (dims) {
    const p    = perimeter(dims.w - 2, dims.h - 2, RADIUS)
    arcLen     = p * ARC_FRAC
    gapLen     = p - arcLen
    const init = -(cfg.startFrac * p)
    fromOffset = `${init}`
    toOffset   = `${init - p}`
  }

  return (
    <div ref={wrapRef} style={{ position: 'relative', borderRadius: RADIUS, height: '100%' }}>
      {/* SVG animated border */}
      {dims && (
        <svg
          aria-hidden="true"
          style={{
            position: 'absolute', inset: 0,
            width: '100%', height: '100%',
            pointerEvents: 'none', zIndex: 10,
            overflow: 'visible',
          }}
          viewBox={`0 0 ${dims.w} ${dims.h}`}
        >
          <defs>
            {/* Extended filter region so glow doesn't clip */}
            <filter id={`glow-${index}`} x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Static dim base border */}
          <rect x={1} y={1} width={dims.w - 2} height={dims.h - 2}
            rx={RADIUS} ry={RADIUS} fill="none"
            stroke={cfg.color} strokeWidth="1" opacity="0.18" />

          {/* Travelling arc — thick + double-blur for strong glow */}
          <rect x={1} y={1} width={dims.w - 2} height={dims.h - 2}
            rx={RADIUS} ry={RADIUS} fill="none"
            stroke={cfg.color} strokeWidth="3" strokeLinecap="round"
            strokeDasharray={`${arcLen} ${gapLen}`}
            filter={`url(#glow-${index})`} opacity="1">
            <animate
              attributeName="stroke-dashoffset"
              from={fromOffset} to={toOffset}
              dur={`${cfg.duration}s`}
              repeatCount="indefinite"
            />
          </rect>
        </svg>
      )}

      {/* Card content */}
      <div style={{
        position: 'relative', zIndex: 11,
        background: 'rgba(18,18,28,0.92)',
        borderRadius: RADIUS, padding: '18px 20px',
        height: '100%', display: 'flex', flexDirection: 'column', gap: 6,
      }}>
        {children}
      </div>
    </div>
  )
}

// ── SeverityBadge ──────────────────────────────────────────────────────────────
function SeverityBadge({ severity }) {
  const map = { critical: 'badge-red', high: 'badge-orange', medium: 'badge-yellow', low: 'badge-cyan' }
  return <span className={`badge ${map[severity?.toLowerCase()] ?? 'badge-gray'}`}>{severity ?? '—'}</span>
}

// ── DashboardPage ──────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const [reports, setReports]       = useState([])
  const [detections, setDetections] = useState([])
  const [services, setServices]     = useState([])
  const [loading, setLoading]       = useState(true)

  const load = async () => {
    setLoading(true)
    await Promise.allSettled([
      apiGet('/api/reports').then(setReports).catch(() => {}),
      apiGet('/api/detections').then(setDetections).catch(() => {}),
      apiGet('/api/services/status').then(setServices).catch(() => {}),
    ])
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const servicesOk    = services.filter(s => s.running).length
  const criticalCount = detections.filter(d => d.severity?.toLowerCase() === 'critical').length
  const allOk         = servicesOk === services.length && services.length > 0

  const CARDS = [
    {
      label: 'Rapports',
      value: loading ? '—' : reports.length,
      sub: 'fichiers analysés',
      icon: <FileText size={18} />,
      iconColor: 'var(--cyan)',
    },
    {
      label: 'Détections',
      value: loading ? '—' : detections.length,
      sub: criticalCount > 0 ? `${criticalCount} critiques` : 'aucune critique',
      subColor: criticalCount > 0 ? 'var(--red)' : 'var(--text-secondary)',
      icon: criticalCount > 0 ? <AlertTriangle size={18} /> : <Shield size={18} />,
      iconColor: criticalCount > 0 ? 'var(--red)' : 'var(--green)',
    },
    {
      label: 'Services',
      value: loading ? '—' : servicesOk,
      unit: loading ? '' : `/ ${services.length}`,
      sub: loading ? '…' : allOk ? 'tous opérationnels' : 'dégradé',
      subColor: allOk ? 'var(--green)' : 'var(--orange)',
      icon: <Activity size={18} />,
      iconColor: allOk ? 'var(--green)' : 'var(--orange)',
    },
  ]

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Vue d'ensemble du système eBPF</p>
        </div>
        <button className="btn btn-ghost" onClick={load} disabled={loading}>
          <RefreshCw className={loading ? 'spin' : ''} />
          Actualiser
        </button>
      </div>

      {/* Stat cards with animated arcs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12, marginBottom: 22 }}>
        {CARDS.map((card, i) => (
          <GlowCard key={i} index={i}>
            <div className="stat-label">{card.label}</div>
            <div className="stat-value">
              {card.value}
              {card.unit && <span className="unit">{card.unit}</span>}
            </div>
            <div className="stat-sub" style={card.subColor ? { color: card.subColor } : undefined}>
              {card.sub}
            </div>
            <div style={{ position: 'absolute', top: 14, right: 14, color: card.iconColor, opacity: 0.65 }}>
              {card.icon}
            </div>
          </GlowCard>
        ))}
      </div>

      {/* Bottom grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        {/* Recent detections */}
        <div className="card">
          <p className="section-title">Dernières détections</p>
          {loading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[0,1,2].map(i => <div key={i} className="skeleton" style={{ height: 32 }} />)}
            </div>
          ) : detections.length === 0 ? (
            <div className="empty"><Shield /><p>Aucune détection</p></div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>IP source</th><th>Type</th><th>Sévérité</th></tr></thead>
                <tbody>
                  {detections.slice(0, 6).map((d, i) => (
                    <tr key={i}>
                      <td className="mono">{d.src_ip ?? '—'}</td>
                      <td className="muted">{d.type ?? '—'}</td>
                      <td><SeverityBadge severity={d.severity} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Recent reports */}
        <div className="card">
          <p className="section-title">Derniers rapports</p>
          {loading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[0,1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 30 }} />)}
            </div>
          ) : reports.length === 0 ? (
            <div className="empty"><FileText /><p>Aucun rapport</p></div>
          ) : (
            reports.slice(0, 6).map(r => (
              <div key={r.name} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 0', borderBottom: '1px solid var(--border)',
              }}>
                <FileText size={13} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
                <span style={{ fontSize: 12, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {r.name}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-disabled)', flexShrink: 0 }}>
                  {(r.size_bytes / 1024).toFixed(1)} Ko
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
