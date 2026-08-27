import { authFetch } from './auth'
import { useEffect, useState } from 'react'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

/**
 * V.2.9: پنل فشرده وضعیت معامله واقعی Toobit
 * فقط خواندنی — فعال/غیرفعال بودن از Secrets بک‌اند کنترل می‌شود.
 */
export default function RealTradePanel() {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

  const load = async () => {
    setLoading(true)
    setErr(null)
    try {
      const res = await authFetch(`${API_BASE_URL}/real-trade/status`)
      if (!res.ok) throw new Error('خطا در دریافت وضعیت')
      const data = await res.json()
      setStatus(data)
    } catch (e) {
      setErr(e.message || 'خطا')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) load()
  }, [open])

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
          {loading && <div>در حال بارگذاری…</div>}
          {err && <div style={{ color: '#FF5C72' }}>{err}</div>}
          {status && !loading && (
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
              <div style={{ marginTop: 10, color: '#667788', fontSize: 12 }}>
                فعال‌سازی فقط با تنظیم{' '}
                <code style={{ color: '#9ad' }}>REAL_TRADING_ENABLED=true</code> در Secrets بک‌اند.
                حداکثر {status.max_open_positions} پوزیشن همزمان · فقط سیگنال ≥ {status.min_confluence}
              </div>
              <button
                type="button"
                onClick={load}
                style={{
                  marginTop: 10,
                  background: '#1a3040',
                  border: '1px solid #2a4a5a',
                  color: '#cde',
                  borderRadius: 8,
                  padding: '6px 12px',
                  cursor: 'pointer',
                }}
              >
                بروزرسانی وضعیت
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
