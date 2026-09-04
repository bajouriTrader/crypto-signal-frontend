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
        gap: 4,
        padding: '10px 6px',
        borderRadius: 10,
        background: '#121c28',
        border: '1px solid #243444',
        minHeight: 64,
        textAlign: 'center',
      }}
    >
      <span style={{ fontSize: 11, color: '#8899aa', lineHeight: 1.25 }}>{label}</span>
      <span
        dir="ltr"
        style={{
          fontSize: 16,
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

/** نوار دو‌رنگ: چپ SL (قرمز) · راست TP (سبز) · نشانگر قیمت فعلی */
function PathBar({ direction, entry, sl, tp, price }) {
  const e = Number(entry)
  const s = Number(sl)
  const t = Number(tp)
  const p = Number(price)
  if (![e, s, t, p].every((x) => Number.isFinite(x) && x > 0)) {
    return null
  }

  // برای لانگ: SL < entry < TP — برای شورت برعکس
  const isLong = (direction || '').toLowerCase() === 'long'
  const low = isLong ? s : t
  const high = isLong ? t : s
  const span = high - low
  if (span <= 1e-12) return null

  const clamp01 = (x) => Math.max(0, Math.min(1, x))
  const entryPos = clamp01((e - low) / span)
  const pricePos = clamp01((p - low) / span)

  // پیشرفت به TP از entry (مثبت = به سمت TP)
  let toTp = 0
  if (isLong) {
    toTp = t !== e ? (p - e) / (t - e) : 0
  } else {
    toTp = e !== t ? (e - p) / (e - t) : 0
  }
  const toTpPct = Math.round(toTp * 100)

  // فاصله تا SL به‌صورت درصد مسیر entry→SL
  let toSl = 0
  if (isLong) {
    toSl = e !== s ? (e - p) / (e - s) : 0
  } else {
    toSl = s !== e ? (p - e) / (s - e) : 0
  }
  const towardSl = toSl > 0

  return (
    <div style={{ marginTop: 8, marginBottom: 4 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 10,
          color: '#778899',
          marginBottom: 4,
        }}
      >
        <span style={{ color: '#FF5C72' }}>SL {s}</span>
        <span dir="ltr" style={{ color: towardSl ? '#FF5C72' : toTpPct >= 0 ? '#2DD4A7' : '#8899aa' }}>
          {towardSl
            ? `${Math.min(100, Math.round(toSl * 100))}% → SL`
            : `${toTpPct}% → TP`}
        </span>
        <span style={{ color: '#2DD4A7' }}>TP {t}</span>
      </div>
      <div
        style={{
          position: 'relative',
          height: 10,
          borderRadius: 6,
          overflow: 'hidden',
          background: '#1a2836',
          border: '1px solid #243444',
        }}
      >
        {/* نیمه قرمز (سمت SL) و سبز (سمت TP) نسبت به entry */}
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: `${entryPos * 100}%`,
            background: 'linear-gradient(90deg, rgba(255,92,114,0.55), rgba(255,92,114,0.2))',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: `${entryPos * 100}%`,
            top: 0,
            bottom: 0,
            width: `${(1 - entryPos) * 100}%`,
            background: 'linear-gradient(90deg, rgba(45,212,167,0.2), rgba(45,212,167,0.55))',
          }}
        />
        {/* خط ورود */}
        <div
          style={{
            position: 'absolute',
            left: `${entryPos * 100}%`,
            top: 0,
            bottom: 0,
            width: 2,
            marginLeft: -1,
            background: 'rgba(255,255,255,0.55)',
          }}
        />
        {/* نشانگر قیمت */}
        <div
          style={{
            position: 'absolute',
            left: `${pricePos * 100}%`,
            top: -2,
            bottom: -2,
            width: 4,
            marginLeft: -2,
            borderRadius: 2,
            background: towardSl ? '#FF5C72' : '#2DD4A7',
            boxShadow: towardSl
              ? '0 0 6px rgba(255,92,114,0.8)'
              : '0 0 6px rgba(45,212,167,0.8)',
          }}
        />
      </div>
    </div>
  )
}

