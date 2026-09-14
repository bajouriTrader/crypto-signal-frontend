import { useEffect, useMemo, useState } from 'react'
import { authFetch } from './auth'

/**
 * سشن‌ها به وقت تهران (UTC+3:30).
 * open/close: ساعت اعشاری ۰–۲۴ به وقت تهران
 */
const SESSIONS = [
  { id: 'sydney', name: 'Sydney', nameFa: 'سیدنی', flag: '🇦🇺', open: 1.5, close: 10.5, color: '#5b8def' },
  { id: 'tokyo', name: 'Tokyo', nameFa: 'توکیو', flag: '🇯🇵', open: 3.5, close: 12.5, color: '#e85d6c' },
  { id: 'frankfurt', name: 'Frankfurt', nameFa: 'فرانکفورت', flag: '🇩🇪', open: 10.5, close: 19.5, color: '#c4a35a' },
  { id: 'london', name: 'London', nameFa: 'لندن', flag: '🇬🇧', open: 11.5, close: 20.5, color: '#6ec6ff' },
  { id: 'newyork', name: 'New York', nameFa: 'نیویورک', flag: '🇺🇸', open: 16.5, close: 1.5, color: '#3ecf8e' },
]

function tehranParts(date = new Date()) {
  const fmt = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Tehran',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
  })
  const parts = Object.fromEntries(fmt.formatToParts(date).map((p) => [p.type, p.value]))
  return {
    clock: `${parts.hour}:${parts.minute}:${parts.second}`,
    day: `${parts.weekday} ${parts.day}/${parts.month}`,
    hour: Number(parts.hour),
    minute: Number(parts.minute),
    second: Number(parts.second),
  }
}

/** ساعت اعشاری فعلی به وقت تهران (۰–۲۴) */
function tehranHourFloat(date = new Date()) {
  const p = tehranParts(date)
  return p.hour + p.minute / 60 + p.second / 3600
}

