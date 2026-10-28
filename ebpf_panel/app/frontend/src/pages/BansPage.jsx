import { useEffect, useState, useCallback, useRef } from 'react'
import { apiGet, apiDelete } from '../api/client'
import { ShieldOff, RefreshCw, Unlock, KeyRound } from 'lucide-react'

function formatRemaining(seconds) {
  if (seconds <= 0) return 'Expiré'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m > 0 ? `${m}m ${s.toString().padStart(2, '0')}s` : `${s}s`
}

function TimerBar({ remaining, duration }) {
  const pct = duration > 0 ? Math.min(100, (remaining / duration) * 100) : 0
  const color = pct > 60 ? 'var(--red)' : pct > 25 ? 'var(--orange)' : 'var(--yellow)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ width: 80, height: 4, background: 'var(--surface)', borderRadius: 99, overflow: 'hidden', flexShrink: 0 }}>
        <div style={{
          width: `${pct}%`, height: '100%', background: color, borderRadius: 99,
          transition: 'width 1s linear',
        }} />
      </div>
      <span style={{ fontSize: 11, color: 'var(--text-secondary)', minWidth: 52, fontFamily: 'monospace' }}>
        {formatRemaining(remaining)}
      </span>
    </div>
  )
}

function SudoModal({ ip, onConfirm, onCancel }) {
  const [password, setPassword] = useState('')
  const [error, setError]       = useState(null)
  const [loading, setLoading]   = useState(false)
  const inputRef = useRef(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = await onConfirm(password)
      if (res?.bpftool === 'echec sudo') {
        setError(password
          ? 'Mot de passe sudo incorrect.'
          : 'Cache sudo expiré — veuillez saisir votre mot de passe.')
        setPassword('')
        setLoading(false)
        inputRef.current?.focus()
      }
    } catch (e) {
      setError(e.message)
      setLoading(false)
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div className="card" style={{ width: 360, padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <KeyRound size={18} style={{ color: 'var(--orange)' }} />
          <span style={{ fontWeight: 600 }}>Authentification sudo</span>
        </div>

        <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0 }}>
          Débannissement de <span className="mono" style={{ color: 'var(--text)' }}>{ip}</span>
          <br />Mot de passe sudo requis pour modifier la map eBPF.
          <br /><span style={{ fontSize: 11, color: 'var(--text-disabled)' }}>(Si vous n'avez pas de mot de passe sudo, laissez le champ vide.)</span>
        </p>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <input
            ref={inputRef}
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="Mot de passe sudo"
            autoComplete="current-password"
            style={{
              padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)',
              background: 'var(--surface)', color: 'var(--text)', fontSize: 13,
              outline: error ? '1px solid var(--red)' : 'none',
            }}
          />
          {error && <span style={{ fontSize: 12, color: 'var(--red)' }}>{error}</span>}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
            <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={loading}>
              Annuler
            </button>
            <button type="submit" className="btn btn-ghost"
              style={{ color: 'var(--orange)' }} disabled={loading}>
              <Unlock size={13} />
              {loading ? '…' : 'Débannir'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function BansPage() {
  const [bans, setBans]         = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [modal, setModal]       = useState(null)   // { ip } ou null

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiGet('/api/bans')
      setBans(data)
    } catch {
      setError('Impossible de charger les bans')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const poll = setInterval(() => {
      apiGet('/api/bans').then(setBans).catch(() => {})
    }, 5000)
    return () => clearInterval(poll)
  }, [load])

  useEffect(() => {
    const tick = setInterval(() => {
      setBans(prev => prev.map(b => ({ ...b, remaining: Math.max(0, b.remaining - 1) })))
    }, 1000)
    return () => clearInterval(tick)
  }, [])

  const handleUnban = async (password) => {
    const ip = modal.ip
    const res = await apiDelete(`/api/bans/${ip}`, { sudo_password: password })
    if (res?.bpftool !== 'echec sudo') {
      setBans(prev => prev.filter(b => b.ip !== ip))
      setModal(null)
    }
    return res
  }

  const activeBans  = bans.filter(b => b.remaining > 0)
  const expiredBans = bans.filter(b => b.remaining <= 0)

  return (
    <div>
      {modal && (
        <SudoModal
          ip={modal.ip}
          onConfirm={handleUnban}
          onCancel={() => setModal(null)}
        />
      )}

      <div className="page-header">
        <div>
          <h1 className="page-title">IPs bannies</h1>
          <p className="page-subtitle">
            {loading
              ? 'Chargement…'
              : `${activeBans.length} actif${activeBans.length !== 1 ? 's' : ''}` +
                (expiredBans.length > 0 ? ` · ${expiredBans.length} expiré${expiredBans.length !== 1 ? 's' : ''}` : '')}
          </p>
        </div>
        <button className="btn btn-ghost" onClick={load} disabled={loading}>
          <RefreshCw className={loading ? 'spin' : ''} />
          Actualiser
        </button>
      </div>

      {!loading && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
          {activeBans.length > 0
            ? <span className="badge badge-red">🚫 {activeBans.length} IP{activeBans.length !== 1 ? 's' : ''} bloquée{activeBans.length !== 1 ? 's' : ''}</span>
            : <span className="badge badge-green">Aucun ban actif</span>}
          {expiredBans.length > 0 &&
            <span className="badge badge-gray">{expiredBans.length} expiré{expiredBans.length !== 1 ? 's' : ''}</span>}
        </div>
      )}

      {error && (
        <div className="card" style={{ color: 'var(--red)', marginBottom: 16 }}>{error}</div>
      )}

      <div className="card">
        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[0, 1, 2].map(i => <div key={i} className="skeleton" style={{ height: 36 }} />)}
          </div>
        ) : bans.length === 0 ? (
          <div className="empty">
            <ShieldOff />
            <p>Aucune IP bannie</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>IP source</th>
                  <th>Type d'attaque</th>
                  <th>Banni à</th>
                  <th>Durée</th>
                  <th>Temps restant</th>
                  <th>Détail</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {bans.map(ban => (
                  <tr key={ban.ip} style={{ opacity: ban.remaining <= 0 ? 0.45 : 1 }}>
                    <td>
                      <span className="mono" style={{ fontWeight: 600 }}>{ban.ip}</span>
                    </td>
                    <td>
                      <span className="badge badge-red">{ban.attack_type || '—'}</span>
                    </td>
                    <td className="muted mono" style={{ whiteSpace: 'nowrap' }}>
                      {new Date(ban.banned_at * 1000).toLocaleTimeString('fr-FR')}
                    </td>
                    <td className="muted">{ban.duration}s</td>
                    <td>
                      {ban.remaining > 0
                        ? <TimerBar remaining={ban.remaining} duration={ban.duration} />
                        : <span className="badge badge-gray">Expiré</span>}
                    </td>
                    <td className="muted" style={{
                      maxWidth: 220, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {ban.reason || '—'}
                    </td>
                    <td>
                      <button
                        className="btn btn-ghost"
                        style={{ padding: '4px 10px', fontSize: 11, color: 'var(--orange)' }}
                        onClick={() => setModal({ ip: ban.ip })}
                      >
                        <Unlock size={12} />
                        Débannir
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {bans.length > 0 && (
          <p style={{ marginTop: 12, fontSize: 11, color: 'var(--text-disabled)' }}>
            Mise à jour automatique toutes les 5 s · le ban expire côté eBPF à la même échéance
          </p>
        )}
      </div>
    </div>
  )
}
