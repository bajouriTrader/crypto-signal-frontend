import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType } from 'lightweight-charts'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'
const REFRESH_INTERVAL_MS = 60 * 1000 // هر ۶۰ ثانیه داده‌ی چارت بروز می‌شه
const LIVE_PRICE_INTERVAL_MS = 15 * 1000 // هر ۱۵ ثانیه قیمت لحظه‌ای بروز می‌شه

async function fetchCandles(symbol, interval) {
  const res = await fetch(
    `${API_BASE_URL}/market/klines?symbol=${encodeURIComponent(symbol)}&interval=${interval}&limit=150`
  )
  if (!res.ok) throw new Error('دریافت داده قیمت ناموفق بود')
  const data = await res.json()
  return data.candles || []
}

// دقت اعشار مناسب رو بر اساس بزرگی قیمت تعیین می‌کنه
function pricePrecision(referencePrice) {
  const p = Math.abs(referencePrice || 0)
  if (p >= 100) return 2
  if (p >= 1) return 4
  if (p >= 0.01) return 6
  return 8
}

const TIMEFRAME_LABELS = {
  '5m': 'کندل ۵ دقیقه‌ای',
  '15m': 'کندل ۱۵ دقیقه‌ای',
  '30m': 'کندل ۳۰ دقیقه‌ای',
  '1h': 'کندل ۱ ساعته',
  '4h': 'کندل ۴ ساعته',
  '1d': 'کندل روزانه',
}

export default function SignalChart({ parsedSignal, interval = '15m' }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const livePriceLineRef = useRef(null)
  const [status, setStatus] = useState('loading') // 'loading' | 'ready' | 'error'
  const [errorMsg, setErrorMsg] = useState('')
  const [livePrice, setLivePrice] = useState(null)

  useEffect(() => {
    if (!parsedSignal?.symbol) {
      setStatus('error')
      setErrorMsg('نماد ارز از سیگنال قابل تشخیص نبود.')
      return
    }

    let disposed = false
    let refreshTimer = null
    let liveTimer = null

    async function updateLivePrice(symbol) {
      try {
        const res = await fetch(`${API_BASE_URL}/live-price/${symbol}`)
        if (!res.ok) return
        const data = await res.json()
        if (disposed || typeof data.price !== 'number') return

        setLivePrice(data.price)

        if (seriesRef.current) {
          if (livePriceLineRef.current) {
            livePriceLineRef.current.applyOptions({ price: data.price })
          } else {
            livePriceLineRef.current = seriesRef.current.createPriceLine({
              price: data.price,
              color: '#e8a94a',
              lineWidth: 1,
              lineStyle: 3,
              title: 'قیمت لحظه‌ای',
            })
          }
        }
      } catch {
        // خطای موقت شبکه رو نادیده می‌گیریم
      }
    }

    async function loadAndRender(isFirstLoad) {
      let candles
      try {
        candles = await fetchCandles(parsedSignal.symbol, interval)
      } catch {
        if (!disposed && isFirstLoad) {
          setStatus('error')
          setErrorMsg('دریافت داده‌ی قیمت با خطا مواجه شد.')
        }
        return
      }

      if (disposed || candles.length === 0) {
        if (!disposed && isFirstLoad) {
          setStatus('error')
          setErrorMsg('داده‌ی قیمتی برای این ارز پیدا نشد.')
        }
        return
      }

      if (seriesRef.current) {
        seriesRef.current.setData(candles)
        return
      }

      if (!containerRef.current) return
      containerRef.current.innerHTML = ''

      const referencePrice = parsedSignal.entries?.[0] ?? candles[candles.length - 1].close
      const precision = pricePrecision(referencePrice)

      const chart = createChart(containerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: '#7b8492',
        },
        grid: {
          vertLines: { color: '#232935' },
          horzLines: { color: '#232935' },
        },
        rightPriceScale: { borderColor: '#232935' },
        timeScale: { borderColor: '#232935' },
        height: 340,
      })

      const series = chart.addCandlestickSeries({
        upColor: '#2dd4a7',
        downColor: '#ff5c72',
        borderVisible: false,
        wickUpColor: '#2dd4a7',
        wickDownColor: '#ff5c72',
        priceFormat: { type: 'price', precision, minMove: 1 / 10 ** precision },
      })
      series.setData(candles)
      chartRef.current = chart
      seriesRef.current = series

      const isLong = (parsedSignal.direction || '').toLowerCase() === 'long'
      const lineColor = isLong ? '#2dd4a7' : '#ff5c72'

      ;(parsedSignal.entries || []).forEach((price, i) => {
        series.createPriceLine({ price, color: lineColor, lineWidth: 1, lineStyle: 0, title: `ورود ${i + 1}` })
      })
      ;(parsedSignal.targets || []).forEach((price, i) => {
        series.createPriceLine({ price, color: '#2dd4a7', lineWidth: 1, lineStyle: 2, title: `هدف ${i + 1}` })
      })
      if (parsedSignal.stop_loss) {
        series.createPriceLine({ price: parsedSignal.stop_loss, color: '#ff5c72', lineWidth: 1, lineStyle: 2, title: 'حد ضرر' })
      }

      chart.timeScale().fitContent()
      if (!disposed) setStatus('ready')
    }

    async function init() {
      setStatus('loading')
      await loadAndRender(true)
      refreshTimer = setInterval(() => loadAndRender(false), REFRESH_INTERVAL_MS)
      await updateLivePrice(parsedSignal.symbol)
      liveTimer = setInterval(() => updateLivePrice(parsedSignal.symbol), LIVE_PRICE_INTERVAL_MS)
    }

    init()

    return () => {
      disposed = true
      clearInterval(refreshTimer)
      clearInterval(liveTimer)
      if (chartRef.current) chartRef.current.remove()
      chartRef.current = null
      seriesRef.current = null
      livePriceLineRef.current = null
    }
  }, [parsedSignal, interval])

  return (
    <div className="chart-panel">
      <div className="chart-panel-head">
        <span>
          نمودار {parsedSignal?.symbol || '—'} ·{' '}
          {parsedSignal?.direction === 'short' ? 'شورت' : 'لانگ'} ·{' '}
          {parsedSignal?.leverage ? `اهرم ${parsedSignal.leverage}x` : 'اهرم نامشخص'} ·{' '}
          {TIMEFRAME_LABELS[interval] || interval}
        </span>
        {livePrice !== null && (
          <span dir="ltr" className="chart-live-price">
            🟡 {livePrice}
          </span>
        )}
      </div>
      {status === 'loading' && <div className="chart-status">در حال دریافت داده‌ی قیمت…</div>}
      {status === 'error' && <div className="chart-status">{errorMsg}</div>}
      <div ref={containerRef} className="chart-container" />
      <p className="chart-disclaimer">
        این نمودار از داده‌ی عمومی صرافی توبیت ساخته شده و برای نمایش دقیق نقاط
        سیگنال با تایم‌فریم واقعی معاملاتیه؛ برای اجرای واقعی معامله، از اپ/سایت
        صرافی خودت استفاده کن.
      </p>
    </div>
  )
}
