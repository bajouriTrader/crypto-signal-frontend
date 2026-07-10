import { useEffect, useMemo, useRef, useState } from 'react'
import SignalChart from './SignalChart'

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

function DemoTradePanel({ signal, initialOpenTrade }) {
  const [status, setStatus] = useState('idle') // 'idle'|'starting'|'open'|'win'|'loss'|'timeout_win'|'timeout_loss'|'error'
  const [trade, setTrade] = useState(null)
  const [open, setOpen] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const pollRef = useRef(null)
  const elapsedTimerRef = useRef(null)

  const stopTimers = () => {
    clearInterval(pollRef.current)
    clearInterval(elapsedTimerRef.current)
  }

  const startElapsedFrom = (openedAtSeconds) => {
    const startingElapsed = Math.max(0, Math.floor(Date.now() / 1000 - openedAtSeconds))
    setElapsed(startingElapsed)
    elapsedTimerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000)
  }

  // بازیابی خودکار: اگه از بک‌اند معلوم شد این ارز از قبل پوزیشن باز داره،
  // به‌جای خالی نشون دادن پنل، همون رو بازسازی می‌کنیم (حتی بعد از رفرش صفحه)
  useEffect(() => {
    if (initialOpenTrade && !trade) {
      setTrade(initialOpenTrade)
      setStatus(initialOpenTrade.status)
      setOpen(true)
      startElapsedFrom(initialOpenTrade.opened_at)
      if (initialOpenTrade.status === 'open') {
        pollRef.current = setInterval(() => pollStatus(initialOpenTrade.trade_id), 15000)
      }
    }
    return () => stopTimers()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialOpenTrade])

  const pollStatus = async (tradeId) => {
    try {
      const res = await fetch(`${API_BASE_URL}/demo-trade/status/${tradeId}`)
      const data = await res.json()
      if (!res.ok) throw new Error('trade not found')
      setTrade(data)
      if (data.status !== 'open') {
        setStatus(data.status)
        clearInterval(pollRef.current)
      }
    } catch {
      // موقتاً نادیده می‌گیریم، سیکل بعدی دوباره امتحان می‌کنه
    }
  }

  const startDemo = async () => {
    setOpen(true)
    setStatus('starting')
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
          mode: signal.mode || 'strict',
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error('شروع تست زنده ناموفق بود')
      setTrade(data)
      setStatus(data.status)
      startElapsedFrom(data.opened_at)
      if (data.status === 'open') {
        pollRef.current = setInterval(() => pollStatus(data.trade_id), 15000)
      }
    } catch {
      setStatus('error')
    }
  }

  const formatDuration = (sec) => {
    const h = Math.floor(sec / 3600)
    const m = Math.floor((sec % 3600) / 60)
    if (h > 0) return `${h} ساعت و ${m} دقیقه`
    return `${m} دقیقه و ${sec % 60} ثانیه`
  }

  const isResolved = ['win', 'loss', 'timeout_win', 'timeout_loss'].includes(status)
  const isWin = status === 'win' || status === 'timeout_win'
  const isTimeout = status === 'timeout_win' || status === 'timeout_loss'

  // فقط وقتی مقادیر واقعی معامله عوض بشه بازسازی می‌شه، نه هر ثانیه با تیک شمارنده
  const chartSignal = useMemo(() => {
    if (!trade) return null
    return {
      symbol: trade.symbol,
      direction: trade.direction,
      entries: [trade.entry],
      targets: [trade.target],
      stop_loss: trade.stop_loss,
    }
  }, [trade?.symbol, trade?.direction, trade?.entry, trade?.target, trade?.stop_loss])

  return (
    <>
      <button
        className="btn-mini"
        onClick={startDemo}
        disabled={status === 'starting' || status === 'open'}
      >
        {status === 'open'
          ? `در حال رصد… ${elapsed}s`
          : status === 'starting'
          ? 'در حال شروع…'
          : isResolved
          ? 'مشاهده‌ی نتیجه'
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
              ⏳ پوزیشن دمو باز است — رصد زنده قیمت (حداکثر تا {signal.max_hold_hours || 4} ساعت تکلیفش مشخص می‌شه)
              {trade.current_price && (
                <div dir="ltr" className="demo-current-price">
                  قیمت فعلی: {trade.current_price}
                </div>
              )}
            </div>
          )}

          {trade && (status === 'open' || isResolved) && (
            <SignalChart parsedSignal={chartSignal} interval="5m" />
          )}

          {isResolved && trade && (
            <>
              <div className={`demo-result-badge ${isWin ? 'demo-win' : 'demo-loss'}`}>
                {isWin ? '✅ به سود رسید' : '❌ به ضرر رسید'}
                {isTimeout && ' (پایان بازه‌ی ۴ ساعته)'}
              </div>
              <div className="backtest-grid">
                <div>
                  <span className="detail-label">حالت</span>
                  <div className="detail-value">{trade.mode === 'relaxed' ? 'ساده‌گیر' : 'سخت‌گیر'}</div>
                </div>
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

function SignalRow({ signal, index, onFullAnalyze, isAnalyzing, mode }) {
  const [remaining, startCooldown] = useCountdown(ROW_REFRESH_COOLDOWN)
  const [refreshing, setRefreshing] = useState(false)
  const [rowData, setRowData] = useState(signal)
  const [demoExchangeStatus, setDemoExchangeStatus] = useState(null)
  const [liveExchangeStatus, setLiveExchangeStatus] = useState(null)

  useEffect(() => setRowData(signal), [signal])

  const handleRowRefresh = async () => {
    setRefreshing(true)
    try {
      const res = await fetch(`${API_BASE_URL}/refresh-signal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: rowData.symbol, mode }),
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

  const handleSendToExchange = async (target) => {
    const setter = target === 'live' ? setLiveExchangeStatus : setDemoExchangeStatus
    setter('sending')
    try {
      const res = await fetch(`${API_BASE_URL}/send-to-exchange-${target}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: rowData.symbol }),
      })
      const data = await res.json()
      setter(data.status === 'coming_soon' ? 'soon' : 'sent')
    } catch {
      setter('error')
    } finally {
      setTimeout(() => setter(null), 4000)
    }
  }

  const hasSignal = rowData.direction && rowData.entry !== null && rowData.entry !== undefined
  const isTriggered = rowData.signal_available

  return (
    <div className="watchlist-card">
      <div className="watchlist-card-top">
        <span className="watchlist-rank">{index + 1}</span>
        <span className="watchlist-symbol">{rowData.symbol}</span>
        {rowData.direction && (
          <span className={`watchlist-direction ${rowData.direction === 'long' ? 'dir-long' : 'dir-short'}`}>
            {rowData.direction === 'long' ? 'لانگ' : 'شورت'}
          </span>
        )}
        <span className={`watchlist-score-badge ${scoreLevel(rowData.confluence_score)}`}>
          {rowData.confluence_score}%
        </span>
        {hasSignal && !isTriggered && (
          <span className="watchlist-pending-badge">در انتظار تریگر ۱۵m/۵m</span>
        )}
        {rowData.open_trade?.stale_warning && (
          <span className="watchlist-stale-badge">⚠️ بیش از {rowData.max_hold_hours || 4} ساعته بازه</span>
        )}
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

      {!hasSignal && (
        <div className="watchlist-no-signal">
          {(rowData.reasons || []).join(' — ') || 'روند تایم‌فریم‌های مختلف هم‌جهت نیست، سیگنالی صادر نشده.'}
        </div>
      )}

      {hasSignal && (
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
      )}

      <div className="watchlist-actions">
        <button
          className="btn-mini btn-mini-primary"
          disabled={isAnalyzing}
          onClick={() => onFullAnalyze(rowData.symbol)}
        >
          {isAnalyzing ? 'در حال تحلیل…' : 'تحلیل کامل'}
        </button>
        <button
          className="btn-mini"
          disabled={demoExchangeStatus === 'sending' || !hasSignal}
          onClick={() => handleSendToExchange('demo')}
        >
          {demoExchangeStatus === 'soon'
            ? 'به‌زودی 🚧'
            : demoExchangeStatus === 'sending'
            ? 'در حال ارسال…'
            : 'ارسال به صرافی (دمو تست)'}
        </button>
        <button
          className="btn-mini"
          disabled={liveExchangeStatus === 'sending' || !hasSignal}
          onClick={() => handleSendToExchange('live')}
        >
          {liveExchangeStatus === 'soon'
            ? 'به‌زودی 🚧'
            : liveExchangeStatus === 'sending'
            ? 'در حال ارسال…'
            : 'ارسال به صرافی (لایو واقعی)'}
        </button>
        {hasSignal && <DemoTradePanel signal={rowData} initialOpenTrade={rowData.open_trade} />}
      </div>
    </div>
  )
}

