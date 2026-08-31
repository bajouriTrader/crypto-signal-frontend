import { useEffect, useState } from 'react'
import { authFetch } from './auth'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

const LABELS = {
  min_confluence: 'حداقل امتیاز Confluence ریل',
  min_sl_distance_pct: 'حداقل فاصله SL (%)',
  min_rr: 'حداقل R:R',
  min_tp_distance_pct: 'حداقل فاصله TP (%)',
  real_min_symbol_wr: 'حداقل WR دمو نماد',
  symbol_cooldown_sec: 'کول‌داون نماد بعد از رد (ثانیه)',
  post_close_cooldown_sec: 'کول‌داون بعد از بستن (ثانیه)',
  profit_lock_trigger: 'قفل سود (نسبت مسیر تا TP)',
  min_profit_pct: 'حداقل سود برای قفل (%)',
  breakeven_trigger_pct: 'آستانه BE روی صرافی (%)',
  max_hold_seconds: 'سقف نگهداری (ثانیه)',
  daily_loss_limit: 'سقف ضرر روزانه (USDT)',
  margin_fraction: 'کسر مارجین از موجودی',
  max_open_positions: 'سقف پوزیشن همزمان',
  leverage: 'اهرم',
  enable_chop_filter: 'فیلتر بازار چاپی (ADX)',
  chop_adx_threshold: 'آستانه ADX چاپی',
  max_same_direction: 'سقف پوزیشن هم‌جهت',
}

const GROUPS = [
  {
    title: 'ورود ریل',
    keys: [
      'min_confluence', 'min_sl_distance_pct', 'min_rr', 'min_tp_distance_pct',
      'real_min_symbol_wr', 'symbol_cooldown_sec', 'post_close_cooldown_sec',
      'enable_chop_filter', 'chop_adx_threshold',
    ],
  },
  {
    title: 'خروج / مدیریت سود',
    keys: [
      'profit_lock_trigger', 'min_profit_pct', 'breakeven_trigger_pct', 'max_hold_seconds',
    ],
  },
  {
    title: 'سرمایه و ریسک',
    keys: [
      'daily_loss_limit', 'margin_fraction', 'max_open_positions', 'leverage', 'max_same_direction',
    ],
  },
]

