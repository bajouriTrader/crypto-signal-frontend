import { useEffect, useMemo, useState } from 'react'

/**
 * سشن‌ها به UTC (بازار فارکس تقریبی).
 * open/close: ساعت اعشاری ۰–۲۴
 */
const SESSIONS = [
  { id: 'sydney', name: 'Sydney', nameFa: 'سیدنی', flag: '🇦🇺', open: 22, close: 7, color: '#5b8def' },
  { id: 'tokyo', name: 'Tokyo', nameFa: 'توکیو', flag: '🇯🇵', open: 0, close: 9, color: '#e85d6c' },
  { id: 'frankfurt', name: 'Frankfurt', nameFa: 'فرانکفورت', flag: '🇩🇪', open: 7, close: 16, color: '#c4a35a' },
  { id: 'london', name: 'London', nameFa: 'لندن', flag: '🇬🇧', open: 8, close: 17, color: '#6ec6ff' },
  { id: 'newyork', name: 'New York', nameFa: 'نیویورک', flag: '🇺🇸', open: 13, close: 22, color: '#3ecf8e' },
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
  }
}

function utcHourFloat(date = new Date()) {
  return date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600
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
  if (h <= 0) return `${m}m`
  return `${h}h ${m}m`
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
      label: `Ends in ${formatDuration(minutesUntil(s.open, s.close, nowH, true))}`,
    }
  }
  return {
    open: false,
    label: `Begins in ${formatDuration(minutesUntil(s.open, s.close, nowH, false))}`,
  }
}

function currentOverlaps(nowH) {
  const openOnes = SESSIONS.filter((s) => isOpen(s.open, s.close, nowH))
  if (openOnes.length < 2) return []
  return [openOnes.map((s) => s.nameFa).join(' + ')]
}

export default function SessionClock() {
  const [tick, setTick] = useState(() => Date.now())

  useEffect(() => {
    const id = setInterval(() => setTick(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const now = new Date(tick)
  const { clock, day } = tehranParts(now)
  const nowH = utcHourFloat(now)
  const nowPct = (nowH / 24) * 100

  const statuses = useMemo(
    () => SESSIONS.map((s) => ({ ...s, st: sessionStatus(s, nowH) })),
    // nowH changes every second via tick
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tick]
  )
  const overlaps = useMemo(() => currentOverlaps(nowH), [tick])

  return (
    <div className="ff-sessions" title="سشن‌های معاملاتی — ساعت تهران">
      <div className="ff-sessions-head">
        <div className="ff-sessions-tehran">
          <span className="ff-sessions-tehran-label">تهران</span>
          <span className="ff-sessions-tehran-time">{clock}</span>
          <span className="ff-sessions-tehran-day">{day}</span>
        </div>
        {overlaps.length > 0 && (
          <div className="ff-overlap-badge">
            <span className="ff-overlap-dot" />
            هم‌پوشانی: {overlaps[0]}
          </div>
        )}
      </div>

      <div className="ff-timeline">
        <div className="ff-timeline-track">
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
                title={s.nameFa}
              />
            ))
          )}
          <div className="ff-now-line" style={{ left: `${nowPct}%` }} />
        </div>
        <div className="ff-timeline-hours">
          {[0, 4, 8, 12, 16, 20, 24].map((h) => (
            <span key={h} style={{ left: `${(h / 24) * 100}%` }}>
              {String(h).padStart(2, '0')}
            </span>
          ))}
        </div>
      </div>

      <div className="ff-pills">
        {statuses.map((s) => (
          <div
            key={s.id}
            className={`ff-pill ${s.st.open ? 'ff-pill-open' : 'ff-pill-closed'}`}
            style={
              s.st.open
                ? { borderColor: s.color, boxShadow: `0 0 12px ${s.color}33` }
                : undefined
            }
          >
            <span className="ff-pill-flag">{s.flag}</span>
            <div className="ff-pill-body">
              <div className="ff-pill-name">{s.name}</div>
              <div className="ff-pill-meta">{s.st.label}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
