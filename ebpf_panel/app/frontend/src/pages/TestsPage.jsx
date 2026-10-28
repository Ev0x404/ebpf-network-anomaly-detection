import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api/client'
import { FlaskConical, Play, CheckCircle, XCircle, Terminal, Clock } from 'lucide-react'

function formatTs(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
}

export default function TestsPage() {
  const [tests, setTests]       = useState([])
  const [result, setResult]     = useState(null)
  const [running, setRunning]   = useState(null)
  const [history, setHistory]   = useState([])
  const [activeResult, setActiveResult] = useState(null)

  useEffect(() => {
    apiGet('/api/tests/catalog').then(setTests).catch(() => {})
    apiGet('/api/tests/history').then(h => setHistory([...h].reverse())).catch(() => {})
  }, [])

  async function runTest(id) {
    setRunning(id)
    setResult(null)
    try {
      const data = await apiPost('/api/tests/run', { test_id: id })
      setResult({ ...data, test_id: id })
      setActiveResult({ ...data, test_id: id })
      setHistory(h => [{ test_id: id, timestamp: Date.now() / 1000, ...data }, ...h])
    } catch (e) {
      setResult({ success: false, stdout: '', stderr: String(e), return_code: -1, test_id: id })
    } finally {
      setRunning(null)
    }
  }

  const testMap = Object.fromEntries(tests.map(t => [t.id, t]))

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Tests</h1>
          <p className="page-subtitle">Catalogue des tests réseau eBPF</p>
        </div>
      </div>

      {/* Test cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 14, marginBottom: 24 }}>
        {tests.map(t => {
          const isRunning = running === t.id
          const lastRun = history.find(h => h.test_id === t.id)
          return (
            <div key={t.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
                <div>
                  <p style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-primary)', marginBottom: 4 }}>{t.name}</p>
                  <p style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{t.description}</p>
                </div>
                <FlaskConical size={16} style={{ color: 'var(--violet)', flexShrink: 0, marginTop: 2 }} />
              </div>

              <div className="code-inline" style={{ display: 'block', padding: '6px 10px', fontSize: 11 }}>
                {t.command}
              </div>

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginTop: 'auto' }}>
                {lastRun ? (
                  <span style={{ fontSize: 11, color: 'var(--text-disabled)', display: 'flex', alignItems: 'center', gap: 4 }}>
                    <Clock size={11} />
                    {formatTs(lastRun.timestamp)}
                  </span>
                ) : <span />}

                <button
                  className="btn btn-primary"
                  onClick={() => runTest(t.id)}
                  disabled={running !== null}
                  style={{ marginLeft: 'auto' }}
                >
                  {isRunning
                    ? <><span className="spin" style={{ display: 'inline-block' }}>⟳</span> En cours…</>
                    : <><Play size={13} /> Lancer</>}
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Result panel */}
      {activeResult && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {activeResult.success
                ? <CheckCircle size={16} style={{ color: 'var(--green)' }} />
                : <XCircle size={16} style={{ color: 'var(--red)' }} />}
              <span style={{ fontWeight: 600, fontSize: 14 }}>
                {testMap[activeResult.test_id]?.name ?? activeResult.test_id}
              </span>
              <span className={`badge ${activeResult.success ? 'badge-green' : 'badge-red'}`}>
                {activeResult.success ? 'Succès' : 'Échec'}
              </span>
              <span className="badge badge-gray">code {activeResult.return_code}</span>
            </div>
            <button className="btn btn-ghost" style={{ fontSize: 11 }} onClick={() => setActiveResult(null)}>
              Fermer
            </button>
          </div>

          {activeResult.stdout && (
            <>
              <p style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Terminal size={12} /> stdout
              </p>
              <div className="code-block" style={{ marginBottom: 12 }}>{activeResult.stdout}</div>
            </>
          )}

          {activeResult.stderr && (
            <>
              <p style={{ fontSize: 11, color: 'var(--red)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Terminal size={12} /> stderr
              </p>
              <div className="code-block" style={{ borderColor: 'rgba(255,68,102,0.2)', color: 'var(--red)' }}>
                {activeResult.stderr}
              </div>
            </>
          )}
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="card">
          <p className="section-title">Historique d'exécution</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Test</th>
                  <th>Résultat</th>
                  <th>Code</th>
                </tr>
              </thead>
              <tbody>
                {history.slice(0, 20).map((h, i) => (
                  <tr key={i} style={{ cursor: 'pointer' }} onClick={() => setActiveResult(h)}>
                    <td className="muted mono">{formatTs(h.timestamp)}</td>
                    <td style={{ fontSize: 12 }}>{testMap[h.test_id]?.name ?? h.test_id}</td>
                    <td>
                      <span className={`badge ${h.success || h.return_code === 0 ? 'badge-green' : 'badge-red'}`}>
                        {h.success || h.return_code === 0 ? 'Succès' : 'Échec'}
                      </span>
                    </td>
                    <td className="mono muted">{h.return_code}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
