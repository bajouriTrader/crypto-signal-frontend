import { authFetch } from './auth'
import { useEffect, useState, useRef } from 'react'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

/**
 * V.2.10.1: پنل وضعیت معامله واقعی Toobit
 * - به‌روزرسانی خودکار هر ۳۰ ثانیه وقتی باز است
 * - بازخورد واضح روی دکمه بروزرسانی (loading + «به‌روز شد»)
 * - نمایش پوزیشن‌های ردیابی‌شده با پیشرفت و سود لحظه‌ای
 */
export default function RealTradePanel() {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const [flash, setFlash] = useState(null) // 'ok' | null
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

  useEffect(() => {
    if (open) {
      load()
      timerRef.current = setInterval(() => load(true), 30000)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    }
  }, [open])

  const tracked = status?.tracked || []
  const mgr = status?.manager || {}

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
          {status && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                <div>
                  <span style={{ color: '#8899aa' }}>وضعیت: </span>
                  {status.real_trading_enabled ? (
                    <strong style={{ color: '#2DD4A7' }}>فعال</strong>
                  ) : (
                    <strong style={{ color: '#E8A94A' }}>خاموش (Secrets)</strong>
                  )}
                </div>
                <div>
                  <span style={{ color: '#8899aa' }}>موجودی آزاد: </span>
                  <strong dir="ltr">{Number(status.available_usdt || 0).toFixed(2)} USDT</strong>
                </div>
                <div>
                  <span style={{ color: '#8899aa' }}>پوزیشن باز: </span>
                  <strong dir="ltr">
                    {status.open_positions} / {status.max_open_positions}
                  </strong>
                </div>
                <div>
                  <span style={{ color: '#8899aa' }}>اهرم: </span>
                  <strong dir="ltr">{status.leverage}x</strong>
                </div>
                <div>
                  <span style={{ color: '#8899aa' }}>حداقل امتیاز: </span>
                  <strong dir="ltr">{status.min_confluence}</strong>
                </div>
                <div>
                  <span style={{ color: '#8899aa' }}>سقف ضرر روزانه: </span>
                  <strong dir="ltr">{status.daily_loss_limit} USDT</strong>
                </div>
              </div>

              {mgr.profit_lock_trigger != null && (
                <div
                  style={{
                    marginTop: 12,
                    padding: '8px 10px',
                    borderRadius: 8,
                    background: '#0a1a14',
                    border: '1px solid #1a3a2a',
                    fontSize: 12,
                    color: '#8cba9e',
                  }}
                >
                  مدیریت خودکار فعال: قفل سود از{' '}
                  <strong dir="ltr">{Math.round((mgr.profit_lock_trigger || 0) * 100)}%</strong> پیشرفت
                  به هدف · حداقل سود{' '}
                  <strong dir="ltr">{mgr.min_profit_pct}%</strong> · سقف نگهداری{' '}
                  <strong dir="ltr">{Math.round((mgr.max_hold_seconds || 0) / 3600)}h</strong>
                  <br />
                  برنامه خودش هر {mgr.interval_seconds || 45} ثانیه پوزیشن‌ها را چک و در صورت نیاز می‌بندد.
                </div>
              )}


              {/* پوزیشن‌های باز صرافی (حتی اگر بعد از ری‌استارت از tracked جا مانده باشند) */}
              {Array.isArray(status.positions) && status.positions.length > 0 && tracked.length === 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ color: '#8899aa', marginBottom: 6 }}>پوزیشن باز روی صرافی:</div>
                  {status.positions.map((p, idx) => {
                    const sym = String(p.symbol || '').replace('-SWAP-USDT', '').replace('USDT', '')
                    const side = String(p.side || '').toUpperCase()
                    const isLong = side.includes('LONG') || Number(p.position || p.positionAmt || 0) > 0
                    const upnl = Number(p.unrealizedPnL || 0)
                    const entry = p.avgPrice || p.entryPrice
                    const last = p.lastPrice || p.markPrice
                    return (
                      <div
                        key={sym + idx}
                        style={{
                          padding: '8px 10px',
                          marginBottom: 6,
                          borderRadius: 8,
                          background: '#121c28',
                          border: '1px solid #243444',
                          display: 'grid',
                          gridTemplateColumns: '1fr auto',
                          gap: 4,
                        }}
                      >
                        <div>
                          <strong>{sym}</strong>{' '}
                          <span style={{ color: isLong ? '#2DD4A7' : '#FF5C72' }}>
                            {isLong ? 'لانگ' : 'شورت'}
                          </span>
                          <span style={{ color: '#667', marginRight: 6 }} dir="ltr">
                            @{entry}
                          </span>
                        </div>
                        <div dir="ltr" style={{ textAlign: 'left' }}>
                          <strong style={{ color: upnl >= 0 ? '#2DD4A7' : '#FF5C72' }}>
                            {upnl >= 0 ? '+' : ''}{upnl.toFixed(4)} USDT
                          </strong>
                        </div>
                        <div style={{ fontSize: 11, color: '#778' }} dir="ltr">
                          last {last} · lev {p.leverage || '—'}x
                        </div>
                      </div>
                    )
                  })}
                  <div style={{ fontSize: 11, color: '#667', marginTop: 4 }}>
                    بعد از ری‌استارت سرور، جزئیات قفل‌سود تا همگام‌سازی مجدد از روی صرافی خوانده می‌شود.
                  </div>
                </div>
              )}

              {tracked.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ color: '#8899aa', marginBottom: 6 }}>پوزیشن‌های ردیابی‌شده:</div>
                  {tracked.map((t) => (
                    <div
                      key={t.symbol}
                      style={{
                        padding: '8px 10px',
                        marginBottom: 6,
                        borderRadius: 8,
                        background: '#121c28',
                        border: '1px solid #243444',
                        display: 'grid',
                        gridTemplateColumns: '1fr auto',
                        gap: 4,
                      }}
                    >
                      <div>
                        <strong>{t.symbol}</strong>{' '}
                        <span style={{ color: t.direction === 'long' ? '#2DD4A7' : '#FF5C72' }}>
                          {t.direction === 'long' ? 'لانگ' : 'شورت'}
                        </span>
                        <span style={{ color: '#667', marginRight: 6 }} dir="ltr">
                          @{Number(t.entry).toPrecision(6)}
                        </span>
                      </div>
                      <div dir="ltr" style={{ textAlign: 'left' }}>
                        {t.unrealized_pct != null ? (
                          <strong
                            style={{
                              color: t.unrealized_pct >= 0 ? '#2DD4A7' : '#FF5C72',
                            }}
                          >
                            {t.unrealized_pct >= 0 ? '+' : ''}
                            {Number(t.unrealized_pct).toFixed(2)}%
                          </strong>
                        ) : (
                          '—'
                        )}
                      </div>
                      <div style={{ fontSize: 11, color: '#778' }} dir="ltr">
                        progress {t.progress != null ? `${Math.round(t.progress * 100)}%` : '—'} ·{' '}
                        {t.elapsed_sec != null ? `${Math.floor(t.elapsed_sec / 60)}m` : ''}
                        {t.score != null ? ` · score ${t.score}` : ''}{t.recovered ? ' · بازیابی‌شده' : ''}
                        {t.sl_on_exchange === true
                          ? ' · SL روی صرافی ✓'
                          : t.sl_on_exchange === false
                            ? ' · ⚠ SL روی صرافی تأیید نشد'
                            : ''}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div style={{ marginTop: 10, color: '#667788', fontSize: 12 }}>
                فعال‌سازی فقط با تنظیم{' '}
                <code style={{ color: '#9ad' }}>REAL_TRADING_ENABLED=true</code> در Secrets بک‌اند.
                حداکثر {status.max_open_positions} پوزیشن همزمان · فقط سیگنال ≥ {status.min_confluence}
              </div>

              <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10 }}>
                <button
                  type="button"
                  onClick={() => load()}
                  disabled={loading}
                  style={{
                    background: loading ? '#152030' : '#1a3040',
                    border: '1px solid #2a4a5a',
                    color: loading ? '#889' : '#cde',
                    borderRadius: 8,
                    padding: '6px 12px',
                    cursor: loading ? 'wait' : 'pointer',
                    opacity: loading ? 0.7 : 1,
                  }}
                >
                  {loading ? 'در حال بروزرسانی…' : 'بروزرسانی وضعیت'}
                </button>
                {flash === 'ok' && !loading && (
                  <span style={{ color: '#2DD4A7', fontSize: 12 }}>✓ به‌روز شد</span>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
