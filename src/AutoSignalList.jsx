import { useEffect, useRef, useState } from 'react'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'
const GLOBAL_REFRESH_COOLDOWN = 30
const ROW_REFRESH_COOLDOWN = 30

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

function useCountdown(seconds) {
  const [remaining, setRemaining] = useState(0)
  const timerRef = useRef(null)

  const start = () => {
    setRemaining(seconds)
    clearInterval(timerRef.current)
    timerRef.current = setInterval(() => {
      setRemaining((r) => {
        if (r <= 1) {
          clearInterval(timerRef.current)
          return 0
        }
        return r - 1
      })
    }, 1000)
  }

  useEffect(() => () => clearInterval(timerRef.current), [])
  return [remaining, start]
}

function DemoTradePanel({ signal }) {
  const [status, setStatus] = useState('idle') // 'idle' | 'starting' | 'open' | 'win' | 'loss' | 'error'
  const [trade, setTrade] = useState(null)
  const [open, setOpen] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const pollRef = useRef(null)
  const elapsedTimerRef = useRef(null)

  const stopTimers = () => {
    clearInterval(pollRef.current)
    clearInterval(elapsedTimerRef.current)
  }

  useEffect(() => () => stopTimers(), [])

  const pollStatus = async (tradeId) => {
    try {
      const res = await fetch(`${API_BASE_URL}/demo-trade/status/${tradeId}`)
      const data = await res.json()
      if (!res.ok) throw new Error('trade not found')
      setTrade(data)
      if (data.status !== 'open') {
        setStatus(data.status)
        stopTimers()
      }
    } catch {
      // موقتاً نادیده می‌گیریم، سیکل بعدی دوباره امتحان می‌کنه
    }
  }

  const startDemo = async () => {
    setOpen(true)
    setStatus('starting')
    setElapsed(0)
    try {
      const res = await fetch(`${API_BASE_URL}/demo-trade/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: signal.symbol,
          direction: signal.direction,
          entry: signal.entry,
          target: signal.target,
          stop_loss: signal.stop_loss,
          leverage: signal.suggested_leverage,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error('شروع تست زنده ناموفق بود')
      setTrade(data)
      setStatus('open')

      elapsedTimerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000)
      pollRef.current = setInterval(() => pollStatus(data.trade_id), 15000)
    } catch {
      setStatus('error')
    }
  }

  const formatDuration = (sec) => {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return m > 0 ? `${m} دقیقه و ${s} ثانیه` : `${s} ثانیه`
  }

  return (
    <>
      <button className="btn-mini" onClick={startDemo} disabled={status === 'starting' || status === 'open'}>
        {status === 'open'
          ? `در حال رصد… ${elapsed}s`
          : status === 'starting'
          ? 'در حال شروع…'
          : 'تست زنده سیگنال'}
      </button>

      {open && (
        <div className="backtest-panel">
          {status === 'starting' && (
            <div className="backtest-status">در حال باز کردن پوزیشن دمو…</div>
          )}
          {status === 'error' && (
            <div className="backtest-status">شروع تست زنده ناموفق بود، دوباره امتحان کن.</div>
          )}
          {status === 'open' && trade && (
            <div className="backtest-status">
              ⏳ پوزیشن دمو باز است — رصد زنده قیمت (هر ۱۵ ثانیه بروزرسانی می‌شه)
              {trade.current_price && (
                <div dir="ltr" className="demo-current-price">
                  قیمت فعلی: {trade.current_price}
                </div>
              )}
            </div>
          )}
          {(status === 'win' || status === 'loss') && trade && (
            <>
              <div className={`demo-result-badge ${status === 'win' ? 'demo-win' : 'demo-loss'}`}>
                {status === 'win' ? '✅ به هدف خورد' : '❌ به حد ضرر خورد'}
              </div>
              <div className="backtest-grid">
                <div>
                  <span className="detail-label">ورود</span>
                  <div dir="ltr" className="detail-value">{trade.entry}</div>
                </div>
                <div>
                  <span className="detail-label">خروج</span>
                  <div dir="ltr" className="detail-value">{trade.exit_price}</div>
                </div>
                <div>
                  <span className="detail-label">مدت زمان</span>
                  <div className="detail-value">{formatDuration(elapsed)}</div>
                </div>
              </div>
            </>
          )}
          <button className="btn-mini backtest-close" onClick={() => { stopTimers(); setOpen(false) }}>
            بستن
          </button>
        </div>
      )}
    </>
  )
}

function SignalRow({ signal, index, onFullAnalyze, isAnalyzing }) {
  const [remaining, startCooldown] = useCountdown(ROW_REFRESH_COOLDOWN)
  const [refreshing, setRefreshing] = useState(false)
  const [rowData, setRowData] = useState(signal)
  const [exchangeStatus, setExchangeStatus] = useState(null)

  useEffect(() => setRowData(signal), [signal])

  const handleRowRefresh = async () => {
    setRefreshing(true)
    try {
      const res = await fetch(`${API_BASE_URL}/refresh-signal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: rowData.symbol }),
      })
      const data = await res.json()
      if (res.ok) {
        setRowData(data)
        startCooldown()
      }
    } catch {
      // بی‌صدا نادیده می‌گیریم، کاربر می‌تونه دوباره امتحان کنه
    } finally {
      setRefreshing(false)
    }
  }

  const handleSendToExchange = async () => {
    setExchangeStatus('sending')
    try {
      const res = await fetch(`${API_BASE_URL}/send-to-exchange`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: rowData.symbol }),
      })
      const data = await res.json()
      setExchangeStatus(data.status === 'coming_soon' ? 'soon' : 'sent')
    } catch {
      setExchangeStatus('error')
    } finally {
      setTimeout(() => setExchangeStatus(null), 4000)
    }
  }

  return (
    <div className="watchlist-card">
      <div className="watchlist-card-top">
        <span className="watchlist-rank">{index + 1}</span>
        <span className="watchlist-symbol">{rowData.symbol}</span>
        <span className={`watchlist-direction ${rowData.direction === 'long' ? 'dir-long' : 'dir-short'}`}>
          {rowData.direction === 'long' ? 'لانگ' : 'شورت'}
        </span>
        <span className={`watchlist-score-badge ${scoreLevel(rowData.confluence_score)}`}>
          {rowData.confluence_score}%
        </span>
        <span className="watchlist-time">{timeAgo(rowData.last_updated)}</span>
        <button
          className="row-refresh-btn"
          onClick={handleRowRefresh}
          disabled={refreshing || remaining > 0}
          title="رفرش این ارز"
        >
          {refreshing ? '…' : remaining > 0 ? `${remaining}s` : '↻'}
        </button>
      </div>

      <div className="watchlist-details">
        <div className="watchlist-detail-item">
          <span className="detail-label">ورود</span>
          <span dir="ltr" className="detail-value">{rowData.entry}</span>
        </div>
        <div className="watchlist-detail-item">
          <span className="detail-label">هدف</span>
          <span dir="ltr" className="detail-value detail-target">{rowData.target}</span>
        </div>
        <div className="watchlist-detail-item">
          <span className="detail-label">حد ضرر</span>
          <span dir="ltr" className="detail-value detail-stop">{rowData.stop_loss}</span>
        </div>
        <div className="watchlist-detail-item">
          <span className="detail-label">اهرم</span>
          <span dir="ltr" className="detail-value">{rowData.suggested_leverage}x</span>
        </div>
      </div>

      <div className="watchlist-actions">
        <button
          className="btn-mini btn-mini-primary"
          disabled={isAnalyzing}
          onClick={() => onFullAnalyze(rowData.symbol)}
        >
          {isAnalyzing ? 'در حال تحلیل…' : 'تحلیل کامل'}
        </button>
        <button className="btn-mini" disabled={exchangeStatus === 'sending'} onClick={handleSendToExchange}>
          {exchangeStatus === 'soon'
            ? 'به‌زودی 🚧'
            : exchangeStatus === 'sending'
            ? 'در حال ارسال…'
            : 'ارسال به صرافی'}
        </button>
        <DemoTradePanel signal={rowData} />
      </div>
    </div>
  )
}

