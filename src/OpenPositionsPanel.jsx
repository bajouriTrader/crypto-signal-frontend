import { authFetch } from './auth'
import { useEffect, useRef, useState } from 'react'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'
const POLL_INTERVAL_MS = 20000

function computeUnrealizedPnl(trade) {
  const price = trade.current_price
  if (price == null || !trade.quantity) return null
  return trade.direction === 'long'
    ? trade.quantity * (price - trade.entry)
    : trade.quantity * (trade.entry - price)
}

function PositionRow({ trade, onClosed }) {
  const [closing, setClosing] = useState(false)
  const pnl = computeUnrealizedPnl(trade)

  const handleClose = async () => {
    setClosing(true)
    try {
      const res = await authFetch(`${API_BASE_URL}/demo-trade/close/${trade.trade_id}`, {
        method: 'POST',
      })
      if (res.ok) onClosed(trade.trade_id)
    } catch {
      // خطای موقت — کاربر می‌تونه دوباره امتحان کنه
    } finally {
      setClosing(false)
    }
  }

  return (
    <div className="oppos-row">
      <div className="oppos-symbol-cell">
        <span className={`oppos-dir-badge ${trade.direction === 'long' ? 'oppos-dir-long' : 'oppos-dir-short'}`}>
          {trade.direction === 'long' ? 'لانگ' : 'شورت'}
        </span>
        <span className="oppos-symbol">{trade.symbol}</span>
        {trade.stale_warning && (
          <span className="oppos-stale-badge" title="بیش از ۴ ساعته باز مونده">⚠️</span>
        )}
      </div>

      <div className="oppos-price-cell" dir="ltr">
        <span className="oppos-entry-price">{trade.entry}</span>
        <span className="oppos-current-price">{trade.current_price ?? '…'}</span>
      </div>

      <div
        className={`oppos-pnl-cell ${pnl == null ? '' : pnl >= 0 ? 'oppos-pnl-pos' : 'oppos-pnl-neg'}`}
        dir="ltr"
      >
        {pnl == null ? '—' : `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}$`}
      </div>

      <div className="oppos-tpsl-cell" dir="ltr">
        <span className="oppos-tp">TP {trade.target}</span>
        <span className="oppos-sl">SL {trade.stop_loss}</span>
      </div>

      <button className="oppos-close-btn" onClick={handleClose} disabled={closing}>
        {closing ? '…' : 'بستن'}
      </button>
    </div>
  )
}

export default function OpenPositionsPanel() {
  const [trades, setTrades] = useState([])
  const [status, setStatus] = useState('loading') // 'loading' | 'ready' | 'error'
  const pollRef = useRef(null)

  const load = async () => {
    try {
      const res = await authFetch(`${API_BASE_URL}/demo-trade/open-all`)
      if (!res.ok) throw new Error()
      const data = await res.json()
      setTrades(data.trades || [])
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }

  useEffect(() => {
    load()
    pollRef.current = setInterval(load, POLL_INTERVAL_MS)
    return () => clearInterval(pollRef.current)
  }, [])

  const handleClosed = (tradeId) => {
    setTrades((prev) => prev.filter((t) => t.trade_id !== tradeId))
  }

  if (status === 'loading' || (status === 'ready' && trades.length === 0)) {
    return null // چیزی برای نشون دادن نیست، جای خالی اشغال نمی‌کنه
  }

  return (
    <section className="oppos-panel">
      <div className="oppos-head">
        <div className="oppos-head-title">
          <span>پوزیشن‌های باز من</span>
          <span className="oppos-count-badge" dir="ltr">{trades.length} باز</span>
        </div>
        <div className="oppos-live-indicator">
          <span className="oppos-live-dot" />
          رصد زنده
        </div>
      </div>

      {status === 'error' && (
        <div className="oppos-error">دریافت پوزیشن‌های باز با خطا مواجه شد.</div>
      )}

      <div className="oppos-list">
        {trades.map((t) => (
          <PositionRow key={t.trade_id} trade={t} onClosed={handleClosed} />
        ))}
      </div>
    </section>
  )
}
