import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType } from 'lightweight-charts'

// نگاشت چند تیکر پرکاربرد به شناسه‌ی کوین‌گکو (برای بقیه، از سرچ استفاده می‌کنیم)
const KNOWN_IDS = {
  BTC: 'bitcoin',
  ETH: 'ethereum',
  SOL: 'solana',
  XLM: 'stellar',
  BNB: 'binancecoin',
  XRP: 'ripple',
  DOGE: 'dogecoin',
  ADA: 'cardano',
  AVAX: 'avalanche-2',
  LINK: 'chainlink',
  DOT: 'polkadot',
  MATIC: 'matic-network',
  TON: 'the-open-network',
  TRX: 'tron',
  LTC: 'litecoin',
}

const REFRESH_INTERVAL_MS = 90 * 1000 // هر ۹۰ ثانیه داده‌ی چارت بروز می‌شه (نه چیزی تندتر، برای رعایت rate limit)

async function resolveCoinId(symbol) {
  const clean = symbol.toUpperCase().replace('USDT', '').trim()
  if (KNOWN_IDS[clean]) return KNOWN_IDS[clean]
  try {
    const res = await fetch(
      `https://api.coingecko.com/api/v3/search?query=${encodeURIComponent(clean)}`
    )
    const data = await res.json()
    return data?.coins?.[0]?.id ?? null
  } catch {
    return null
  }
}

async function fetchCandles(coinId, days) {
  const res = await fetch(
    `https://api.coingecko.com/api/v3/coins/${coinId}/ohlc?vs_currency=usd&days=${days}`
  )
  if (!res.ok) throw new Error('دریافت داده قیمت ناموفق بود')
  const raw = await res.json()
  return raw.map(([time, open, high, low, close]) => ({
    time: Math.floor(time / 1000),
    open,
    high,
    low,
    close,
  }))
}

// دقت اعشار مناسب رو بر اساس بزرگی قیمت تعیین می‌کنه (مثلاً برای DOGE با قیمت
// ۰.۰۷ باید ۶ رقم اعشار نشون بدیم، نه فقط ۲ تا که همه چیز "0.07" دیده بشه)
function pricePrecision(referencePrice) {
  const p = Math.abs(referencePrice || 0)
  if (p >= 100) return 2
  if (p >= 1) return 4
  if (p >= 0.01) return 6
  return 8
}

// برچسب تایم‌فریم بر اساس بازه‌ی روزی که از کوین‌گکو خواستیم (طبق گرانولاریت
// مستند API: ۱-۲ روز → ۳۰ دقیقه، ۳-۹۰ روز → ۴ ساعت، بیشتر از ۹۰ → روزانه)
function timeframeLabel(days) {
  if (days <= 2) return 'کندل ۳۰ دقیقه‌ای'
  if (days <= 90) return 'کندل ۴ ساعته'
  return 'کندل روزانه'
}

export default function SignalChart({ parsedSignal, days = 7 }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const [status, setStatus] = useState('loading') // 'loading' | 'ready' | 'error'
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    if (!parsedSignal?.symbol) {
      setStatus('error')
      setErrorMsg('نماد ارز از سیگنال قابل تشخیص نبود.')
      return
    }

    let disposed = false
    let refreshTimer = null

    async function loadAndRender(coinId, isFirstLoad) {
      let candles
      try {
        candles = await fetchCandles(coinId, days)
      } catch {
        if (!disposed && isFirstLoad) {
          setStatus('error')
          setErrorMsg('دریافت داده‌ی قیمت با خطا مواجه شد.')
        }
        return
      }

      if (disposed || candles.length === 0) return

      if (seriesRef.current) {
        // فقط داده‌ی کندل‌ها رو بروز می‌کنیم، بدون بازسازی کل چارت (جلوگیری از پرش/فلیکر)
        seriesRef.current.setData(candles)
        return
      }

      if (!containerRef.current) return
      containerRef.current.innerHTML = ''

      const referencePrice =
        parsedSignal.entries?.[0] ?? candles[candles.length - 1].close
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
        priceFormat: {
          type: 'price',
          precision,
          minMove: 1 / 10 ** precision,
        },
      })
      series.setData(candles)
      chartRef.current = chart
      seriesRef.current = series

      const isLong = (parsedSignal.direction || '').toLowerCase() === 'long'
      const lineColor = isLong ? '#2dd4a7' : '#ff5c72'

      ;(parsedSignal.entries || []).forEach((price, i) => {
        series.createPriceLine({
          price,
          color: lineColor,
          lineWidth: 1,
          lineStyle: 0,
          title: `ورود ${i + 1}`,
        })
      })
      ;(parsedSignal.targets || []).forEach((price, i) => {
        series.createPriceLine({
          price,
          color: '#2dd4a7',
          lineWidth: 1,
          lineStyle: 2,
          title: `هدف ${i + 1}`,
        })
      })
      if (parsedSignal.stop_loss) {
        series.createPriceLine({
          price: parsedSignal.stop_loss,
          color: '#ff5c72',
          lineWidth: 1,
          lineStyle: 2,
          title: 'حد ضرر',
        })
      }

      chart.timeScale().fitContent()
      if (!disposed) setStatus('ready')
    }

    async function init() {
      setStatus('loading')
      const coinId = await resolveCoinId(parsedSignal.symbol)
      if (!coinId) {
        if (!disposed) {
          setStatus('error')
          setErrorMsg(`ارز «${parsedSignal.symbol}» در کوین‌گکو پیدا نشد.`)
        }
        return
      }

      await loadAndRender(coinId, true)
      refreshTimer = setInterval(() => loadAndRender(coinId, false), REFRESH_INTERVAL_MS)
    }

    init()

    return () => {
      disposed = true
      clearInterval(refreshTimer)
      if (chartRef.current) chartRef.current.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [parsedSignal, days])

  return (
    <div className="chart-panel">
      <div className="chart-panel-head">
        <span>
          نمودار {parsedSignal?.symbol || '—'} ·{' '}
          {parsedSignal?.direction === 'short' ? 'شورت' : 'لانگ'} ·{' '}
          {parsedSignal?.leverage ? `اهرم ${parsedSignal.leverage}x` : 'اهرم نامشخص'} ·{' '}
          {timeframeLabel(days)}
        </span>
      </div>
      {status === 'loading' && (
        <div className="chart-status">در حال دریافت داده‌ی قیمت…</div>
      )}
      {status === 'error' && <div className="chart-status">{errorMsg}</div>}
      <div ref={containerRef} className="chart-container" />
      <p className="chart-disclaimer">
        این نمودار از داده‌ی عمومی CoinGecko ساخته شده (هر ۹۰ ثانیه بروز می‌شه)
        و صرفاً برای نمایش تقریبی نقاط سیگنال است؛ برای معامله‌ی واقعی از نمودار
        صرافی خودت استفاده کن.
      </p>
    </div>
  )
}
