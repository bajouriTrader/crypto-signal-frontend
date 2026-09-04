import { authFetch } from './auth'
import { useEffect, useState, useRef } from 'react'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'
const STATUS_VIEWER = 'https://asalehb-crypto-signal-backend.hf.space/status-viewer'

function Metric({ label, value, color }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        padding: '12px 8px',
        borderRadius: 10,
        background: '#121c28',
        border: '1px solid #243444',
        minHeight: 72,
        textAlign: 'center',
      }}
    >
      <span style={{ fontSize: 11, color: '#8899aa', lineHeight: 1.3 }}>{label}</span>
      <span
        dir="ltr"
        style={{
          fontSize: 18,
          fontWeight: 700,
          color: color || '#e8f0f8',
          lineHeight: 1.2,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </span>
    </div>
  )
}

function PosCard({ t, onClose, closing }) {
  const sym = t.symbol
  const dir = t.direction
  const upnl = Number(t.unrealized_usdt ?? 0)
  const upct = Number(t.unrealized_pct ?? 0)
  const progress = Number(t.progress ?? 0)
  const pnlColor = upnl >= 0 ? '#2DD4A7' : '#FF5C72'
  return (
    <div
      style={{
        padding: 12,
        marginBottom: 8,
        borderRadius: 12,
        background: '#121c28',
        border: '1px solid #243444',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <strong style={{ fontSize: 15 }}>{sym}</strong>
          <span
            style={{
              fontSize: 11,
              padding: '2px 8px',
              borderRadius: 6,
              background: dir === 'long' ? 'rgba(45,212,167,0.15)' : 'rgba(255,92,114,0.15)',
              color: dir === 'long' ? '#2DD4A7' : '#FF5C72',
            }}
          >
            {dir === 'long' ? 'لانگ' : 'شورت'}
          </span>
          {t.profit_locked && (
            <span style={{ fontSize: 10, color: '#E8A94A' }}>قفل‌شده</span>
          )}
        </div>
        <div dir="ltr" style={{ textAlign: 'left' }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: pnlColor }}>
            {upnl >= 0 ? '+' : ''}{upnl.toFixed(4)} $
          </div>
          <div style={{ fontSize: 11, color: pnlColor }} dir="ltr">
            {upct >= 0 ? '+' : ''}{upct.toFixed(3)}%
          </div>
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 8,
          marginBottom: 10,
        }}
      >
        {[
          ['ورود', t.entry],
          ['هدف', t.target],
          ['حد ضرر', t.stop_loss],
          ['مارجین', t.margin != null ? Number(t.margin).toFixed(2) : '—'],
        ].map(([lb, val]) => (
          <div key={lb} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: '#667788', marginBottom: 2 }}>{lb}</div>
            <div dir="ltr" style={{ fontSize: 12, fontWeight: 600, color: '#cde' }}>
              {val ?? '—'}
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginBottom: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#667', marginBottom: 3 }}>
          <span>پیشرفت به TP</span>
          <span dir="ltr">{Math.round(progress * 100)}%</span>
        </div>
        <div style={{ height: 4, borderRadius: 2, background: '#1a2836', overflow: 'hidden' }}>
          <div
            style={{
              height: '100%',
              width: `${Math.max(0, Math.min(100, progress * 100))}%`,
              background: progress >= 0.72 ? '#2DD4A7' : '#3a7abd',
              transition: 'width 0.4s',
            }}
          />
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 11, color: '#667' }} dir="ltr">
          SL:{t.sl_on_exchange ? '✓' : '—'} · TP:{t.tp_on_exchange ? '✓' : '—'}
          {t.leverage ? ` · ${t.leverage}x` : ''}
        </span>
        <button
          type="button"
          disabled={closing}
          onClick={() => onClose(sym)}
          style={{
            background: '#2a1520',
            border: '1px solid #5a2a35',
            color: '#ff8a9a',
            borderRadius: 8,
            padding: '4px 12px',
            fontSize: 12,
            cursor: closing ? 'wait' : 'pointer',
          }}
        >
          {closing ? '…' : 'بستن'}
        </button>
      </div>
    </div>
  )
}