export default function SettingsPanel() {
  const [settings, setSettings] = useState({})
  const [defaults, setDefaults] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [pwCurrent, setPwCurrent] = useState('')
  const [pwNew, setPwNew] = useState('')
  const [pwNew2, setPwNew2] = useState('')
  const [pwOverride, setPwOverride] = useState(false)

  const load = async () => {
    setLoading(true)
    setErr('')
    try {
      const res = await authFetch(`${API_BASE_URL}/settings`)
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        const detail = data.detail || res.statusText || ''
        if (res.status === 404) {
          throw new Error(
            'مسیر /settings روی بک‌اند پیدا نشد (۴۰۴). در app.py این دو خط را بگذار و Relaunch کن: from settings_api import router as settings_router — app.include_router(settings_router)'
          )
        }
        throw new Error(`بارگذاری ناموفق (${res.status}) ${detail}`)
      }
      setSettings(data.settings || {})
      setDefaults(data.defaults || {})
      setPwOverride(!!data.password_override_active)
    } catch (e) {
      setErr(e.message || 'خطا')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const setField = (key, value) => {
    setSettings((s) => ({ ...s, [key]: value }))
  }

  const save = async () => {
    setSaving(true)
    setMsg('')
    setErr('')
    try {
      const res = await authFetch(`${API_BASE_URL}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'ذخیره ناموفق')
      setSettings(data.settings || settings)
      setMsg('ذخیره شد و روی ریل اعمال شد.')
    } catch (e) {
      setErr(e.message || 'خطا در ذخیره')
    } finally {
      setSaving(false)
    }
  }

  const changePassword = async () => {
    setMsg('')
    setErr('')
    if (pwNew.length < 4) {
      setErr('رمز جدید حداقل ۴ کاراکتر')
      return
    }
    if (pwNew !== pwNew2) {
      setErr('تکرار رمز با رمز جدید یکی نیست')
      return
    }
    try {
      const res = await authFetch(`${API_BASE_URL}/settings/password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: pwNew, current_password: pwCurrent }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'تغییر رمز ناموفق')
      setMsg(data.message || 'رمز به‌روز شد')
      setPwCurrent('')
      setPwNew('')
      setPwNew2('')
      setPwOverride(true)
    } catch (e) {
      setErr(typeof e.message === 'string' ? e.message : 'خطا')
    }
  }

  const goHome = () => {
    window.location.hash = ''
    window.location.reload()
  }

  if (loading) {
    return (
      <div className="app">
        <header className="topbar">
          <div className="brand">
            <span className="brand-mark">◈</span>
            <span className="brand-name">تنظیمات SignalDesk</span>
          </div>
        </header>
        <main className="main"><p>در حال بارگذاری…</p></main>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">◈</span>
          <span className="brand-name">تنظیمات</span>
        </div>
        <div className="topbar-status">
          <a
            href="#"
            className="topbar-admin-link"
            onClick={(e) => {
              e.preventDefault()
              goHome()
            }}
          >
            بازگشت به صفحه اصلی
          </a>
        </div>
      </header>

      <main className="main" style={{ maxWidth: 720, margin: '0 auto' }}>
        <section className="final-section" style={{ marginBottom: 16 }}>
          <p style={{ opacity: 0.85, lineHeight: 1.6 }}>
            متغیرهای ریل را از اینجا تغییر بده. بعد از ذخیره بلافاصله اعمال می‌شوند
            (بدون Relaunch). مقادیر افراطی می‌توانند ترید را متوقف یا ریسک را بالا ببرند.
          </p>
          {msg && <p className="error-note" style={{ color: '#2DD4A7' }}>{msg}</p>}
          {err && <p className="error-note">{err}</p>}
        </section>

        {GROUPS.map((g) => (
          <section key={g.title} className="final-section" style={{ marginBottom: 20 }}>
            <h3 style={{ marginTop: 0 }}>{g.title}</h3>
            <div style={{ display: 'grid', gap: 12 }}>
              {g.keys.map((key) => {
                const val = settings[key]
                const isBool = typeof defaults[key] === 'boolean' || typeof val === 'boolean'
                return (
                  <label
                    key={key}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: 12,
                      flexWrap: 'wrap',
                    }}
                  >
                    <span style={{ flex: 1, minWidth: 180 }}>{LABELS[key] || key}</span>
                    {isBool ? (
                      <select
                        value={val ? '1' : '0'}
                        onChange={(e) => setField(key, e.target.value === '1')}
                        className="admin-pass-input"
                        style={{ width: 140 }}
                      >
                        <option value="1">روشن</option>
                        <option value="0">خاموش</option>
                      </select>
                    ) : (
                      <input
                        type="number"
                        step="any"
                        className="admin-pass-input"
                        style={{ width: 140 }}
                        value={val ?? ''}
                        onChange={(e) => {
                          const n = e.target.value
                          setField(key, n === '' ? '' : Number(n))
                        }}
                      />
                    )}
                  </label>
                )
              })}
            </div>
          </section>
        ))}

        <div style={{ display: 'flex', gap: 12, marginBottom: 28 }}>
          <button className="btn-primary" type="button" onClick={save} disabled={saving}>
            {saving ? 'در حال ذخیره…' : 'ذخیره تنظیمات ریل'}
          </button>
          <button
            type="button"
            className="topbar-admin-link"
            onClick={() => setSettings({ ...defaults })}
          >
            بازگردانی پیش‌فرض‌ها (هنوز ذخیره نشده)
          </button>
        </div>

        <section className="final-section">
          <h3 style={{ marginTop: 0 }}>رمز ورود به پلتفرم</h3>
          <p style={{ opacity: 0.8, fontSize: 14 }}>
            رمز ورود سایت را اینجا عوض کن.
            {pwOverride
              ? ' الان override فایل فعال است.'
              : ' فعلاً از Secret محیطی (SITE_PASSWORD) استفاده می‌شود.'}
            {' '}روی HuggingFace برای ماندگاری بعد از ریست، Persistent Storage توصیه می‌شود.
          </p>
          <div style={{ display: 'grid', gap: 10, maxWidth: 360 }}>
            <input
              type="password"
              className="admin-pass-input"
              placeholder="رمز فعلی (اختیاری اگر می‌دانی)"
              value={pwCurrent}
              onChange={(e) => setPwCurrent(e.target.value)}
            />
            <input
              type="password"
              className="admin-pass-input"
              placeholder="رمز جدید"
              value={pwNew}
              onChange={(e) => setPwNew(e.target.value)}
            />
            <input
              type="password"
              className="admin-pass-input"
              placeholder="تکرار رمز جدید"
              value={pwNew2}
              onChange={(e) => setPwNew2(e.target.value)}
            />
            <button className="btn-primary" type="button" onClick={changePassword}>
              تغییر رمز ورود
            </button>
          </div>
        </section>
      </main>
    </div>
  )
}
