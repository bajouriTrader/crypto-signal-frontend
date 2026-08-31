import { authFetch } from './auth'
import { useEffect, useState, useRef, useCallback } from 'react'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

function normSym(s) {
  return String(s || '')
    .replace('-SWAP-USDT', '')
    .replace('USDT', '')
    .replace(/[-_/]/g, '')
    .toUpperCase()
}

/**
 * پنل معامله واقعی — PnL دلاری زنده از صرافی + دکمه بستن دستی
 * پولینگ: ۵ ثانیه وقتی پوزیشن باز است، وگرنه ۳۰ ثانیه
 */
export default function RealTradePanel() {
  const [open, setOpen] = useState(true)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const [flash, setFlash] = useState(null)
  const [closing, setClosing] = useState({})
  const [closeMsg, setCloseMsg] = useState(null)
  const timerRef = useRef(null)
  const flashTimerRef = useRef(null)

  const load = useCallback(async (silent = false) => {
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
  }, [])

  const hasOpen =
    (status?.open_positions > 0) ||
    (Array.isArray(status?.positions) && status.positions.length > 0) ||
    (Array.isArray(status?.tracked) && status.tracked.some((t) => t.status === 'open' || !t.status))

  useEffect(() => {
    load(true)
    return () => {
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    }
  }, [load])

  // پولینگ پویا
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    const ms = hasOpen ? 5000 : 30000
    timerRef.current = setInterval(() => load(true), ms)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [hasOpen, load])

  const closePosition = async (symbol) => {
    const key = normSym(symbol)
    if (!key || closing[key]) return
    if (!window.confirm(`بستن دستی ${key} با سفارش مارکت؟`)) return
    setClosing((c) => ({ ...c, [key]: true }))
    setCloseMsg(null)
    try {
      const res = await authFetch(`${API_BASE_URL}/real-trade/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: key }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || data.ok === false) {
        throw new Error(data.reason || data.detail || `خطا ${res.status}`)
      }
      setCloseMsg({ ok: true, text: `${key} بسته شد` + (data.approx_pnl != null ? ` · PnL≈${Number(data.approx_pnl).toFixed(4)}$` : '') })
      await load(true)
    } catch (e) {
      setCloseMsg({ ok: false, text: e.message || 'بستن ناموفق' })
    } finally {
      setClosing((c) => ({ ...c, [key]: false }))
    }
  }

  const tracked = status?.tracked || []
  const exchangePositions = Array.isArray(status?.positions) ? status.positions : []
  const mgr = status?.manager || {}

  // نقشه PnL دلاری از صرافی
  const exchangeBySym = {}
  for (const p of exchangePositions) {
    const k = normSym(p.symbol)
    exchangeBySym[k] = p
  }

  // ادغام tracked + صرافی برای نمایش واحد
  const rows = []
  const seen = new Set()
  for (const t of tracked) {
    if (t.status && t.status !== 'open') continue
    const k = normSym(t.symbol)
    seen.add(k)
    const ex = exchangeBySym[k]
    const upnl = ex != null ? Number(ex.unrealizedPnL ?? ex.unrealizedPnl ?? 0) : null
    rows.push({
      symbol: k,
      direction: t.direction,
      entry: t.entry,
      score: t.score,
      progress: t.progress,
      elapsed_sec: t.elapsed_sec,
      unrealized_pct: t.unrealized_pct,
      upnl,
      last: ex?.lastPrice || ex?.markPrice || t.current_price,
      leverage: ex?.leverage || status?.leverage,
      sl_on_exchange: t.sl_on_exchange,
      tp_on_exchange: t.tp_on_exchange,
      margin: ex?.margin,
    })
  }
  for (const p of exchangePositions) {
    const k = normSym(p.symbol)
    if (seen.has(k)) continue
    const side = String(p.side || '').toUpperCase()
    const isLong = side.includes('LONG') || Number(p.position || 0) > 0
    if (side.includes('SHORT')) {
      /* short */
    }
    rows.push({
      symbol: k,
      direction: side.includes('SHORT') ? 'short' : isLong ? 'long' : 'short',
      entry: p.avgPrice || p.entryPrice,
      upnl: Number(p.unrealizedPnL ?? 0),
      last: p.lastPrice || p.markPrice,
      leverage: p.leverage,
      margin: p.margin,
      recovered: true,
    })
  }

  return (
    <div className="real-trade-wrap" style={{ margin: '12px 0' }}>
      <button
        type="button"
        className="real-trade-toggle"
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
        }}
      >
        {open ? '▼' : '▶'} معامله واقعی Toobit
        {status?.real_trading_enabled ? (
          <span style={{ color: '#2DD4A7', marginRight: 8 }}>● فعال</span>
        ) : status ? (
          <span style={{ color: '#888', marginRight: 8 }}>○ خاموش</span>
        ) : null}
        {status?.open_positions > 0 && (
          <span style={{ color: '#E8A94A', marginRight: 8 }}>
            {status.open_positions} باز
          </span>
        )}
        {hasOpen && (
          <span style={{ color: '#6ec6ff', marginRight: 8, fontSize: 11 }}>زنده ۵ث</span>
        )}
      </button>

      {open && (
        <div
          className="real-trade-body"
          style={{
            marginTop: 8,
            padding: 14,
            borderRadius: 12,
            background: '#0d1520',
            border: '1px solid #1e3344',
            fontSize: 13,
            lineHeight: 1.7,
          }}
        >
          {loading && !status && <div>در حال بارگذاری…</div>}
          {err && <div style={{ color: '#FF5C72' }}>{err}</div>}
          {closeMsg && (
            <div style={{ color: closeMsg.ok ? '#2DD4A7' : '#FF5C72', marginBottom: 8 }}>
              {closeMsg.text}
            </div>
          )}
          {status && (
            <>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 8 }}>
                <div>
                  موجودی آزاد:{' '}
                  <strong dir="ltr">{Number(status.available_usdt || 0).toFixed(2)} USDT</strong>
                </div>
                <div>
                  باز:{' '}
                  <strong dir="ltr">
                    {status.open_positions} / {status.max_open_positions}
                  </strong>
                </div>
                <div>
                  اهرم: <strong dir="ltr">{status.leverage}x</strong>
                </div>
                <button
                  type="button"
                  onClick={() => load(false)}
                  disabled={loading}
                  style={{
                    marginRight: 'auto',
                    background: '#1a2a3a',
                    border: '1px solid #2a4a5a',
                    color: '#cde',
                    borderRadius: 8,
                    padding: '4px 12px',
                    cursor: 'pointer',
                  }}
                >
                  {loading ? '…' : flash === 'ok' ? '✓ به‌روز' : 'بروزرسانی'}
                </button>
              </div>

              {mgr && (
                <div style={{ fontSize: 12, color: '#778899', marginBottom: 8 }}>
                  قفل سود {mgr.profit_lock_trigger} · BE {mgr.breakeven_trigger_pct}% · سقف{' '}
                  {Math.round((mgr.max_hold_seconds || 0) / 3600)}h
                </div>
              )}

              {rows.length === 0 && (
                <div style={{ color: '#667', marginTop: 8 }}>پوزیشن بازی نیست.</div>
              )}

              {rows.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ color: '#8899aa', marginBottom: 8, fontWeight: 600 }}>
                    پوزیشن‌های باز (زنده از صرافی)
                  </div>
                  {rows.map((r) => {
                    const upnl = r.upnl
                    const pct = r.unrealized_pct
                    const isLong = r.direction === 'long'
                    return (
                      <div
                        key={r.symbol}
                        style={{
                          padding: '10px 12px',
                          marginBottom: 8,
                          borderRadius: 10,
                          background: '#121c28',
                          border: '1px solid #243444',
                          display: 'grid',
                          gridTemplateColumns: '1fr auto',
                          gap: 6,
                          alignItems: 'center',
                        }}
                      >
                        <div>
                          <strong style={{ fontSize: 15 }}>{r.symbol}</strong>{' '}
                          <span style={{ color: isLong ? '#2DD4A7' : '#FF5C72', fontWeight: 700 }}>
                            {isLong ? 'LONG' : 'SHORT'}
                          </span>
                          <span style={{ color: '#667', marginRight: 8 }} dir="ltr">
                            @{Number(r.entry).toPrecision(6)}
                          </span>
                          {r.last != null && (
                            <span style={{ color: '#8899aa', fontSize: 12 }} dir="ltr">
                              · now {Number(r.last).toPrecision(6)}
                            </span>
                          )}
                        </div>
                        <div style={{ textAlign: 'left' }} dir="ltr">
                          {upnl != null && !Number.isNaN(upnl) ? (
                            <strong
                              style={{
                                fontSize: 16,
                                color: upnl >= 0 ? '#2DD4A7' : '#FF5C72',
                              }}
                            >
                              {upnl >= 0 ? '+' : ''}
                              {upnl.toFixed(4)} $
                            </strong>
                          ) : pct != null ? (
                            <strong style={{ color: pct >= 0 ? '#2DD4A7' : '#FF5C72' }}>
                              {pct >= 0 ? '+' : ''}
                              {Number(pct).toFixed(2)}%
                            </strong>
                          ) : (
                            '—'
                          )}
                          {pct != null && upnl != null && (
                            <div style={{ fontSize: 11, color: '#778' }}>
                              {pct >= 0 ? '+' : ''}
                              {Number(pct).toFixed(2)}%
                            </div>
                          )}
                        </div>
                        <div style={{ fontSize: 11, color: '#778' }} dir="ltr">
                          {r.leverage ? `${r.leverage}x` : ''}
                          {r.margin != null ? ` · margin ${Number(r.margin).toFixed(2)}` : ''}
                          {r.progress != null ? ` · prog ${Math.round(Number(r.progress) * 100)}%` : ''}
                          {r.elapsed_sec != null ? ` · ${Math.floor(r.elapsed_sec / 60)}m` : ''}
                          {r.score != null ? ` · ${r.score}` : ''}
                          {r.sl_on_exchange === true ? ' · SL✓' : r.sl_on_exchange === false ? ' · SL✗' : ''}
                          {r.tp_on_exchange === true ? ' · TP✓' : ''}
                          {r.recovered ? ' · از صرافی' : ''}
                        </div>
                        <div>
                          <button
                            type="button"
                            disabled={!!closing[r.symbol]}
                            onClick={() => closePosition(r.symbol)}
                            style={{
                              background: closing[r.symbol]
                                ? '#333'
                                : 'linear-gradient(180deg, #8b2e3a, #5c1a24)',
                              border: '1px solid #a33',
                              color: '#fff',
                              borderRadius: 8,
                              padding: '6px 14px',
                              cursor: closing[r.symbol] ? 'wait' : 'pointer',
                              fontSize: 12,
                              fontWeight: 700,
                            }}
                          >
                            {closing[r.symbol] ? '…' : 'بستن دستی'}
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {(status.recent_closed || []).length > 0 && (
                <div style={{ marginTop: 14 }}>
                  <div style={{ color: '#8899aa', marginBottom: 6, fontWeight: 600 }}>
                    ۵ معاملهٔ اخیر بسته‌شده
                  </div>
                  {(status.recent_closed || []).slice(0, 5).map((r, i) => {
                    const pnl = Number(r.approx_pnl || 0)
                    const sym = String(r.symbol || '').replace('-SWAP-USDT', '')
                    const dir = String(r.direction || '').toLowerCase()
                    return (
                      <div
                        key={String(sym) + i + String(r.exit_price || '')}
                        style={{
                          padding: '7px 10px',
                          marginBottom: 5,
                          borderRadius: 8,
                          background: '#0f1822',
                          border: '1px solid #1e2a38',
                          display: 'flex',
                          justifyContent: 'space-between',
                          gap: 8,
                        }}
                      >
                        <span>
                          <strong>{sym}</strong>{' '}
                          <span style={{ color: dir === 'long' ? '#2DD4A7' : '#FF5C72' }}>
                            {dir === 'long' ? 'L' : 'S'}
                          </span>
                        </span>
                        <strong dir="ltr" style={{ color: pnl >= 0 ? '#2DD4A7' : '#FF5C72' }}>
                          {pnl >= 0 ? '+' : ''}
                          {pnl.toFixed(4)} $
                        </strong>
                      </div>
                    )
                  })}
                </div>
              )}

              <div style={{ fontSize: 11, color: '#556', marginTop: 10 }}>
                حداکثر {status.max_open_positions} پوزیشن · سیگنال ≥ {status.min_confluence}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