export default function RealTradePanel() {
  const [open, setOpen] = useState(true)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const [flash, setFlash] = useState(null)
  const [closingSym, setClosingSym] = useState(null)
  const timerRef = useRef(null)
  const flashTimerRef = useRef(null)

  const load = async (silent = false) => {
    if (!silent) setLoading(true)
    setErr(null)
    try {
      const res = await authFetch(`${API_BASE_URL}/real-trade/status`)
      if (!res.ok) throw new Error('خطا در دریافت وضعیت')
      const data = await res.json()
      setStatus(data)
      if (!silent) {
        setFlash('ok')
        if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
        flashTimerRef.current = setTimeout(() => setFlash(null), 2000)
      }
    } catch (e) {
      setErr(e.message || 'خطا')
      setFlash(null)
    } finally {
      if (!silent) setLoading(false)
    }
  }

  const closePos = async (symbol) => {
    setClosingSym(symbol)
    try {
      const res = await authFetch(`${API_BASE_URL}/real-trade/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || data.message || 'بستن ناموفق')
      await load(true)
    } catch (e) {
      setErr(e.message || 'خطا در بستن')
    } finally {
      setClosingSym(null)
    }
  }

  useEffect(() => {
    load(true)
    timerRef.current = setInterval(() => load(true), 5000)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    }
  }, [])

  const tracked = status?.tracked || []
  const mgr = status?.manager || {}
  const recent = status?.recent_closed || []

  return (
    <div className="real-trade-wrap" style={{ margin: '12px 0' }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          background: 'linear-gradient(135deg, #1a2a3a, #0d1b2a)',
          border: '1px solid #2a4a5a',
          color: '#e0f0ff',
          borderRadius: 10,
          padding: '10px 16px',
          cursor: 'pointer',
          fontSize: 14,
          width: '100%',
          textAlign: 'right',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span>
          {open ? '▼' : '▶'} معامله واقعی Toobit
          {status?.real_trading_enabled ? (
            <span style={{ color: '#2DD4A7', marginRight: 8 }}>● فعال</span>
          ) : status ? (
            <span style={{ color: '#888', marginRight: 8 }}>○ خاموش</span>
          ) : null}
        </span>
        {status && (
          <span style={{ fontSize: 12, color: '#8899aa' }} dir="ltr">
            {status.open_positions}/{status.max_open_positions} · {Number(status.available_usdt || 0).toFixed(2)} USDT
          </span>
        )}
      </button>

      {open && (
        <div
          style={{
            marginTop: 8,
            padding: 14,
            borderRadius: 12,
            background: '#0d1520',
            border: '1px solid #1e3344',
            fontSize: 13,
          }}
        >
          {loading && !status && <div>در حال بارگذاری…</div>}
          {err && <div style={{ color: '#FF5C72', marginBottom: 8 }}>{err}</div>}
          {status && (
            <>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(4, 1fr)',
                  gap: 8,
                  marginBottom: 12,
                }}
              >
                <Metric
                  label="موجودی آزاد"
                  value={`${Number(status.available_usdt || 0).toFixed(2)} $`}
                />
                <Metric
                  label="پوزیشن باز"
                  value={`${status.open_positions} / ${status.max_open_positions}`}
                />
                <Metric label="اهرم" value={`${status.leverage}x`} />
                <Metric
                  label="PnL باز"
                  value={`${(tracked.reduce((s, t) => s + Number(t.unrealized_usdt || 0), 0)).toFixed(4)} $`}
                  color={
                    tracked.reduce((s, t) => s + Number(t.unrealized_usdt || 0), 0) >= 0
                      ? '#2DD4A7'
                      : '#FF5C72'
                  }
                />
              </div>

              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 8,
                  justifyContent: 'center',
                  marginBottom: 12,
                  fontSize: 11,
                  color: '#7a8a9a',
                }}
              >
                <span>قفل {mgr.profit_lock_trigger ?? '—'} · BE {mgr.breakeven_trigger_pct ?? '—'}%</span>
                <span>·</span>
                <span>سیگنال ≥ {status.min_confluence}</span>
                <span>·</span>
                <span>سقف نگهداری {Math.round((mgr.max_hold_seconds || 0) / 3600)}h</span>
              </div>

              {tracked.length > 0 ? (
                <div style={{ marginBottom: 12 }}>
                  {tracked.map((t) => (
                    <PosCard
                      key={t.symbol}
                      t={t}
                      onClose={closePos}
                      closing={closingSym === t.symbol}
                    />
                  ))}
                </div>
              ) : (
                <div
                  style={{
                    padding: '20px 12px',
                    textAlign: 'center',
                    color: '#556677',
                    border: '1px dashed #243444',
                    borderRadius: 10,
                    marginBottom: 12,
                  }}
                >
                  پوزیشن بازی نیست
                </div>
              )}

              {recent.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 12, color: '#8899aa', marginBottom: 6 }}>معاملات اخیر بسته‌شده</div>
                  {recent.slice(0, 5).map((r, i) => {
                    const pnl = Number(r.approx_pnl || 0)
                    return (
                      <div
                        key={i}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          padding: '6px 4px',
                          borderBottom: '1px solid #1a2836',
                          fontSize: 12,
                        }}
                      >
                        <span>
                          <strong>{r.symbol}</strong>{' '}
                          <span style={{ color: r.direction === 'long' ? '#2DD4A7' : '#FF5C72' }}>
                            {r.direction === 'long' ? 'L' : 'S'}
                          </span>
                        </span>
                        <strong dir="ltr" style={{ color: pnl >= 0 ? '#2DD4A7' : '#FF5C72' }}>
                          {pnl >= 0 ? '+' : ''}{pnl.toFixed(4)} $
                        </strong>
                      </div>
                    )
                  })}
                </div>
              )}

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
                <button
                  type="button"
                  onClick={() => load()}
                  disabled={loading}
                  style={{
                    background: '#1a3040',
                    border: '1px solid #2a4a5a',
                    color: '#cde',
                    borderRadius: 8,
                    padding: '6px 14px',
                    cursor: loading ? 'wait' : 'pointer',
                    fontSize: 13,
                  }}
                >
                  {loading ? '…' : 'بروزرسانی'}
                </button>
                {flash === 'ok' && !loading && (
                  <span style={{ color: '#2DD4A7', fontSize: 12 }}>✓ به‌روز شد</span>
                )}
                <a
                  href={STATUS_VIEWER}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    marginRight: 'auto',
                    fontSize: 12,
                    color: '#6af',
                    textDecoration: 'none',
                    border: '1px solid #2a4a6a',
                    borderRadius: 8,
                    padding: '6px 12px',
                  }}
                >
                  وضعیت / رژیم ↗
                </a>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