export default function AutoSignalList({ onFullAnalyze, isAnalyzing }) {
  const [signals, setSignals] = useState([])
  const [status, setStatus] = useState('loading')
  const [isPartial, setIsPartial] = useState(false)
  const [filter, setFilter] = useState('all')
  const [globalRemaining, startGlobalCooldown] = useCountdown(GLOBAL_REFRESH_COOLDOWN)
  const [globalRefreshing, setGlobalRefreshing] = useState(false)

  const loadList = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/watchlist-signals?limit=20`)
      if (!res.ok) throw new Error('خطا در دریافت لیست')
      const data = await res.json()
      setSignals(data.signals || [])
      setStatus('ready')
      setIsPartial((data.count || 0) < (data.total_watchlist_size || 20))
      return data
    } catch {
      setStatus('error')
      return null
    }
  }

  useEffect(() => {
    let cancelled = false
    let pollTimer = null

    async function initialLoad() {
      const data = await loadList()
      if (!cancelled && data && (data.count || 0) < (data.total_watchlist_size || 20)) {
        pollTimer = setTimeout(initialLoad, 15000)
      }
    }

    setStatus('loading')
    initialLoad()
    return () => {
      cancelled = true
      if (pollTimer) clearTimeout(pollTimer)
    }
  }, [])

  const handleGlobalRefresh = async () => {
    setGlobalRefreshing(true)
    await loadList()
    setGlobalRefreshing(false)
    startGlobalCooldown()
  }

  const filteredSignals = signals.filter((s) => filter === 'all' || s.direction === filter)

  return (
    <section className="watchlist-panel">
      <div className="watchlist-head">
        <div className="watchlist-head-top">
          <h2 className="watchlist-title">سیگنال‌های خودکار پلتفرم</h2>
          <div className="watchlist-head-actions">
            <div className="watchlist-filters">
              <button className={`filter-chip ${filter === 'all' ? 'filter-chip-active' : ''}`} onClick={() => setFilter('all')}>
                همه
              </button>
              <button className={`filter-chip ${filter === 'long' ? 'filter-chip-active' : ''}`} onClick={() => setFilter('long')}>
                فقط لانگ
              </button>
              <button className={`filter-chip ${filter === 'short' ? 'filter-chip-active' : ''}`} onClick={() => setFilter('short')}>
                فقط شورت
              </button>
            </div>
            <button
              className="filter-chip refresh-chip"
              disabled={globalRefreshing || globalRemaining > 0}
              onClick={handleGlobalRefresh}
            >
              {globalRefreshing ? 'Refreshing…' : globalRemaining > 0 ? `Refresh (${globalRemaining}s)` : '↻ Refresh'}
            </button>
          </div>
        </div>
        <span className="watchlist-sub">
          بر اساس اندیکاتورهای تکنیکال، مرتب‌شده بر اساس امتیاز
          {isPartial && ' — لیست در حال تکمیل شدنه'}
        </span>
      </div>

      {status === 'loading' && <div className="watchlist-status">در حال دریافت لیست…</div>}
      {status === 'error' && <div className="watchlist-status">دریافت لیست با خطا مواجه شد.</div>}
      {status === 'ready' && filteredSignals.length === 0 && (
        <div className="watchlist-status">موردی با این فیلتر پیدا نشد.</div>
      )}

      {status === 'ready' && filteredSignals.length > 0 && (
        <div className="watchlist-list">
          {filteredSignals.map((s, index) => (
            <SignalRow
              key={s.symbol}
              signal={s}
              index={index}
              onFullAnalyze={onFullAnalyze}
              isAnalyzing={isAnalyzing}
            />
          ))}
        </div>
      )}
    </section>
  )
}
