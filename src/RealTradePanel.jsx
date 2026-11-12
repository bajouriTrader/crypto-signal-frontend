import { authFetch } from './auth'
import { useEffect, useState, useRef } from 'react'
import AgentPipeline, { exitLabel } from './AgentPipeline'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'
const STATUS_VIEWER = 'https://asalehb-crypto-signal-backend.hf.space/status-viewer'

function Metric({ label, value, color }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 4,
        padding: '10px 6px',
        borderRadius: 10,
        background: '#121c28',
        border: '1px solid #243444',
        minHeight: 64,
        textAlign: 'center',
      }}
    >
      <span style={{ fontSize: 11, color: '#8899aa', lineHeight: 1.25 }}>{label}</span>
      <span
        dir="ltr"
        style={{
          fontSize: 16,
          fontWeight: 700,
          color: color || '#e8f0f8',
          lineHeight: 1.2,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </span>
    </div>
  )
}

/** نوار مسیر قیمت: همیشه LTR — چپ=SL · راست=TP · نشانگر=قیمت فعلی */

function formatTehran(isoOrTs) {
  try {
    const d = typeof isoOrTs === 'number' ? new Date(isoOrTs * 1000) : new Date(isoOrTs)
    if (Number.isNaN(d.getTime())) return '—'
    return d.toLocaleString('fa-IR', {
      timeZone: 'Asia/Tehran',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch (e) {
    return '—'
  }
}

// V.2.42.1 — پول همیشه ۲ رقم اعشار با ارقام لاتین؛ مقداری که به صفر گرد می‌شود بدون علامت
function money(v, signed = false) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const r = Math.round(n * 100) / 100
  if (r === 0) return '0.00 $'
  return `${r > 0 ? (signed ? '+' : '') : '−'}${Math.abs(r).toFixed(2)} $`
}

function pnlTone(v) {
  const r = Math.round(Number(v || 0) * 100) / 100
  return r > 0 ? '#2DD4A7' : r < 0 ? '#FF5C72' : '#e8f0f8'
}

function usePersistedOpen(key) {
  const [v, setV] = useState(() => {
    try { return localStorage.getItem(key) === '1' } catch (_) { return false }
  })
  const set = (x) => {
    setV(!!x)
    try { localStorage.setItem(key, x ? '1' : '0') } catch (_) {}
  }
  return [v, set]
}

function hhmmTehran(isoOrTs) {
  try {
    const d = typeof isoOrTs === 'number' ? new Date(isoOrTs * 1000) : new Date(isoOrTs)
    if (Number.isNaN(d.getTime())) return ''
    return d.toLocaleTimeString('fa-IR', { timeZone: 'Asia/Tehran', hour: '2-digit', minute: '2-digit' })
  } catch (_) { return '' }
}

// دلیل توقف ورود جدید (یا null) — به ترتیب اولویت
function entryStop(s) {
  const gh = s.gh_entry || {}
  const lim = Number(s.daily_loss_limit)
  const loss = Math.max(0, -Number(s.daily_pnl?.pnl || 0))
  if ((Number.isFinite(lim) && lim > 0 && loss >= lim) || gh.why === 'سقف ضرر روزانه') {
    return { tone: 'bad', text: 'ورود جدید تا فردا متوقف است: سقف ضرر روزانه پر شد', short: 'سقف ضرر روزانه پر شد' }
  }
  if (s.enable_new_entries === false) {
    return { tone: 'warn', text: 'ورود جدید از تنظیمات خاموش است', short: 'ورود جدید خاموش است' }
  }
  const nb = s.news_blackout || {}
  if (nb.active) {
    const title = nb.event_title || nb.event?.title_fa || nb.event?.title || 'مهم'
    const until = hhmmTehran(nb.window_end_iso || nb.window_end_ts)
    const t = `خبر ${title}${until ? ` تا ${until}` : ''}`
    return { tone: 'warn', text: `ورود جدید متوقف است: ${t}`, short: `ورود جدید متوقف: ${t}` }
  }
  if (gh.blocked) {
    const why = gh.why === 'قفل سراسری SL' ? 'استراحت بعد از حد ضرر' : (gh.why || 'موقت')
    return { tone: 'warn', text: `ورود جدید موقتاً متوقف است: ${why}`, short: `ورود جدید متوقف: ${why}` }
  }
  if (Array.isArray(gh.live) && gh.live.length === 0) {
    return { tone: 'warn', text: 'هیچ استراتژی فعالی نیست؛ معامله‌ای باز نمی‌شود', short: 'استراتژی فعالی نیست' }
  }
  return null
}

// V.2.42.1 — یک جملهٔ ساده: «پولم خوب است؟ ربات الان چه می‌کند؟» (اولین شرطِ برقرار)
export function statusSentence(s, err) {
  if (!s) return err ? { tone: 'bad', text: 'اتصال به سرور برقرار نشد' } : { tone: 'off', text: 'در حال دریافت وضعیت…' }
  if (err) return { tone: 'warn', text: 'اتصال قطع است؛ اطلاعات قدیمی است' }
  const tracked = Array.isArray(s.tracked) ? s.tracked : []
  const noSl = tracked.find((t) => t?.sl_on_exchange === false)
  if (noSl) return { tone: 'bad', text: 'هشدار: این پوزیشن روی صرافی حد ضرر ندارد:', sym: String(noSl.symbol || '') }
  if (Number(s.open_positions) > tracked.length) {
    return { tone: 'bad', text: 'پوزیشنی روی صرافی هست که ربات مدیریت نمی‌کند' }
  }
  const lag = s.manager_heartbeat?.last_cycle_ago_sec
  const iv = Number(s.manager?.interval_seconds) || 45
  if (lag != null && Number(lag) > Math.max(180, 4 * iv)) {
    return { tone: tracked.length ? 'bad' : 'warn', text: `ربات ${Math.round(Number(lag) / 60)} دقیقه است پاسخ نداده` }
  }
  const stop = entryStop(s)
  if (tracked.length > 0) {
    const total = tracked.reduce((a, t) => a + Number(t?.unrealized_usdt || 0), 0)
    const gh = s.gh_entry || {}
    const suffix = !s.real_trading_enabled ? 'معامله واقعی خاموش است'
      : stop ? stop.short
        : (Number(gh.open) >= Number(gh.max) && Number(gh.max) > 0) ? 'ظرفیت پر است' : null
    const one = tracked.length === 1 ? tracked[0] : null
    return {
      tone: Math.round(total * 100) / 100 >= 0 ? 'ok' : 'bad',
      text: one ? '۱ پوزیشن باز:' : `${tracked.length} پوزیشن باز`,
      sym: one ? String(one.symbol || '').replace('-SWAP-USDT', '') : null,
      side: one ? (String(one.direction).toLowerCase() === 'long' ? 'لانگ' : 'شورت') : null,
      pnl: total,
      suffix,
    }
  }
  if (!s.real_trading_enabled) return { tone: 'off', text: 'معامله واقعی خاموش است' }
  if (stop) return { tone: stop.tone, text: stop.text }
  return { tone: 'ok', text: 'ربات آماده است و منتظر سیگنال می‌ماند' }
}

function formatElapsed(sec) {
  const n = Number(sec)
  if (!Number.isFinite(n) || n < 0) return '—'
  const s = Math.floor(n)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  const pad = (x) => String(x).padStart(2, '0')
  if (h > 0) return `${h}:${pad(m)}:${pad(r)}`
  return `${pad(m)}:${pad(r)}`
}

function PathBar({ direction, entry, sl, tp, price }) {
  const e = Number(entry)
  const s = Number(sl)
  const t = Number(tp)
  const p = Number(price)
  if (![e, s, t, p].every((x) => Number.isFinite(x) && x > 0)) {
    return null
  }

  // لانگ: SL < entry < TP — شورت برعکس؛ محور همیشه چپ=کم · راست=زیاد از دید قیمت
  const isLong = (direction || '').toLowerCase() === 'long'
  const low = Math.min(s, t, e)
  const high = Math.max(s, t, e)
  const span = high - low
  if (span <= 1e-12) return null

  const clamp01 = (x) => Math.max(0, Math.min(1, x))
  const entryPos = clamp01((e - low) / span)
  const pricePos = clamp01((p - low) / span)
  const slPos = clamp01((s - low) / span)
  const tpPos = clamp01((t - low) / span)

  // پیشرفت نسبت به ورود: مثبت = به سمت TP
  let toTp = 0
  if (isLong) {
    toTp = t !== e ? (p - e) / (t - e) : 0
  } else {
    toTp = e !== t ? (e - p) / (e - t) : 0
  }
  const toTpPct = Math.round(toTp * 100)

  let toSl = 0
  if (isLong) {
    toSl = e !== s ? (e - p) / (e - s) : 0
  } else {
    toSl = s !== e ? (p - e) / (s - e) : 0
  }
  const towardSl = toSl > 0.02
  const towardTp = toTp > 0.02
  const statusLabel = towardSl
    ? `${Math.min(100, Math.round(toSl * 100))}% مسیر تا حدضرر`
    : towardTp
      ? `${Math.min(100, Math.max(0, toTpPct))}% مسیر تا هدف`
      : 'نزدیک ورود'

  const statusColor = towardSl ? '#FF5C72' : towardTp ? '#2DD4A7' : '#8899aa'

  // سمت چپ نوار همیشه عدد کوچکتر (قیمت پایین‌تر)
  const leftLabel = isLong ? `حدضرر ${s}` : `هدف ${t}`
  const rightLabel = isLong ? `هدف ${t}` : `حدضرر ${s}`
  const leftColor = isLong ? '#FF5C72' : '#2DD4A7'
  const rightColor = isLong ? '#2DD4A7' : '#FF5C72'

  return (
    <div style={{ marginTop: 10, marginBottom: 4 }} dir="ltr">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: 10,
          marginBottom: 4,
          gap: 6,
        }}
      >
        <span style={{ color: leftColor, fontWeight: 600 }}>{leftLabel}</span>
        <span style={{ color: statusColor, fontWeight: 700 }}>{statusLabel}</span>
        <span style={{ color: rightColor, fontWeight: 600 }}>{rightLabel}</span>
      </div>
      <div
        style={{
          position: 'relative',
          height: 12,
          borderRadius: 6,
          overflow: 'hidden',
          background: '#1a2836',
          border: '1px solid #243444',
        }}
      >
        {/* پس‌زمینه: از SL تا entry قرمز، از entry تا TP سبز */}
        <div
          style={{
            position: 'absolute',
            left: `${Math.min(slPos, entryPos) * 100}%`,
            width: `${Math.abs(entryPos - slPos) * 100}%`,
            top: 0,
            bottom: 0,
            background: 'linear-gradient(90deg, rgba(255,92,114,0.5), rgba(255,92,114,0.18))',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: `${Math.min(entryPos, tpPos) * 100}%`,
            width: `${Math.abs(tpPos - entryPos) * 100}%`,
            top: 0,
            bottom: 0,
            background: 'linear-gradient(90deg, rgba(45,212,167,0.18), rgba(45,212,167,0.5))',
          }}
        />
        {/* خط ورود */}
        <div
          title="ورود"
          style={{
            position: 'absolute',
            left: `${entryPos * 100}%`,
            top: 0,
            bottom: 0,
            width: 2,
            marginLeft: -1,
            background: 'rgba(255,255,255,0.7)',
          }}
        />
        {/* نشانگر قیمت فعلی */}
        <div
          title={`قیمت ${p}`}
          style={{
            position: 'absolute',
            left: `${pricePos * 100}%`,
            top: -3,
            bottom: -3,
            width: 5,
            marginLeft: -2.5,
            borderRadius: 2,
            background: towardSl ? '#FF5C72' : towardTp ? '#2DD4A7' : '#ccd6e0',
            boxShadow: towardSl
              ? '0 0 8px rgba(255,92,114,0.85)'
              : towardTp
                ? '0 0 8px rgba(45,212,167,0.85)'
                : '0 0 4px rgba(200,210,220,0.5)',
          }}
        />
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 10,
          color: '#667788',
          marginTop: 4,
        }}
      >
        <span>قیمت: <b dir="ltr" style={{ color: '#c8d6e4' }}>{p}</b></span>
        <span>ورود: <b dir="ltr" style={{ color: '#c8d6e4' }}>{e}</b></span>
      </div>
    </div>
  )
}

