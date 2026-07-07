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

async function fetchCandles(coinId) {
  const res = await fetch(
    `https://api.coingecko.com/api/v3/coins/${coinId}/ohlc?vs_currency=usd&days=7`
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

export default function SignalChart({ parsedSignal }) {
  const containerRef = useRef(null)
  const [status, setStatus] = useState('loading') // 'loading' | 'ready' | 'error'
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    if (!parsedSignal?.symbol) {
      setStatus('error')
      setErrorMsg('نماد ارز از سیگنال قابل تشخیص نبود.')
      return
    }

    let chart
    let disposed = false

    async function build() {
      setStatus('loading')
      const coinId = await resolveCoinId(parsedSignal.symbol)
      if (!coinId) {
        if (!disposed) {
          setStatus('error')
          setErrorMsg(`ارز «${parsedSignal.symbol}» در کوین‌گکو پیدا نشد.`)
        }
        return
      }

      let candles
      try {
        candles = await fetchCandles(coinId)
      } catch (e) {
        if (!disposed) {
          setStatus('error')
          setErrorMsg('دریافت داده‌ی قیمت با خطا مواجه شد.')
        }
        return
      }

      if (disposed || !containerRef.current || candles.length === 0) {
        if (!disposed) {
          setStatus('error')
          setErrorMsg('داده‌ی قیمتی کافی برای رسم نمودار موجود نبود.')
        }
        return
      }

      containerRef.current.innerHTML = ''
      chart = createChart(containerRef.current, {
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
      })
      series.setData(candles)

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

    build()

    return () => {
      disposed = true
      if (chart) chart.remove()
    }
  }, [parsedSignal])

  return (
    <div className="chart-panel">
      <div className="chart-panel-head">
        <span>
          نمودار {parsedSignal?.symbol || '—'} ·{' '}
          {parsedSignal?.direction === 'short' ? 'شورت' : 'لانگ'} ·{' '}
          {parsedSignal?.leverage ? `اهرم ${parsedSignal.leverage}x` : 'اهرم نامشخص'}
        </span>
      </div>
      {status === 'loading' && (
        <div className="chart-status">در حال دریافت داده‌ی قیمت…</div>
      )}
      {status === 'error' && <div className="chart-status">{errorMsg}</div>}
      <div ref={containerRef} className="chart-container" />
      <p className="chart-disclaimer">
        این نمودار از داده‌ی عمومی CoinGecko ساخته شده و صرفاً برای نمایش
        تقریبی نقاط سیگنال است؛ برای معامله‌ی واقعی از نمودار صرافی خودت
        استفاده کن.
      </p>
    </div>
  )
}