export default function AutoSignalList({ onFullAnalyze, isAnalyzing }) {
  const [signals, setSignals] = useState([])
  const [status, setStatus] = useState('loading')
  const [isPartial, setIsPartial] = useState(false)
  const [filter, setFilter] = useState('all')
  const [mode, setMode] = useState('strict') // 'strict' | 'relaxed'
  const [globalRemaining, startGlobalCooldown] = useCountdown(GLOBAL_REFRESH_COOLDOWN)
  const [globalRefreshing, setGlobalRefreshing] = useState(false)

  const loadList = async (activeMode) => {
    try {
      const res = await fetch(`${API_BASE_URL}/watchlist-signals?limit=20&mode=${activeMode}`)
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
      const data = await loadList(mode)
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
  }, [mode])

  const handleGlobalRefresh = async () => {
    setGlobalRefreshing(true)
    await loadList(mode)
    setGlobalRefreshing(false)
    startGlobalCooldown()
  }

  const filteredSignals = signals.filter((s) => filter === 'all' || s.direction === filter)

  return (
    <section className="watchlist-panel">
      <div className="mode-toggle">
        <label className={`mode-option ${mode === 'strict' ? 'mode-option-active' : ''}`}>
          <input
            type="radio"
            name="signal-mode"
            checked={mode === 'strict'}
            onChange={() => setMode('strict')}
          />
          سخت‌گیر (دقت بالاتر، سیگنال کمتر)
        </label>
        <label className={`mode-option ${mode === 'relaxed' ? 'mode-option-active' : ''}`}>
          <input
            type="radio"
            name="signal-mode"
            checked={mode === 'relaxed'}
            onChange={() => setMode('relaxed')}
          />
          ساده‌گیر (سیگنال بیشتر، دقت پایین‌تر)
        </label>
      </div>

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
              mode={mode}
            />
          ))}
        </div>
      )}
    </section>
  )
}