function PosCard({ t, onClose, closing }) {
  const sym = t.symbol
  const dir = t.direction
  const upnl = Number(t.unrealized_usdt ?? 0)
  const upct = Number(t.unrealized_pct ?? 0)
  const pnlColor = upnl >= 0 ? '#2DD4A7' : '#FF5C72'

  const cells = [
    { label: 'ورود', value: t.entry, color: '#4DA3FF' },
    { label: 'قیمت فعلی', value: t.current_price, color: '#FFFFFF' },
    { label: 'هدف (TP)', value: t.target, color: '#2DD4A7' },
    { label: 'حد ضرر (SL)', value: t.stop_loss, color: '#FF5C72' },
    { label: 'مارجین', value: t.margin != null ? Number(t.margin).toFixed(2) : '—', color: '#d8e6f0' },
  ]

  return (
    <div
      style={{
        padding: 12,
        marginBottom: 10,
        borderRadius: 12,
        background: '#121c28',
        border: '1px solid #243444',
      }}
    >
      {/* هدر: نماد + PnL */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 8,
          marginBottom: 8,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <strong style={{ fontSize: 15, letterSpacing: 0.3 }}>{sym}</strong>
          <span
            style={{
              fontSize: 11,
              padding: '2px 8px',
              borderRadius: 6,
              background: dir === 'long' ? 'rgba(45,212,167,0.15)' : 'rgba(255,92,114,0.15)',
              color: dir === 'long' ? '#2DD4A7' : '#FF5C72',
            }}
          >
            {dir === 'long' ? 'لانگ' : 'شورت'}
          </span>
          {t.profit_locked && (
            <span style={{ fontSize: 10, color: '#E8A94A' }}>قفل‌شده</span>
          )}
          <span
            style={{
              fontSize: 11,
              padding: '2px 8px',
              borderRadius: 6,
              background: 'rgba(100,140,180,0.15)',
              color: '#9ab0c4',
            }}
            title="مدت باز بودن پوزیشن"
          >
            ⏱ {formatElapsed(t.elapsed_sec)}
            {t.max_hold_h ? ` / ${t.max_hold_h}h` : ''}
          </span>
          {t.strategy_id && (
            <span style={{ fontSize: 10, color: '#7a8a9a' }} title="استراتژی (V.2.35.0)">{t.strategy_id}</span>
          )}
        </div>
        <div dir="ltr" style={{ textAlign: 'left', minWidth: 88 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: pnlColor, fontVariantNumeric: 'tabular-nums' }}>
            {upnl >= 0 ? '+' : ''}{upnl.toFixed(4)} $
          </div>
          <div style={{ fontSize: 11, color: pnlColor, fontVariantNumeric: 'tabular-nums' }}>
            {upct >= 0 ? '+' : ''}{upct.toFixed(3)}%
          </div>
        </div>
      </div>

      {/* ورود · قیمت · TP · SL · مارجین — همیشه یک سطر */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'row',
          flexWrap: 'nowrap',
          gap: 6,
          width: '100%',
        }}
        className="pos-levels"
      >
        {cells.map((c) => (
          <div
            key={c.label}
            style={{
              flex: '1 1 0',
              minWidth: 0,
              textAlign: 'center',
              padding: '6px 2px',
              borderRadius: 8,
              background: '#0d1520',
              border: '1px solid #1e3344',
            }}
          >
            <div style={{ fontSize: 9, color: '#667788', marginBottom: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.label}</div>
            <div dir="ltr" style={{ fontSize: 12, fontWeight: 600, color: c.color, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {c.value ?? '—'}
            </div>
          </div>
        ))}
      </div>

      <PathBar
        direction={dir}
        entry={t.entry}
        sl={t.stop_loss}
        tp={t.target}
        price={t.current_price}
      />

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 8,
          gap: 8,
          flexWrap: 'wrap',
        }}
      >
        {t.sl_on_exchange === false && (
          <span style={{ fontSize: 12, fontWeight: 700, color: '#FF5C72', width: '100%' }}>✗ حد ضرر روی صرافی نیست</span>
        )}
        <span style={{ fontSize: 11, color: '#667788' }} dir="ltr">
          SL روی صرافی:{t.sl_on_exchange ? '✓' : '✗'} · TP:{t.tp_on_exchange ? '✓' : '✗'}
          {t.leverage ? ` · ${t.leverage}x` : ''}
          {t.regime_sl_tightened ? ' · SL تنگ‌شده' : ''}
          {t.breakeven_set ? ' · BE' : ''}
        </span>
        <button
          type="button"
          disabled={closing}
          onClick={() => onClose(sym)}
          style={{
            background: '#2a1520',
            border: '1px solid #5a2a35',
            color: '#ff8a9a',
            borderRadius: 10,
            padding: '8px 18px',
            minHeight: 42,
            fontSize: 13,
            cursor: closing ? 'wait' : 'pointer',
          }}
        >
          {closing ? '…' : 'بستن'}
        </button>
      </div>
    </div>
  )
}

export default function RealTradePanel() {
  const [techOpen, setTechOpen] = usePersistedOpen('sd_tech_open')
  const [status, setStatus] = useState(null)
  const [openDespitePause, setOpenDespitePause] = useState([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const [flash, setFlash] = useState(null)
  const [closingSym, setClosingSym] = useState(null)
  const [closedVisible, setClosedVisible] = useState(10)
  const timerRef = useRef(null)
  const flashTimerRef = useRef(null)

  const load = async (silent = false) => {
    if (!silent) setLoading(true)
    setErr(null)
    try {
      const res = await authFetch(`${API_BASE_URL}/real-trade/status`)
      if (!res.ok) throw new Error('خطا در دریافت وضعیت')
      const data = await res.json()
      setStatus(data)
      setClosedVisible(10)
      if (!silent) {
        setFlash('ok')
        if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
        flashTimerRef.current = setTimeout(() => setFlash(null), 2000)
      }
    } catch (e) {
      setErr(e.message || 'خطا')
      setFlash(null)
    } finally {
      if (!silent) setLoading(false)
    }
  }

  const closePos = async (symbol) => {
    setClosingSym(symbol)
    try {
      const res = await authFetch(`${API_BASE_URL}/real-trade/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || data.message || 'بستن ناموفق')
      await load(true)
    } catch (e) {
      setErr(e.message || 'خطا در بستن')
    } finally {
      setClosingSym(null)
    }
  }

  useEffect(() => {   // V.2.42.1 — برگشت به تب ⇒ بلافاصله تازه‌سازی (دادهٔ کهنه نمایش داده نشود)
    const onVis = () => { if (!document.hidden) load(true) }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])

  useEffect(() => {
    load(true)
    // V.2.35.0 — هر ۱۵ ثانیه و فقط وقتی تب دیده می‌شود (status سنگین است)
    timerRef.current = setInterval(() => { if (!document.hidden) load(true) }, 15000)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    }
  }, [])

  const tracked = status?.tracked || []
  const mgr = status?.manager || {}
  const recent = status?.recent_closed || []
  const openPnl = tracked.reduce((s, t) => s + Number(t.unrealized_usdt || 0), 0)
  const dailyPnl = Number(status?.daily_pnl?.pnl || 0)
  const dailyDate = status?.daily_pnl?.date || ''

  const s = status || {}
  const sent = statusSentence(status, err)
  const eq = Number(s.equity_usdt)
  const hasEq = Number.isFinite(eq) && eq > 0
  const avail = Number(s.available_usdt)
  const lossLim = Number(s.daily_loss_limit)
  const nb = s.news_blackout || {}
  const nextNews = nb.next_window?.event_title || nb.next_event?.title_fa || nb.next_event?.title

  return (
    <div className="real-trade-wrap rt2" style={{ margin: '12px 0' }}>
      {/* V.2.42.1 — خلاصه: یک جملهٔ وضعیت + دارایی + امروز */}
      <section className={`rt2-summary rt2-tone-${sent.tone}`} aria-live="polite">
        <div className="rt2-sentence">
          <span className="rt2-dot" aria-hidden="true" />
          <span>
            {sent.text}
            {sent.sym && <> <bdi dir="ltr">{sent.sym}</bdi></>}
            {sent.side && <> {sent.side}</>}
            {sent.pnl != null && <>، <bdi dir="ltr" className="num">{money(sent.pnl, true)}</bdi></>}
            {sent.suffix && <span className="rt2-suffix">{sent.suffix}</span>}
          </span>
        </div>
        {status && (
          <>
            <div className="rt2-figures">
              <div>
                <div className="rt2-label">{hasEq ? 'دارایی' : 'موجودی آزاد'}</div>
                <bdi dir="ltr" className="rt2-big num">
                  {hasEq ? money(eq) : Number.isFinite(avail) ? money(avail) : '—'}
                </bdi>
              </div>
              <div>
                <div className="rt2-label">سود و زیان امروز</div>
                <bdi dir="ltr" className="rt2-big num" style={{ color: pnlTone(dailyPnl) }}>{money(dailyPnl, true)}</bdi>
              </div>
            </div>
            <dl className="rt2-facts">
              <div><dt>پوزیشن باز</dt><dd className="num">{s.open_positions ?? '—'} از {s.max_open_positions ?? '—'}</dd></div>
              <div><dt>سود و زیان باز</dt><dd><bdi dir="ltr" className="num" style={{ color: pnlTone(openPnl) }}>{money(openPnl, true)}</bdi></dd></div>
              <div><dt>موجودی آزاد</dt><dd><bdi dir="ltr" className="num">{Number.isFinite(avail) ? money(avail) : '—'}</bdi></dd></div>
              <div><dt>سقف ضرر روز</dt><dd><bdi dir="ltr" className="num">{Number.isFinite(lossLim) ? money(lossLim) : '—'}</bdi></dd></div>
            </dl>
            {!nb.active && nextNews && (
              <div className="rt2-news">
                خبر بعدی: <span style={{ color: '#c5d0e8' }}>{nextNews}</span>
                {nb.next_window?.window_start_iso && (
                  <> — توقف ورود از <bdi>{formatTehran(nb.next_window.window_start_iso)}</bdi> تا <bdi>{formatTehran(nb.next_window.window_end_iso)}</bdi></>
                )}
              </div>
            )}
          </>
        )}
        {loading && !status && <div style={{ color: '#8899aa' }}>در حال بارگذاری…</div>}
        {err && status && <div className="rt2-err">{err}</div>}
      </section>

      {status && (
        <>
          <h2 className="rt2-h">پوزیشن‌های باز</h2>
          {tracked.length > 0 ? (
            <div style={{ marginBottom: 14 }}>
              {tracked.map((t) => (
                <PosCard key={t.symbol} t={t} onClose={closePos} closing={closingSym === t.symbol} />
              ))}
            </div>
          ) : (
            <div className="rt2-empty">الان پوزیشن بازی نیست.</div>
          )}

          {recent.length > 0 && (
            <>
              <h2 className="rt2-h">معاملات اخیر</h2>
              <div
                className="rt2-list"
                onScroll={(e) => {
                  const el = e.currentTarget
                  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 8) {
                    setClosedVisible((n) => Math.min(recent.length, n + 10))
                  }
                }}
              >
                {recent.slice(0, closedVisible).map((r, i) => {
                  const pnl = Number(r.approx_pnl || 0)
                  const ts = Number(r.closed_at || 0)
                  let when = '—'
                  try {
                    if (ts > 0) {
                      const d = new Date((ts > 1e12 ? ts : ts * 1000))
                      when = d.toLocaleString('fa-IR', {
                        timeZone: 'Asia/Tehran',
                        year: 'numeric', month: '2-digit', day: '2-digit',
                        hour: '2-digit', minute: '2-digit',
                      })
                    }
                  } catch (_) {}
                  // V.2.10.101 — نسخهٔ معامله = نسخهٔ زمان باز شدن؛ بدون تطبیق = «—» (جعل نمی‌شود)
                  const ver = r.app_version || r.app_version_close || r.close_app_version || ''
                  const strat = r.strategy_id === 'range_scalp' ? 'رنج'
                    : r.strategy_id === 'weak_trend' ? 'weak'
                      : r.strategy_id === 'trend' ? 'روند' : (r.strategy_id || '')
                  const ex = exitLabel(r.exit_reason)
                  return (
                    <div className="rt2-row" key={String(r.symbol) + i + String(r.exit_price || '') + String(ts)}>
                      <div style={{ minWidth: 0 }}>
                        <div className="rt2-row-main">
                          <strong><bdi dir="ltr">{String(r.symbol || '').replace('-SWAP-USDT', '')}</bdi></strong>
                          <span className={r.direction === 'long' ? 'rt2-long' : 'rt2-short'}>
                            {r.direction === 'long' ? 'لانگ' : 'شورت'}
                          </span>
                          <span className="rt2-exit">
                            {ex.text}
                            {ex.raw && <bdi dir="ltr" className="rt2-raw"> {ex.raw}</bdi>}
                          </span>
                        </div>
                        <div className="rt2-row-sub">
                          <bdi>{when}</bdi>
                          {strat && <bdi dir="ltr">{strat}</bdi>}
                          {ver && <bdi dir="ltr">{ver}</bdi>}
                        </div>
                      </div>
                      <bdi dir="ltr" className="rt2-row-pnl num" style={{ color: pnlTone(pnl) }}>{money(pnl, true)}</bdi>
                    </div>
                  )
                })}
                {closedVisible < recent.length && (
                  <div style={{ textAlign: 'center', color: '#667788', fontSize: 12, padding: 8 }}>
                    {recent.length - closedVisible} معاملهٔ قدیمی‌تر — پایین‌تر بکشید
                  </div>
                )}
              </div>
            </>
          )}

          <div className="rt2-actions">
            <button type="button" className="rt2-btn" onClick={() => load()} disabled={loading}>
              {loading ? '…' : 'بروزرسانی'}
            </button>
            {flash === 'ok' && !loading && <span style={{ color: '#2DD4A7', fontSize: 12 }}>به‌روز شد</span>}
          </div>

          <details className="rt2-details" open={techOpen} onToggle={(e) => setTechOpen(e.currentTarget.open)}>
            <summary>جزئیات فنی</summary>
            <div className="rt2-details-body">
              <AgentPipeline status={status} />

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center', marginBottom: 12, fontSize: 12, color: '#7a8a9a', lineHeight: 1.5 }}>
                <span>قفل {mgr.profit_lock_trigger ?? '—'} · BE {mgr.breakeven_trigger_pct ?? '—'}%</span>
                <span>·</span>
                <span>استراتژی‌های زنده: {status.gh_entry?.live?.length ?? '—'}</span>
                <span>·</span>
                <span>اهرم {status.leverage ?? '—'}x</span>
                <span>·</span>
                <span>سقف نگه‌داری: ۱۲h (۱ ساعته) / ۲۴h (۴ ساعته)</span>
              </div>

              {status.news_blackout?.active ? (
                <div style={{ marginBottom: 12, padding: '10px 12px', borderRadius: 10, background: '#1a1530', border: '1px solid #5b4a9e', color: '#C4B5FD', fontSize: 12, lineHeight: 1.6, textAlign: 'right' }}>
                  <strong>توقف به‌خاطر خبر مهم</strong>
                  <div style={{ marginTop: 6, color: '#E9D5FF', fontSize: 12, fontWeight: 600 }}>
                    خبر: {status.news_blackout.event_title || status.news_blackout.event?.title || 'high-impact USD'}
                  </div>
                  <div style={{ marginTop: 4, color: '#A78BFA', fontSize: 12 }}>
                    از <bdi>{formatTehran(status.news_blackout.window_start_iso || status.news_blackout.window_start_ts)}</bdi>
                    {' '}تا{' '}
                    <bdi>{formatTehran(status.news_blackout.window_end_iso || status.news_blackout.window_end_ts)}</bdi>
                    <span style={{ color: '#7C6BA8' }}> (تهران)</span>
                  </div>
                  <div style={{ marginTop: 4, color: '#8B7BB8', fontSize: 11 }}>
                    در این بازه پوزیشن جدید باز نمی‌شود · پوزیشن‌های باز مدیریت می‌شوند
                  </div>
                </div>
              ) : null}

              {/* V.2.10.79 — چیپ‌های فشرده گیت ورود */}
              {status.real_trading_enabled ? (
                <div style={{ marginBottom: 12, padding: '8px 10px', borderRadius: 10, background: '#101a26', border: '1px solid #243444', textAlign: 'right' }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'flex-end', alignItems: 'center', marginBottom: 6 }}>
                    {(status.entry_block_summary?.chips || []).length > 0
                      ? status.entry_block_summary.chips.map((c) => (
                          <span
                            key={c.id}
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              padding: '2px 8px',
                              borderRadius: 999,
                              background: c.ok ? '#14352c' : '#3a2210',
                              color: c.ok ? '#2DD4A7' : '#F5C542',
                              border: `1px solid ${c.ok ? '#1e5c48' : '#6b4e14'}`,
                              direction: 'ltr',
                            }}
                          >
                            {c.ok ? '✓' : '✗'} {c.t}
                          </span>
                        ))
                      : (
                          <>
                            <span style={{ fontSize: 11, color: status.auto_entry_pause ? '#F5C542' : '#2DD4A7' }}>
                              {status.auto_entry_pause ? '✗ pause' : '✓ بدون‌pause'}
                            </span>
                            <span style={{ fontSize: 11, color: status.news_blackout?.active ? '#F5C542' : '#2DD4A7' }}>
                              {status.news_blackout?.active ? '✗ خبر' : '✓ خبرOK'}
                            </span>
                          </>
                        )}
                  </div>
                  <div style={{ fontSize: 12, color: '#8ab4a4', lineHeight: 1.5 }}>
                    {status.gh_entry?.line
                      || status.entry_block_summary?.line
                      || status.auto_entry_pause_reason
                      || (status.entry_block_summary?.can_enter
                        ? `آزاد · منتظر score≥${status.min_confluence ?? 92}`
                        : '—')}
                  </div>
                  {status.auto_entry_pause && (
                    <div style={{ fontSize: 11, color: '#7a8a9a', marginTop: 4 }}>
                      «pause» در این ردیف فقط به موتور قدیمی روند/رنج مربوط است، نه استراتژی‌های زنده.
                    </div>
                  )}
                  {/* استثنای ADX فقط وقتی pause مربوط به BTC است نه قفل SL */}
                  {status.auto_entry_pause
                    && /BTC|CHOP|WEAK|رژیم/i.test(String(status.auto_entry_pause_reason || ''))
                    && openDespitePause.length > 0 && (
                    <div style={{ marginTop: 4, color: '#2DD4A7', fontSize: 11 }}>
                      استثنا ADX≥{status?.entry_filters?.adx_strong_bypass_btc ?? 30}:{' '}
                      {openDespitePause.map((x) => x.symbol).join(' · ')}
                    </div>
                  )}
                </div>
              ) : null}

              <a href={STATUS_VIEWER} target="_blank" rel="noreferrer" className="rt2-btn" style={{ display: 'inline-block', textDecoration: 'none' }}>
                صفحهٔ وضعیت / رژیم
              </a>
            </div>
          </details>
        </>
      )}

      <style>{`
        .rt2 { font-size: 14px; }
        .rt2 .num { font-variant-numeric: tabular-nums; }
        .rt2-summary { position: relative; padding: 16px 16px 14px; border-radius: 14px; background: #121b28; border: 1px solid #243444;
          border-inline-start: 4px solid var(--rt2-tone, #5a6a7a); margin-bottom: 18px; }
        .rt2-tone-ok { --rt2-tone: #2DD4A7; } .rt2-tone-warn { --rt2-tone: #F5A623; }
        .rt2-tone-bad { --rt2-tone: #FF5C72; } .rt2-tone-off { --rt2-tone: #5a6a7a; }
        .rt2-sentence { display: flex; gap: 10px; align-items: flex-start; font-size: 17px; font-weight: 700; line-height: 1.7; color: #f1f5fa; }
        .rt2-dot { flex: none; width: 10px; height: 10px; border-radius: 50%; background: var(--rt2-tone); margin-top: 10px;
          box-shadow: 0 0 0 4px color-mix(in srgb, var(--rt2-tone) 22%, transparent); }
        .rt2-suffix { display: block; font-size: 14px; font-weight: 500; color: #F5C542; }
        .rt2-figures { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 14px 0 12px; }
        .rt2-label { font-size: 12px; color: #8899aa; margin-bottom: 2px; }
        .rt2-big { display: block; font-size: 28px; font-weight: 700; line-height: 1.25; color: #f1f5fa; text-align: right; }
        .rt2-facts { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px 12px; margin: 0; padding-top: 12px; border-top: 1px solid #1f2c3c; }
        .rt2-facts dt { font-size: 12px; color: #7a8a9a; } .rt2-facts dd { margin: 0; font-size: 14px; font-weight: 600; color: #d6e0ea; }
        .rt2-facts bdi { display: inline-block; }
        .rt2-news { margin-top: 12px; font-size: 12px; color: #8899bb; line-height: 1.7; }
        .rt2-err { margin-top: 10px; color: #FF5C72; font-size: 13px; }
        .rt2-h { font-size: 14px; font-weight: 700; color: #c9d5e2; margin: 0 0 8px; }
        .rt2-empty { padding: 16px 12px; text-align: center; color: #7a8a9a; border: 1px dashed #2a3a4c; border-radius: 12px; margin-bottom: 18px; font-size: 13px; }
        .rt2-list { max-height: 330px; overflow-y: auto; border: 1px solid #1f2c3c; border-radius: 12px; padding: 2px 12px; background: #101824; margin-bottom: 12px; }
        .rt2-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid #1a2634; }
        .rt2-row:last-child { border-bottom: 0; }
        .rt2-row-main { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; font-size: 14px; }
        .rt2-long { color: #2DD4A7; font-size: 12px; } .rt2-short { color: #FF5C72; font-size: 12px; }
        .rt2-exit { color: #aebccb; font-size: 13px; } .rt2-raw { color: #5f6f80; font-size: 11px; }
        .rt2-row-sub { display: flex; flex-wrap: wrap; gap: 2px 10px; color: #6f8092; font-size: 11.5px; margin-top: 2px; }
        .rt2-row-pnl { font-size: 15px; font-weight: 700; white-space: nowrap; }
        .rt2-actions { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
        .rt2-btn { background: #17283a; border: 1px solid #2a4a5a; color: #d6e6f5; border-radius: 10px; padding: 10px 16px; min-height: 42px;
          font: inherit; font-size: 13px; cursor: pointer; }
        .rt2-btn:disabled { cursor: wait; opacity: .7; }
        .rt2-btn:focus-visible, .rt2-details > summary:focus-visible { outline: 2px solid #6fb7ff; outline-offset: 2px; }
        .rt2-details { border: 1px solid #1f2c3c; border-radius: 12px; background: #0f1722; }
        .rt2-details > summary { cursor: pointer; padding: 12px 14px; min-height: 44px; font-size: 13px; font-weight: 600; color: #aebccb; list-style-position: inside; }
        .rt2-details-body { padding: 4px 12px 14px; }
        @media (min-width: 640px) {
          .rt2-facts { grid-template-columns: repeat(4, 1fr); }
          .rt2-big { font-size: 32px; }
        }
        @media (min-width: 720px) {
          .rt-agents { grid-template-columns: repeat(3, 1fr) !important; }
        }
        @media (max-width: 519px) {
          .rt-agent-en { display: none; }
        }
        .pos-levels {
          display: flex !important;
          flex-wrap: nowrap !important;
          flex-direction: row !important;
        }
      `}</style>
    </div>
  )
}