function PosCard({ t, onClose, closing }) {
  const sym = t.symbol
  const dir = t.direction
  const upnl = Number(t.unrealized_usdt ?? 0)
  const upct = Number(t.unrealized_pct ?? 0)
  const pnlColor = upnl >= 0 ? '#2DD4A7' : '#FF5C72'

  const cells = [
    ['ورود', t.entry],
    ['هدف', t.target],
    ['حد ضرر', t.stop_loss],
    ['مارجین', t.margin != null ? Number(t.margin).toFixed(2) : '—'],
  ]

  return (
    <div
      style={{
        padding: 12,
        marginBottom: 10,
        borderRadius: 12,
        background: '#121c28',
        border: '1px solid #243444',
      }}
    >
      {/* هدر: نماد + PnL */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 8,
          marginBottom: 8,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <strong style={{ fontSize: 15, letterSpacing: 0.3 }}>{sym}</strong>
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
        <div dir="ltr" style={{ textAlign: 'left', minWidth: 88 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: pnlColor, fontVariantNumeric: 'tabular-nums' }}>
            {upnl >= 0 ? '+' : ''}{upnl.toFixed(4)} $
          </div>
          <div style={{ fontSize: 11, color: pnlColor, fontVariantNumeric: 'tabular-nums' }}>
            {upct >= 0 ? '+' : ''}{upct.toFixed(3)}%
          </div>
        </div>
      </div>

      {/* اعداد ورود/TP/SL/مارجین — موبایل ۲×۲ */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: 6,
        }}
        className="pos-levels"
      >
        {cells.map(([lb, val]) => (
          <div
            key={lb}
            style={{
              textAlign: 'center',
              padding: '6px 4px',
              borderRadius: 8,
              background: '#0d1520',
              border: '1px solid #1e3344',
            }}
          >
            <div style={{ fontSize: 10, color: '#667788', marginBottom: 2 }}>{lb}</div>
            <div dir="ltr" style={{ fontSize: 13, fontWeight: 600, color: '#d8e6f0', fontVariantNumeric: 'tabular-nums' }}>
              {val ?? '—'}
            </div>
          </div>
        ))}
      </div>

      <PathBar
        direction={dir}
        entry={t.entry}
        sl={t.stop_loss}
        tp={t.target}
        price={t.current_price}
      />

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 8,
          gap: 8,
          flexWrap: 'wrap',
        }}
      >
        <span style={{ fontSize: 11, color: '#667788' }} dir="ltr">
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
            padding: '6px 14px',
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
  const openPnl = tracked.reduce((s, t) => s + Number(t.unrealized_usdt || 0), 0)

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
          padding: '10px 14px',
          cursor: 'pointer',
          fontSize: 13,
          width: '100%',
          textAlign: 'right',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
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
            padding: 12,
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
                  gridTemplateColumns: 'repeat(2, 1fr)',
                  gap: 8,
                  marginBottom: 12,
                }}
                className="rt-metrics"
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
                  value={`${openPnl >= 0 ? '+' : ''}${openPnl.toFixed(4)} $`}
                  color={openPnl >= 0 ? '#2DD4A7' : '#FF5C72'}
                />
              </div>

              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 6,
                  justifyContent: 'center',
                  marginBottom: 12,
                  fontSize: 11,
                  color: '#7a8a9a',
                  lineHeight: 1.5,
                }}
              >
                <span>قفل {mgr.profit_lock_trigger ?? '—'} · BE {mgr.breakeven_trigger_pct ?? '—'}%</span>
                <span>·</span>
                <span>سیگنال ≥ {status.min_confluence}</span>
                <span>·</span>
                <span>سقف {Math.round((mgr.max_hold_seconds || 0) / 3600)}h</span>
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
                    padding: '18px 12px',
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
                          padding: '7px 4px',
                          borderBottom: '1px solid #1a2836',
                          fontSize: 12,
                          gap: 8,
                        }}
                      >
                        <span>
                          <strong>{r.symbol}</strong>{' '}
                          <span style={{ color: r.direction === 'long' ? '#2DD4A7' : '#FF5C72' }}>
                            {r.direction === 'long' ? 'L' : 'S'}
                          </span>
                        </span>
                        <strong dir="ltr" style={{ color: pnl >= 0 ? '#2DD4A7' : '#FF5C72', fontVariantNumeric: 'tabular-nums' }}>
                          {pnl >= 0 ? '+' : ''}{pnl.toFixed(4)} $
                        </strong>
                      </div>
                    )
                  })}
                </div>
              )}

              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 8,
                  alignItems: 'center',
                }}
              >
                <button
                  type="button"
                  onClick={() => load()}
                  disabled={loading}
                  style={{
                    background: '#1a3040',
                    border: '1px solid #2a4a5a',
                    color: '#cde',
                    borderRadius: 8,
                    padding: '8px 14px',
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
                    padding: '8px 12px',
                  }}
                >
                  وضعیت / رژیم ↗
                </a>
              </div>
            </>
          )}
        </div>
      )}

      <style>{`
        @media (min-width: 520px) {
          .rt-metrics { grid-template-columns: repeat(4, 1fr) !important; }
          .pos-levels { grid-template-columns: repeat(4, 1fr) !important; }
        }
      `}</style>
    </div>
  )
}
