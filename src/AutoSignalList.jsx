import { useEffect, useState } from 'react'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

export default function AutoSignalList({ onFullAnalyze }) {
  const [signals, setSignals] = useState([])
  const [status, setStatus] = useState('loading') // 'loading' | 'ready' | 'error'
  const [isPartial, setIsPartial] = useState(false)
  const [sendingSymbol, setSendingSymbol] = useState(null)
  const [sentStatus, setSentStatus] = useState({}) // { SYMBOL: 'sent' | 'error' }

  useEffect(() => {
    let cancelled = false
    let pollTimer = null

    async function load() {
      try {
        const res = await fetch(`${API_BASE_URL}/watchlist-signals?limit=20`)
        if (!res.ok) throw new Error('خطا در دریافت لیست')
        const data = await res.json()
        if (cancelled) return

        setSignals(data.signals || [])
        setStatus('ready')
        setIsPartial((data.count || 0) < (data.total_watchlist_size || 20))

        // اگر لیست هنوز کامل نشده (سرویس تازه بالا اومده)، هر ۱۵ ثانیه دوباره چک کن
        if ((data.count || 0) < (data.total_watchlist_size || 20)) {
          pollTimer = setTimeout(load, 15000)
        }
      } catch {
        if (!cancelled) setStatus('error')
      }
    }

    setStatus('loading')
    load()
    return () => {
      cancelled = true
      if (pollTimer) clearTimeout(pollTimer)
    }
  }, [])

  const handleQuickTelegram = async (symbol) => {
    setSendingSymbol(symbol)
    try {
      const res = await fetch(`${API_BASE_URL}/quick-telegram`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol }),
      })
      const data = await res.json()
      setSentStatus((prev) => ({
        ...prev,
        [symbol]: data.telegram_status === 'sent' ? 'sent' : 'error',
      }))
    } catch {
      setSentStatus((prev) => ({ ...prev, [symbol]: 'error' }))
    } finally {
      setSendingSymbol(null)
      setTimeout(() => {
        setSentStatus((prev) => {
          const next = { ...prev }
          delete next[symbol]
          return next
        })
      }, 4000)
    }
  }

  return (
    <section className="watchlist-panel">
      <div className="watchlist-head">
        <h2 className="watchlist-title">سیگنال‌های خودکار پلتفرم</h2>
        <span className="watchlist-sub">
          بر اساس اندیکاتورهای تکنیکال، مرتب‌شده بر اساس امتیاز
          {isPartial && ' — لیست در حال تکمیل شدنه، چند لحظه دیگه بیشتر میشه'}
        </span>
      </div>

      {status === 'loading' && (
        <div className="watchlist-status">در حال دریافت لیست…</div>
      )}
      {status === 'error' && (
        <div className="watchlist-status">دریافت لیست با خطا مواجه شد.</div>
      )}

      {status === 'ready' && (
        <div className="watchlist-list">
          {signals.map((s, index) => (
            <div className="watchlist-row" key={s.symbol}>
              <span className="watchlist-rank">{index + 1}</span>
              <div className="watchlist-info">
                <span className="watchlist-symbol">{s.symbol}</span>
                <span
                  className={`watchlist-direction ${
                    s.direction === 'long' ? 'dir-long' : 'dir-short'
                  }`}
                >
                  {s.direction === 'long' ? 'لانگ' : 'شورت'}
                </span>
              </div>

              <div className="watchlist-score-track">
                <div
                  className="watchlist-score-fill"
                  style={{ width: `${s.confluence_score}%` }}
                />
              </div>
              <span dir="ltr" className="watchlist-score-value">
                {s.confluence_score}%
              </span>

              <div className="watchlist-actions">
                <button
                  className="btn-mini btn-mini-primary"
                  onClick={() => onFullAnalyze(s.symbol)}
                >
                  تحلیل کامل
                </button>
                <button
                  className="btn-mini"
                  disabled={sendingSymbol === s.symbol}
                  onClick={() => handleQuickTelegram(s.symbol)}
                >
                  {sentStatus[s.symbol] === 'sent'
                    ? 'ارسال شد ✅'
                    : sentStatus[s.symbol] === 'error'
                    ? 'خطا ⚠️'
                    : sendingSymbol === s.symbol
                    ? 'در حال ارسال…'
                    : 'ارسال به تلگرام'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
