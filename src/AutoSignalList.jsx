import { authFetch } from './auth'
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

function modeLabel(mode) {
  if (mode === 'relaxed') return 'ساده‌گیر'
  if (mode === 'manual') return 'دستی'
  return 'سخت‌گیر'
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

// ---------------------------------------------------------------------------
// دکمه‌ی «ارسال به صرافی» — جدا شده تا هم توی کارت واچ‌لیست خودکار، هم زیر
// نتیجه‌ی تحلیل دستی (App.jsx) قابل استفاده باشه بدون تکرار کد
// ---------------------------------------------------------------------------
export function SendToExchangeButton({ symbol, hasSignal, className = 'btn-mini' }) {
  const [liveExchangeStatus, setLiveExchangeStatus] = useState(null)

  const handleSendToExchange = async () => {
    setLiveExchangeStatus('sending')
    try {
      const res = await authFetch(`${API_BASE_URL}/send-to-exchange-live`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol }),
      })
      const data = await res.json()
      setLiveExchangeStatus(data.status === 'coming_soon' ? 'soon' : 'sent')
    } catch {
      setLiveExchangeStatus('error')
    } finally {
      setTimeout(() => setLiveExchangeStatus(null), 4000)
    }
  }

  return (
    <button
      className={className}
      disabled={liveExchangeStatus === 'sending' || !hasSignal}
      onClick={handleSendToExchange}
    >
      {liveExchangeStatus === 'soon'
        ? 'به‌زودی 🚧'
        : liveExchangeStatus === 'sending'
        ? 'در حال ارسال…'
        : liveExchangeStatus === 'sent'
        ? 'ارسال شد ✅'
        : liveExchangeStatus === 'error'
        ? 'خطا در ارسال'
        : 'ارسال به صرافی (حساب ریل)'}
    </button>
  )
}

