import { authFetch } from './auth'
import { useEffect, useState, useRef, useCallback } from 'react'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

function normSym(s) {
  return String(s || '')
    .replace(/-SWAP-USDT/gi, '')
    .replace(/USDT$/i, '')
    .replace(/[-_/]/g, '')
    .toUpperCase()
}

function fmtPrice(v) {
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return '—'
  if (n >= 100) return n.toFixed(2)
  if (n >= 1) return n.toFixed(4)
  if (n >= 0.01) return n.toFixed(5)
  return n.toFixed(6)
}

function fmtUsd(v, digits = 4) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)} $`
}

function fmtPct(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function Field({ label, value, dir = 'ltr', accent }) {
  return (
    <div className="rt-field">
      <span className="rt-field-label">{label}</span>
      <span className="rt-field-value" dir={dir} style={accent ? { color: accent } : undefined}>
        {value}
      </span>
    </div>
  )
}

/**
 * پنل معامله واقعی — چیدمان متقارن و خوانا
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
        flashTimerRef.current = setTimeout(() => setFlash(null), 1500)
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

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    const ms = hasOpen ? 4000 : 30000
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
      const pnlBit = data.approx_pnl != null ? ` · ${fmtUsd(data.approx_pnl)}` : ''
      setCloseMsg({ ok: true, text: `${key} بسته شد${pnlBit}` })
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

  const exchangeBySym = {}
  for (const p of exchangePositions) {
    exchangeBySym[normSym(p.symbol)] = p
  }

  const rows = []
  const seen = new Set()
  for (const t of tracked) {
    if (t.status && t.status !== 'open') continue
    const k = normSym(t.symbol)
    seen.add(k)
    const ex = exchangeBySym[k]
    const upnlRaw =
      t.unrealized_usdt != null
        ? t.unrealized_usdt
        : ex != null
          ? ex.unrealizedPnL ?? ex.unrealizedPnl
          : null
    rows.push({
      symbol: k,
      direction: t.direction,
      entry: t.entry,
      target: t.target,
      stop_loss: t.stop_loss,
      score: t.score,
      progress: t.progress,
      elapsed_sec: t.elapsed_sec,
      unrealized_pct: t.unrealized_pct,
      upnl: upnlRaw != null ? Number(upnlRaw) : null,
      last: t.current_price ?? ex?.lastPrice ?? ex?.markPrice ?? null,
      leverage: t.leverage || ex?.leverage || status?.leverage,
      sl_on_exchange: t.sl_on_exchange,
      tp_on_exchange: t.tp_on_exchange,
      margin: t.margin ?? ex?.margin,
      profit_locked: t.profit_locked,
    })
  }
  for (const p of exchangePositions) {
    const k = normSym(p.symbol)
    if (seen.has(k)) continue
    const side = String(p.side || '').toUpperCase()
    const direction = side.includes('SHORT')
      ? 'short'
      : side.includes('LONG') || Number(p.position || 0) > 0
        ? 'long'
        : 'short'
    rows.push({
      symbol: k,
      direction,
      entry: p.avgPrice || p.entryPrice,
      upnl: Number(p.unrealizedPnL ?? p.unrealizedPnl ?? 0),
      last: p.lastPrice || p.markPrice,
      leverage: p.leverage,
      margin: p.margin,
      recovered: true,
    })
  }

  const totalUpnl = rows.reduce((s, r) => s + (Number.isFinite(r.upnl) ? r.upnl : 0), 0)

  return (
    <div className="rt-wrap">
      <button type="button" className="rt-toggle" onClick={() => setOpen((v) => !v)}>
        <span className="rt-toggle-title">
          {open ? '▼' : '▶'} معامله واقعی Toobit
        </span>
        <span className="rt-toggle-meta">
          {status?.real_trading_enabled ? (
            <span className="rt-badge rt-badge-on">فعال</span>
          ) : status ? (
            <span className="rt-badge">خاموش</span>
          ) : null}
          {status?.open_positions > 0 && (
            <span className="rt-badge rt-badge-warn">{status.open_positions} باز</span>
          )}
          {hasOpen && <span className="rt-badge rt-badge-live">زنده ۴ث</span>}
        </span>
      </button>

      {open && (
        <div className="rt-body">
          {loading && !status && <div className="rt-muted">در حال بارگذاری…</div>}
          {err && <div className="rt-err">{err}</div>}
          {closeMsg && (
            <div className={closeMsg.ok ? 'rt-ok' : 'rt-err'}>{closeMsg.text}</div>
          )}

          {status && (
            <>
              {/* خلاصه حساب */}
              <div className="rt-account">
                <div className="rt-account-grid">
                  <Field
                    label="موجودی آزاد"
                    value={`${Number(status.available_usdt || 0).toFixed(2)} USDT`}
                  />
                  <Field
                    label="پوزیشن باز"
                    value={`${status.open_positions} / ${status.max_open_positions}`}
                  />
                  <Field label="اهرم" value={`${status.leverage}x`} />
                  <Field
                    label="PnL باز"
                    value={fmtUsd(totalUpnl)}
                    accent={totalUpnl >= 0 ? '#2DD4A7' : '#FF5C72'}
                  />
                </div>
                <div className="rt-account-foot">
                  <span className="rt-muted">
                    قفل {mgr.profit_lock_trigger ?? '—'} · BE {mgr.breakeven_trigger_pct ?? '—'}% · سقف{' '}
                    {Math.round((mgr.max_hold_seconds || 0) / 3600)}h · سیگنال ≥ {status.min_confluence}
                  </span>
                  <button
                    type="button"
                    className="rt-btn-ghost"
                    onClick={() => load(false)}
                    disabled={loading}
                  >
                    {loading ? '…' : flash === 'ok' ? 'به‌روز شد' : 'بروزرسانی'}
                  </button>
                </div>
              </div>

              {rows.length === 0 && (
                <div className="rt-empty">پوزیشن بازی نیست</div>
              )}

              {rows.map((r) => {
                const isLong = r.direction === 'long'
                const upnl = r.upnl
                const pct = r.unrealized_pct
                const pnlColor =
                  upnl != null
                    ? upnl >= 0
                      ? '#2DD4A7'
                      : '#FF5C72'
                    : pct != null
                      ? pct >= 0
                        ? '#2DD4A7'
                        : '#FF5C72'
                      : '#889'
                const progPct =
                  r.progress != null && Number.isFinite(Number(r.progress))
                    ? Math.max(-100, Math.min(100, Math.round(Number(r.progress) * 100)))
                    : null
                const elapsed =
                  r.elapsed_sec != null ? `${Math.floor(Number(r.elapsed_sec) / 60)}m` : '—'

                return (
                  <div key={r.symbol} className="rt-card">
                    {/* هدر کارت */}
                    <div className="rt-card-head">
                      <div className="rt-card-sym">
                        <span className="rt-sym-name">{r.symbol}</span>
                        <span className={`rt-dir ${isLong ? 'rt-dir-long' : 'rt-dir-short'}`}>
                          {isLong ? 'LONG' : 'SHORT'}
                        </span>
                        {r.profit_locked && <span className="rt-badge rt-badge-on">قفل</span>}
                      </div>
                      <div className="rt-card-pnl" dir="ltr">
                        <div className="rt-pnl-usd" style={{ color: pnlColor }}>
                          {upnl != null ? fmtUsd(upnl) : pct != null ? fmtPct(pct) : '—'}
                        </div>
                        {upnl != null && pct != null && (
                          <div className="rt-pnl-pct">{fmtPct(pct)}</div>
                        )}
                      </div>
                    </div>

                    {/* قیمت‌ها: ورود / لحظه / هدف / حد ضرر */}
                    <div className="rt-price-grid">
                      <Field label="ورود (Entry)" value={fmtPrice(r.entry)} />
                      <Field label="لحظه (Live)" value={fmtPrice(r.last)} accent="#6ec6ff" />
                      <Field label="هدف (TP)" value={fmtPrice(r.target)} accent="#2DD4A7" />
                      <Field label="حد ضرر (SL)" value={fmtPrice(r.stop_loss)} accent="#FF5C72" />
                    </div>

                    {/* مارجین و وضعیت */}
                    <div className="rt-meta-grid">
                      <Field label="مارجین" value={r.margin != null ? `${Number(r.margin).toFixed(2)}` : '—'} />
                      <Field label="اهرم" value={r.leverage != null ? `${r.leverage}x` : '—'} />
                      <Field label="زمان باز" value={elapsed} />
                      <Field label="امتیاز" value={r.score != null ? String(r.score) : '—'} />
                    </div>

                    {/* نوار پیشرفت به TP */}
                    {progPct != null && (
                      <div className="rt-progress-wrap">
                        <div className="rt-progress-labels">
                          <span>پیشرفت به TP</span>
                          <span dir="ltr">{progPct}%</span>
                        </div>
                        <div className="rt-progress-bar">
                          <div
                            className={`rt-progress-fill ${progPct >= 0 ? 'pos' : 'neg'}`}
                            style={{ width: `${Math.min(100, Math.abs(progPct))}%` }}
                          />
                        </div>
                        <div className="rt-progress-flags" dir="ltr">
                          {r.sl_on_exchange === true ? 'SL ✓' : r.sl_on_exchange === false ? 'SL ✗' : ''}
                          {r.tp_on_exchange === true ? ' · TP ✓' : ''}
                          {r.recovered ? ' · از صرافی' : ''}
                        </div>
                      </div>
                    )}

                    <div className="rt-card-actions">
                      <button
                        type="button"
                        className="rt-btn-close"
                        disabled={!!closing[r.symbol]}
                        onClick={() => closePosition(r.symbol)}
                      >
                        {closing[r.symbol] ? '…' : 'بستن دستی'}
                      </button>
                    </div>
                  </div>
                )
              })}

              {(status.recent_closed || []).length > 0 && (
                <div className="rt-recent">
                  <div className="rt-section-title">معاملات اخیر بسته‌شده</div>
                  <div className="rt-recent-list">
                    {(status.recent_closed || []).slice(0, 5).map((r, i) => {
                      const pnl = Number(r.approx_pnl || 0)
                      const sym = normSym(r.symbol)
                      const dir = String(r.direction || '').toLowerCase()
                      return (
                        <div key={sym + i + String(r.exit_price || '')} className="rt-recent-row">
                          <span>
                            <strong>{sym}</strong>{' '}
                            <span className={dir === 'long' ? 'rt-dir-long' : 'rt-dir-short'}>
                              {dir === 'long' ? 'L' : 'S'}
                            </span>
                          </span>
                          <strong
                            dir="ltr"
                            style={{ color: pnl >= 0 ? '#2DD4A7' : '#FF5C72' }}
                          >
                            {fmtUsd(pnl)}
                          </strong>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
