import { useEffect, useState } from 'react'

/** سشن‌های بازار (ساعت به UTC، نیم‌روز ۰–۲۴) */
const SESSIONS = [
  { id: 'sydney', name: 'سیدنی', flag: '🇦🇺', open: 22, close: 7 },
  { id: 'tokyo', name: 'توکیو', flag: '🇯🇵', open: 0, close: 9 },
  { id: 'frankfurt', name: 'فرانکفورت', flag: '🇩🇪', open: 7, close: 16 },
  { id: 'london', name: 'لندن', flag: '🇬🇧', open: 8, close: 17 },
  { id: 'newyork', name: 'نیویورک', flag: '🇺🇸', open: 13, close: 22 },
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

/** آیا سشن الان باز است؟ (پشتیبانی از عبور از نیمه‌شب) */
function isOpen(openH, closeH, nowH) {
  if (openH < closeH) return nowH >= openH && nowH < closeH
  return nowH >= openH || nowH < closeH
}

/** دقیقه تا باز یا بسته شدن بعدی */
function minutesUntil(openH, closeH, nowH, wantClose) {
  const target = wantClose ? closeH : openH
  let delta = target - nowH
  if (delta <= 0) delta += 24
  return Math.round(delta * 60)
}

function formatDuration(mins) {
  const h = Math.floor(mins / 60)
  const m = mins % 60
  if (h <= 0) return `${m}د`
  return `${h}س ${m}د`
}

function sessionStatus(s, nowH) {
  const open = isOpen(s.open, s.close, nowH)
  if (open) {
    return { open: true, label: `تا ${formatDuration(minutesUntil(s.open, s.close, nowH, true))}` }
  }
  return { open: false, label: `شروع ${formatDuration(minutesUntil(s.open, s.close, nowH, false))}` }
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

  return (
    <div className="session-clock" title="سشن‌های معاملاتی — ساعت به وقت تهران">
      <div className="session-clock-now">
        <span className="session-clock-label">تهران</span>
        <span className="session-clock-time">{clock}</span>
        <span className="session-clock-day">{day}</span>
      </div>
      <div className="session-clock-pills">
        {SESSIONS.map((s) => {
          const st = sessionStatus(s, nowH)
          return (
            <div
              key={s.id}
              className={`session-pill ${st.open ? 'session-pill-open' : 'session-pill-closed'}`}
            >
              <span className="session-pill-flag">{s.flag}</span>
              <span className="session-pill-name">{s.name}</span>
              <span className="session-pill-meta">{st.label}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