function formatTehranClock(hFloat) {
  let h = Math.floor(hFloat) % 24
  if (h < 0) h += 24
  const m = Math.round((hFloat - Math.floor(hFloat)) * 60) % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function isOpen(openH, closeH, nowH) {
  if (openH < closeH) return nowH >= openH && nowH < closeH
  return nowH >= openH || nowH < closeH
}

function minutesUntil(openH, closeH, nowH, wantClose) {
  const target = wantClose ? closeH : openH
  let delta = target - nowH
  if (delta <= 0) delta += 24
  return Math.max(0, Math.round(delta * 60))
}

function formatDuration(mins) {
  const h = Math.floor(mins / 60)
  const m = mins % 60
  if (h <= 0) return `${m}د`
  return `${h}س ${m}د`
}

function segments(openH, closeH) {
  if (openH < closeH) return [[openH, closeH]]
  return [
    [openH, 24],
    [0, closeH],
  ]
}

function sessionStatus(s, nowH) {
  const open = isOpen(s.open, s.close, nowH)
  if (open) {
    return {
      open: true,
      label: `${formatDuration(minutesUntil(s.open, s.close, nowH, true))} تا پایان`,
      range: `${formatTehranClock(s.open)}–${formatTehranClock(s.close)}`,
    }
  }
  return {
    open: false,
    label: `${formatDuration(minutesUntil(s.open, s.close, nowH, false))} تا شروع`,
    range: `${formatTehranClock(s.open)}–${formatTehranClock(s.close)}`,
  }
}

function currentOverlaps(nowH) {
  const openOnes = SESSIONS.filter((s) => isOpen(s.open, s.close, nowH))
  if (openOnes.length < 2) return []
  return [openOnes.map((s) => s.nameFa).join(' + ')]
}

export default function SessionClock() {
  const [tick, setTick] = useState(() => Date.now())
  const [news, setNews] = useState({ today_events: [], active: false, next_window: null })

  useEffect(() => {
    const id = setInterval(() => setTick(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await authFetch('/real-trade/status')
        if (!res.ok) return
        const data = await res.json()
        const nb = data.news_blackout || {}
        if (!cancelled) {
          setNews({
            today_events: nb.today_events || [],
            active: !!nb.active,
            event_title: nb.event_title || nb.event?.title,
            next_window: nb.next_window || null,
            reason: nb.reason || '',
          })
        }
      } catch (e) {
        /* قبل از لاگین ممکن است 401 */
      }
    }
    load()
    const id = setInterval(load, 60000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  const now = new Date(tick)
  const { clock, day } = tehranParts(now)
  const nowH = tehranHourFloat(now)
  const nowPct = (nowH / 24) * 100

  const statuses = useMemo(
    () => SESSIONS.map((s) => ({ ...s, st: sessionStatus(s, nowH) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tick]
  )
  const overlaps = useMemo(() => currentOverlaps(nowH), [tick])

  const events = news.today_events || []

  return (
    <div className="ff-row" title="سشن‌ها و اخبار — همه ساعت‌ها به وقت تهران">
      <div className="ff-sessions ff-sessions-compact">
        <div className="ff-sessions-head">
          <div className="ff-sessions-tehran">
            <span className="ff-sessions-tehran-label">تهران</span>
            <span className="ff-sessions-tehran-time">{clock}</span>
            <span className="ff-sessions-tehran-day">{day}</span>
          </div>
          {overlaps.length > 0 && (
            <div className="ff-overlap-badge">
              <span className="ff-overlap-dot" />
              {overlaps[0]}
            </div>
          )}
        </div>

        <div className="ff-timeline">
          <div className="ff-timeline-track ff-timeline-track-sm">
            {SESSIONS.map((s) =>
              segments(s.open, s.close).map(([a, b], i) => (
                <div
                  key={`${s.id}-${i}`}
                  className={`ff-seg ${isOpen(s.open, s.close, nowH) ? 'ff-seg-live' : ''}`}
                  style={{
                    left: `${(a / 24) * 100}%`,
                    width: `${((b - a) / 24) * 100}%`,
                    background: s.color,
                    opacity: isOpen(s.open, s.close, nowH) ? 0.85 : 0.28,
                  }}
                  title={`${s.nameFa} ${formatTehranClock(s.open)}–${formatTehranClock(s.close)} تهران`}
                />
              ))
            )}
            <div className="ff-now-line" style={{ left: `${nowPct}%` }} />
          </div>
          <div className="ff-timeline-hours">
            {[0, 6, 12, 18, 24].map((h) => (
              <span key={h} style={{ left: `${(h / 24) * 100}%` }}>
                {String(h).padStart(2, '0')}
              </span>
            ))}
          </div>
        </div>

        <div className="ff-pills ff-pills-compact">
          {statuses.map((s) => (
            <div
              key={s.id}
              className={`ff-pill ${s.st.open ? 'ff-pill-open' : 'ff-pill-closed'}`}
              style={
                s.st.open
                  ? { borderColor: s.color, boxShadow: `0 0 8px ${s.color}33` }
                  : undefined
              }
              title={`${s.nameFa}: ${s.st.range} تهران`}
            >
              <span className="ff-pill-flag">{s.flag}</span>
              <div className="ff-pill-body">
                <div className="ff-pill-name">{s.nameFa}</div>
                <div className="ff-pill-meta">{s.st.range}</div>
                <div className="ff-pill-meta">{s.st.label}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className={`ff-news ${news.active ? 'ff-news-active' : ''}`}>
        <div className="ff-news-head">
          <span className="ff-news-title">📰 اخبار امروز (تهران)</span>
          {news.active && <span className="ff-news-badge">توقف ورود</span>}
        </div>
        {events.length === 0 ? (
          <div className="ff-news-empty">
            {news.next_window?.event_title ? (
              <>
                خبر high-impact دیگری برای امروز ثبت نشده
                <div className="ff-news-next">
                  بعدی: {news.next_window.event_title}
                </div>
              </>
            ) : (
              'خبر high-impact برای امروز نیست / تقویم در دسترس نیست'
            )}
          </div>
        ) : (
          <ul className="ff-news-list">
            {events.slice(0, 6).map((ev, i) => (
              <li key={`${ev.ts}-${i}`} className="ff-news-item">
                <span className="ff-news-time">{ev.time_tehran || '—'}</span>
                <span className="ff-news-name">{ev.title_fa || ev.title || 'خبر'}</span>
                <span className="ff-news-impact">مهم</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
