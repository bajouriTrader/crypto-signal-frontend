import { useEffect, useState } from 'react'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

function scoreLevel(score) {
  if (score >= 70) return 'score-high'
  if (score >= 45) return 'score-mid'
  return 'score-low'
}

function timeAgo(epochSeconds) {
  if (!epochSeconds) return ''
  const diff = Math.max(0, Date.now() / 1000 - epochSeconds)
  if (diff < 90) return 'همین الان'
  const minutes = Math.round(diff / 60)
  if (minutes < 60) return `${minutes} دقیقه پیش`
  const hours = Math.round(minutes / 60)
  return `${hours} ساعت پیش`
}

export default function AutoSignalList({ onFullAnalyze }) {
  const [signals, setSignals] = useState([])
  const [status, setStatus] = useState('loading') // 'loading' | 'ready' | 'error'
  const [isPartial, setIsPartial] = useState(false)
  const [filter, setFilter] = useState('all') // 'all' | 'long' | 'short'
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

  const filteredSignals = signals.filter((s) => filter === 'all' || s.direction === filter)

  return (
    <section className="watchlist-panel">
      <div className="watchlist-head">
        <div className="watchlist-head-top">
          <h2 className="watchlist-title">سیگنال‌های خودکار پلتفرم</h2>
          <div className="watchlist-filters">
            <button
              className={`filter-chip ${filter === 'all' ? 'filter-chip-active' : ''}`}
              onClick={() => setFilter('all')}
            >
              همه
            </button>
            <button
              className={`filter-chip ${filter === 'long' ? 'filter-chip-active' : ''}`}
              onClick={() => setFilter('long')}
            >
              فقط لانگ
            </button>
            <button
              className={`filter-chip ${filter === 'short' ? 'filter-chip-active' : ''}`}
              onClick={() => setFilter('short')}
            >
              فقط شورت
            </button>
          </div>
        </div>
        <span className="watchlist-sub">
          بر اساس اندیکاتورهای تکنیکال، مرتب‌شده بر اساس امتیاز
          {isPartial && ' — لیست در حال تکمیل شدنه'}
        </span>
      </div>

      {status === 'loading' && (
        <div className="watchlist-status">در حال دریافت لیست…</div>
      )}
      {status === 'error' && (
        <div className="watchlist-status">دریافت لیست با خطا مواجه شد.</div>
      )}
      {status === 'ready' && filteredSignals.length === 0 && (
        <div className="watchlist-status">موردی با این فیلتر پیدا نشد.</div>
      )}

      {status === 'ready' && filteredSignals.length > 0 && (
        <div className="watchlist-list">
          {filteredSignals.map((s, index) => (
            <div className="watchlist-card" key={s.symbol}>
              <div className="watchlist-card-top">
                <span className="watchlist-rank">{index + 1}</span>
                <span className="watchlist-symbol">{s.symbol}</span>
                <span
                  className={`watchlist-direction ${
                    s.direction === 'long' ? 'dir-long' : 'dir-short'
                  }`}
                >
                  {s.direction === 'long' ? 'لانگ' : 'شورت'}
                </span>
                <span className={`watchlist-score-badge ${scoreLevel(s.confluence_score)}`}>
                  {s.confluence_score}%
                </span>
                <span className="watchlist-time">{timeAgo(s.last_updated)}</span>
              </div>

              <div className="watchlist-details">
                <div className="watchlist-detail-item">
                  <span className="detail-label">ورود</span>
                  <span dir="ltr" className="detail-value">{s.entry}</span>
                </div>
                <div className="watchlist-detail-item">
                  <span className="detail-label">هدف</span>
                  <span dir="ltr" className="detail-value detail-target">{s.target}</span>
                </div>
                <div className="watchlist-detail-item">
                  <span className="detail-label">حد ضرر</span>
                  <span dir="ltr" className="detail-value detail-stop">{s.stop_loss}</span>
                </div>
                <div className="watchlist-detail-item">
                  <span className="detail-label">اهرم</span>
                  <span dir="ltr" className="detail-value">{s.suggested_leverage}x</span>
                </div>
              </div>

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