// ---------------------------------------------------------------------------
// پنل تست زنده (Paper Trade) — از App.jsx (تحلیل دستی) هم export و استفاده می‌شه
// ---------------------------------------------------------------------------
export function DemoTradePanel({ signal, initialOpenTrade }) {
  const [status, setStatus] = useState('idle') // 'idle'|'configuring'|'starting'|'open'|'win'|'loss'|'timeout_win'|'timeout_loss'|'manual_win'|'manual_loss'|'closing'|'error'
  const [trade, setTrade] = useState(null)
  const [open, setOpen] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [livePrice, setLivePrice] = useState(null)
  const [marginInput, setMarginInput] = useState('10')
  const [leverageInput, setLeverageInput] = useState(String(signal.suggested_leverage || 5))
  const pollRef = useRef(null)
  const elapsedTimerRef = useRef(null)
  const livePriceTimerRef = useRef(null)

  const stopTimers = () => {
    clearInterval(pollRef.current)
    clearInterval(elapsedTimerRef.current)
    clearInterval(livePriceTimerRef.current)
  }

  const startElapsedFrom = (openedAtSeconds) => {
    const startingElapsed = Math.max(0, Math.floor(Date.now() / 1000 - openedAtSeconds))
    setElapsed(startingElapsed)
    elapsedTimerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000)
  }

  // تایمر سبک و سریع (هر ۸ ثانیه) فقط برای قیمت لحظه‌ای — جدا از poll سنگین‌تر
  // وضعیت (که هر ۱۵ ثانیه‌ست و کندل چک می‌کنه)، تا سود/زیان واقعاً «زنده»‌تر باشه
  const [priceRefreshing, setPriceRefreshing] = useState(false)

  const fetchLivePriceNow = async (symbol, showSpinner = false) => {
    if (showSpinner) setPriceRefreshing(true)
    try {
      const res = await authFetch(`${API_BASE_URL}/live-price/${symbol}`)
      if (res.ok) {
        const data = await res.json()
        if (typeof data.price === 'number') setLivePrice(data.price)
      }
    } catch {
      // خطای موقت رو نادیده می‌گیریم
    } finally {
      if (showSpinner) setPriceRefreshing(false)
    }
  }

  const startLivePriceTicker = (symbol) => {
    fetchLivePriceNow(symbol)
    livePriceTimerRef.current = setInterval(() => fetchLivePriceNow(symbol), 8000)
  }

  // بازیابی خودکار: اگه از بک‌اند معلوم شد این ارز از قبل پوزیشن باز داره،
  // به‌جای خالی نشون دادن پنل، همون رو بازسازی می‌کنیم (حتی بعد از رفرش صفحه)
  useEffect(() => {
    if (initialOpenTrade && !trade) {
      setTrade(initialOpenTrade)
      setStatus(initialOpenTrade.status)
      setOpen(true)
      if (initialOpenTrade.status === 'open') {
        startElapsedFrom(initialOpenTrade.opened_at)
        pollRef.current = setInterval(() => pollStatus(initialOpenTrade.trade_id), 15000)
        startLivePriceTicker(initialOpenTrade.symbol)
      } else if (initialOpenTrade.closed_at) {
        // نتیجه‌ی تازه‌بسته‌شده — دیگه نیازی به تایمر زنده نیست، فقط مدت‌زمان نهایی رو نشون بده
        setElapsed(Math.max(0, Math.floor(initialOpenTrade.closed_at - initialOpenTrade.opened_at)))
      }
    }
    return () => stopTimers()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialOpenTrade?.trade_id, initialOpenTrade?.status])

  const pollStatus = async (tradeId) => {
    try {
      const res = await authFetch(`${API_BASE_URL}/demo-trade/status/${tradeId}`)
      const data = await res.json()
      if (!res.ok) throw new Error('trade not found')
      setTrade(data)
      if (data.status !== 'open') {
        setStatus(data.status)
        clearInterval(pollRef.current)
        clearInterval(elapsedTimerRef.current)
        clearInterval(livePriceTimerRef.current)
        if (data.closed_at) {
          setElapsed(Math.max(0, Math.floor(data.closed_at - data.opened_at)))
        }
      }
    } catch {
      // موقتاً نادیده می‌گیریم، سیکل بعدی دوباره امتحان می‌کنه
    }
  }

  const startDemo = async () => {
    let live = signal

    // فقط برای سیگنال‌های واچ‌لیست (نه ورود دستی) قبل از باز کردن پوزیشن،
    // یه رفرش زنده می‌گیریم تا با مقادیر قدیمی/منقضی پوزیشن باز نشه
    if (signal.mode === 'strict' || signal.mode === 'relaxed') {
      setStatus('starting')
      try {
        const refreshRes = await authFetch(`${API_BASE_URL}/refresh-signal`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol: signal.symbol, mode: signal.mode }),
        })
        if (refreshRes.ok) {
          const fresh = await refreshRes.json()
          if (!fresh.signal_available) {
            setStatus('error')
            return
          }
          live = fresh
        }
        // اگه ۴۲۹ (کول‌داون اخیر) بود، یعنی دیتای فعلی همین چند ثانیه پیش
        // تازه بوده — همون signal فعلی رو معتبر در نظر می‌گیریم و ادامه می‌دیم
      } catch {
        // خطای شبکه‌ی موقت در رفرش — با آخرین دیتای موجود ادامه می‌دیم
      }
    }

    setStatus('starting')
    try {
      const res = await authFetch(`${API_BASE_URL}/demo-trade/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: live.symbol,
          direction: live.direction,
          entry: live.entry,
          target: live.target,
          stop_loss: live.stop_loss,
          leverage: parseFloat(leverageInput) || 5,
          mode: live.mode || signal.mode || 'strict',
          margin_usdt: parseFloat(marginInput) || 10,
          confluence_score: live.confluence_score ?? null,
          diagnostics: live.diagnostics ?? null,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error('شروع تست زنده ناموفق بود')
      setTrade(data)
      setStatus(data.status)
      startElapsedFrom(data.opened_at)
      if (data.status === 'open') {
        pollRef.current = setInterval(() => pollStatus(data.trade_id), 15000)
        startLivePriceTicker(data.symbol)
      }
    } catch {
      setStatus('error')
    }
  }

  const closeManually = async () => {
    if (!trade) return
    setStatus('closing')
    try {
      const res = await authFetch(`${API_BASE_URL}/demo-trade/close/${trade.trade_id}`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error('بستن پوزیشن ناموفق بود')
      setTrade(data)
      setStatus(data.status)
      clearInterval(pollRef.current)
      clearInterval(elapsedTimerRef.current)
      clearInterval(livePriceTimerRef.current)
      if (data.closed_at) {
        setElapsed(Math.max(0, Math.floor(data.closed_at - data.opened_at)))
      }
    } catch {
      setStatus('open') // برگردون به حالت باز، کاربر می‌تونه دوباره امتحان کنه
    }
  }

  const formatDuration = (sec) => {
    const h = Math.floor(sec / 3600)
    const m = Math.floor((sec % 3600) / 60)
    if (h > 0) return `${h} ساعت و ${m} دقیقه`
    return `${m} دقیقه و ${sec % 60} ثانیه`
  }

  const isResolved = ['win', 'loss', 'timeout_win', 'timeout_loss', 'manual_win', 'manual_loss'].includes(status)
  const isWin = status === 'win' || status === 'timeout_win' || status === 'manual_win'
  const isTimeout = status === 'timeout_win' || status === 'timeout_loss'
  const isManual = status === 'manual_win' || status === 'manual_loss'

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

  const handleMainClick = () => {
    if (isResolved) {
      setOpen(true)
      return
    }
    setOpen(true)
    setStatus('configuring')
  }

  const renderLiveStatus = (key) => {
    if (status !== 'open' || !trade) return null
    const price = livePrice ?? trade.current_price
    return (
      <div className="backtest-status" key={key}>
        ⏳ پوزیشن دمو باز است ({trade.margin_usdt}$ با اهرم {trade.leverage}x) — رصد زنده قیمت
        (حداکثر تا {signal.max_hold_hours || 4} ساعت تکلیفش مشخص می‌شه)
        {price && (() => {
          const qty = trade.quantity || 0
          const unrealizedPnl =
            trade.direction === 'long'
              ? qty * (price - trade.entry)
              : qty * (trade.entry - price)
          return (
            <>
              <div className="demo-price-row">
                <span className="demo-row-label">قیمت لحظه‌ای:</span>
                <span dir="ltr" className="demo-current-price">{price}</span>
              </div>
              <div className="demo-price-row">
                <span className="demo-row-label">سود/زیان لحظه‌ای:</span>
                <span
                  dir="ltr"
                  className={`demo-unrealized-pnl ${unrealizedPnl >= 0 ? 'detail-target' : 'detail-stop'}`}
                >
                  {unrealizedPnl >= 0 ? '+' : ''}
                  {unrealizedPnl.toFixed(4)}$
                </span>
                <button
                  className="pnl-refresh-btn"
                  onClick={() => fetchLivePriceNow(trade.symbol, true)}
                  disabled={priceRefreshing}
                  title="رفرش دستی قیمت و سود/زیان"
                >
                  {priceRefreshing ? '…' : '↻'}
                </button>
              </div>
            </>
          )
        })()}
        <button className="btn-mini demo-manual-close" onClick={closeManually}>
          بستن دستی پوزیشن
        </button>
      </div>
    )
  }

  return (
    <>
      <button
        className="btn-mini"
        onClick={handleMainClick}
        disabled={status === 'starting' || status === 'open' || status === 'closing'}
      >
        {status === 'open'
          ? `در حال رصد… ${elapsed}s`
          : status === 'starting'
          ? 'در حال شروع…'
          : status === 'closing'
          ? 'در حال بستن…'
          : isResolved
          ? 'مشاهده‌ی نتیجه'
          : 'تست زنده سیگنال'}
      </button>

      {open && (
        <div className="backtest-panel">
          {status === 'configuring' && (
            <div className="demo-config-form">
              <div className="demo-config-row">
                <label>مبلغ ورودی (USDT)</label>
                <input
                  type="number"
                  value={marginInput}
                  onChange={(e) => setMarginInput(e.target.value)}
                  className="demo-config-input"
                  dir="ltr"
                />
              </div>
              <div className="demo-config-row">
                <label>اهرم</label>
                <div className="demo-config-input-wrap">
                  <input
                    type="number"
                    value={leverageInput}
                    onChange={(e) => setLeverageInput(e.target.value)}
                    className="demo-config-input"
                    dir="ltr"
                  />
                  <span className="demo-config-suffix">x</span>
                </div>
              </div>
              <button className="btn-mini btn-mini-primary" onClick={startDemo}>
                شروع پوزیشن دمو
              </button>
            </div>
          )}

          {status === 'starting' && (
            <div className="backtest-status">در حال باز کردن پوزیشن دمو…</div>
          )}
          {status === 'error' && (
            <div className="backtest-status">شروع تست زنده ناموفق بود، دوباره امتحان کن.</div>
          )}
          {status === 'open' && renderLiveStatus('top')}

          {trade && (status === 'open' || isResolved) && (
            <SignalChart parsedSignal={chartSignal} interval="5m" />
          )}

          {status === 'open' && renderLiveStatus('bottom')}

          {isResolved && trade && (
            <>
              <div className={`demo-result-badge ${isWin ? 'demo-win' : 'demo-loss'}`}>
                {isWin ? '✅ به سود رسید' : '❌ به ضرر رسید'}
                {isTimeout && ' (پایان بازه‌ی ۴ ساعته)'}
                {isManual && ' (بستن دستی)'}
              </div>
              <div className="backtest-grid">
                <div>
                  <span className="detail-label">حالت</span>
                  <div className="detail-value">{modeLabel(trade.mode)}</div>
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
                  <span className="detail-label">سود/زیان</span>
                  <div dir="ltr" className={`detail-value ${trade.realized_pnl >= 0 ? 'detail-target' : 'detail-stop'}`}>
                    {trade.realized_pnl >= 0 ? '+' : ''}{trade.realized_pnl}$
                  </div>
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

function WatchTickerRow({ signal }) {
  const hasSignal = signal.direction && signal.entry !== null && signal.entry !== undefined
  const canQuickStart = signal.signal_available && !signal.open_trade
  const [quickStatus, setQuickStatus] = useState('idle') // 'idle' | 'checking' | 'starting' | 'started' | 'expired' | 'error'

  const handleQuickStart = async () => {
    setQuickStatus('checking')
    try {
      // اول یه رفرش فوری و واقعی از بازار می‌گیریم — هیچ‌وقت با مقادیر
      // کش‌شده (که ممکنه چند دقیقه/ساعت قدیمی باشن) پوزیشن باز نمی‌کنیم
      const refreshRes = await authFetch(`${API_BASE_URL}/refresh-signal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: signal.symbol, mode: signal.mode }),
      })

      if (refreshRes.status === 429) {
        // اخیراً رفرش شده (کول‌داون) — یعنی دیتای فعلی همین چند ثانیه پیش تازه بوده، همونو معتبر می‌دونیم
      } else if (!refreshRes.ok) {
        setQuickStatus('error')
        return
      }

      const fresh = refreshRes.ok ? await refreshRes.json() : signal

      if (!fresh.signal_available) {
        // بعد از چک زنده، دیگه سیگنال معتبر نیست — روند/تریگر عوض شده
        setQuickStatus('expired')
        return
      }

      setQuickStatus('starting')
      const res = await authFetch(`${API_BASE_URL}/demo-trade/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: fresh.symbol,
          direction: fresh.direction,
          entry: fresh.entry,
          target: fresh.target,
          stop_loss: fresh.stop_loss,
          leverage: fresh.suggested_leverage || 5,
          mode: fresh.mode || signal.mode || 'strict',
          margin_usdt: 10,
          confluence_score: fresh.confluence_score ?? null,
          diagnostics: fresh.diagnostics ?? null,
        }),
      })
      setQuickStatus(res.ok ? 'started' : 'error')
    } catch {
      setQuickStatus('error')
    }
  }

  return (
    <div className="ticker-row">
      <span className="ticker-symbol">{signal.symbol}</span>
      {signal.direction && (
        <span className={`ticker-direction ${signal.direction === 'long' ? 'dir-long' : 'dir-short'}`}>
          {signal.direction === 'long' ? 'لانگ' : 'شورت'}
        </span>
      )}
      <span className={`ticker-score ${scoreLevel(signal.confluence_score)}`} dir="ltr">
        {signal.confluence_score}%
      </span>
      {signal.open_trade && <span className="ticker-live-badge">در تست زنده</span>}
      {hasSignal && !signal.signal_available && (
        <span className="ticker-pending">در انتظار تریگر</span>
      )}

      {canQuickStart && (quickStatus === 'idle' || quickStatus === 'expired' || quickStatus === 'error') && (
        <button className="ticker-quickstart-btn" onClick={handleQuickStart}>
          شروع تست زنده (۱۰$)
        </button>
      )}
      {quickStatus === 'checking' && <span className="ticker-pending">در حال بررسی زنده‌ی بازار…</span>}
      {quickStatus === 'starting' && <span className="ticker-pending">در حال شروع…</span>}
      {quickStatus === 'started' && <span className="ticker-live-badge">شروع شد ✅</span>}
      {quickStatus === 'expired' && <span className="ticker-pending">سیگنال قبلی منقضی شده بود — دوباره امتحان کن</span>}
      {quickStatus === 'error' && <span className="ticker-pending">خطا، دوباره امتحان کن</span>}

      <span className="ticker-time">{timeAgo(signal.last_updated)}</span>
    </div>
  )
}

function SignalRow({ signal, index, onFullAnalyze, isAnalyzing, mode }) {
  const [remaining, startCooldown] = useCountdown(ROW_REFRESH_COOLDOWN)
  const [refreshing, setRefreshing] = useState(false)
  const [rowData, setRowData] = useState(signal)

  useEffect(() => setRowData(signal), [signal])

  const handleRowRefresh = async () => {
    setRefreshing(true)
    try {
      const res = await authFetch(`${API_BASE_URL}/refresh-signal`, {
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
          onClick={() => onFullAnalyze(rowData.symbol, mode)}
        >
          {isAnalyzing ? 'در حال تحلیل…' : 'تحلیل کامل'}
        </button>
        <SendToExchangeButton symbol={rowData.symbol} hasSignal={hasSignal} />
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
  const [mode, setMode] = useState('relaxed') // 'strict' | 'relaxed'
  const [globalRemaining, startGlobalCooldown] = useCountdown(GLOBAL_REFRESH_COOLDOWN)
  const [globalRefreshing, setGlobalRefreshing] = useState(false)

  // تعداد سیگنال‌های *همین الان فعال و قابل‌معامله* برای هر دو حالت —
  // هر دو رو نگه می‌داریم تا هر دو برچسب (سخت‌گیر/ساده‌گیر) همیشه عدد
  // نشون بدن، نه فقط حالتی که همون لحظه انتخاب شده
  const [counts, setCounts] = useState({ strict: null, relaxed: null })

  const loadCounts = async () => {
    try {
      const [strictRes, relaxedRes] = await Promise.all([
        authFetch(`${API_BASE_URL}/watchlist-signals?limit=20&mode=strict`),
        authFetch(`${API_BASE_URL}/watchlist-signals?limit=20&mode=relaxed`),
      ])
      const [strictData, relaxedData] = await Promise.all([strictRes.json(), relaxedRes.json()])
      setCounts({
        strict: (strictData.signals || []).filter((s) => s.signal_available).length,
        relaxed: (relaxedData.signals || []).filter((s) => s.signal_available).length,
      })
    } catch {
      // بی‌صدا نادیده می‌گیریم، دفعه‌ی بعد دوباره تلاش می‌شه
    }
  }

  const loadList = async (activeMode) => {
    try {
      const res = await authFetch(`${API_BASE_URL}/watchlist-signals?limit=20&mode=${activeMode}`)
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
    loadCounts()
    return () => {
      cancelled = true
      if (pollTimer) clearTimeout(pollTimer)
    }
  }, [mode])

  const handleGlobalRefresh = async () => {
    setGlobalRefreshing(true)
    await Promise.all([loadList(mode), loadCounts()])
    setGlobalRefreshing(false)
    startGlobalCooldown()
  }

  const filteredSignals = signals
    .filter((s) => filter === 'all' || s.direction === filter)
    .slice()
    .sort((a, b) => {
      const aLive = a.open_trade ? 1 : 0
      const bLive = b.open_trade ? 1 : 0
      if (aLive !== bLive) return bLive - aLive
      const aActive = a.signal_available ? 1 : 0
      const bActive = b.signal_available ? 1 : 0
      return bActive - aActive
    })

  const readySignals = filteredSignals.filter((s) => s.signal_available)

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
          {counts.strict !== null && (
            <span dir="ltr"> ({counts.strict} فعال)</span>
          )}
        </label>
        <label className={`mode-option ${mode === 'relaxed' ? 'mode-option-active' : ''}`}>
          <input
            type="radio"
            name="signal-mode"
            checked={mode === 'relaxed'}
            onChange={() => setMode('relaxed')}
          />
          ساده‌گیر (سیگنال بیشتر، دقت پایین‌تر)
          {counts.relaxed !== null && (
            <span dir="ltr"> ({counts.relaxed} فعال)</span>
          )}
        </label>
      </div>

      <div className="watchlist-head">
        <div className="watchlist-head-top">
          <h2 className="watchlist-title">واچ‌لیست رصد زنده</h2>
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
          همه‌ی {filteredSignals.length} ارز زیر نظر — بر اساس امتیاز مرتب‌شده
          {isPartial && ' — لیست در حال تکمیل شدنه'}
        </span>
      </div>

      {status === 'loading' && <div className="watchlist-status">در حال دریافت لیست…</div>}
      {status === 'error' && <div className="watchlist-status">دریافت لیست با خطا مواجه شد.</div>}
      {status === 'ready' && filteredSignals.length === 0 && (
        <div className="watchlist-status">موردی با این فیلتر پیدا نشد.</div>
      )}

      {status === 'ready' && filteredSignals.length > 0 && (
        <div className="ticker-list">
          {filteredSignals.map((s) => (
            <WatchTickerRow key={s.symbol} signal={s} />
          ))}
        </div>
      )}

      <div className="ready-signals-head">
        <h2 className="watchlist-title">سیگنال‌های آماده‌ی گرفتن ({readySignals.length})</h2>
        <span className="watchlist-sub">فقط سیگنال‌هایی که هر ۵ تایم‌فریم (۴H تا ۵M) تاییدشون کرده</span>
      </div>

      {status === 'ready' && readySignals.length === 0 && (
        <div className="watchlist-status">فعلاً هیچ سیگنال آماده‌ای نیست — منتظر بمون تا واچ‌لیست تریگر جدید پیدا کنه.</div>
      )}

      {status === 'ready' && readySignals.length > 0 && (
        <div className="watchlist-list">
          {readySignals.map((s, index) => (
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
