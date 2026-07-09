import { useEffect, useState } from 'react'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'
const ADMIN_PASSCODE = 'bajouri1404' // فقط یه محافظت ساده سمت کلاینت، امنیت واقعی نیست

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('fa-IR')
  } catch {
    return iso
  }
}

function AnalysesTable({ rows }) {
  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead>
          <tr>
            <th>زمان</th>
            <th>سیگنال</th>
            <th>امتیاز نهایی</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{fmtTime(r.created_at)}</td>
              <td className="admin-cell-signal">{(r.raw_signal?.signal_text || '').slice(0, 60)}</td>
              <td dir="ltr">{r.final_verdict?.signal_quality_score ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DemoTradesTable({ rows }) {
  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead>
          <tr>
            <th>باز شدن</th>
            <th>نماد</th>
            <th>جهت</th>
            <th>ورود</th>
            <th>هدف</th>
            <th>حد ضرر</th>
            <th>وضعیت</th>
            <th>خروج</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.trade_id}>
              <td>{fmtTime(r.opened_at)}</td>
              <td>{r.symbol}</td>
              <td>{r.direction === 'long' ? 'لانگ' : 'شورت'}</td>
              <td dir="ltr">{r.entry}</td>
              <td dir="ltr">{r.target}</td>
              <td dir="ltr">{r.stop_loss}</td>
              <td>
                {r.status === 'open' ? 'باز' : r.status === 'win' ? '✅ برد' : '❌ باخت'}
              </td>
              <td dir="ltr">{r.exit_price ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function AdminPanel() {
  const [unlocked, setUnlocked] = useState(
    sessionStorage.getItem('admin_unlocked') === '1'
  )
  const [passInput, setPassInput] = useState('')
  const [tab, setTab] = useState('analyses') // 'analyses' | 'demo'
  const [analyses, setAnalyses] = useState([])
  const [demoTrades, setDemoTrades] = useState([])
  const [status, setStatus] = useState('idle')

  const tryUnlock = () => {
    if (passInput === ADMIN_PASSCODE) {
      sessionStorage.setItem('admin_unlocked', '1')
      setUnlocked(true)
    } else {
      alert('رمز اشتباهه')
    }
  }

  const loadData = async () => {
    setStatus('loading')
    try {
      const [analysesRes, demoRes] = await Promise.all([
        fetch(`${API_BASE_URL}/history?limit=30`),
        fetch(`${API_BASE_URL}/demo-trade/history?limit=30`),
      ])
      const analysesData = await analysesRes.json()
      const demoData = await demoRes.json()
      setAnalyses(analysesData.analyses || [])
      setDemoTrades(demoData.trades || [])
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }

  useEffect(() => {
    if (unlocked) loadData()
  }, [unlocked])

  if (!unlocked) {
    return (
      <div className="admin-gate">
        <h2>پنل ادمین</h2>
        <input
          type="password"
          className="admin-pass-input"
          placeholder="رمز عبور"
          value={passInput}
          onChange={(e) => setPassInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && tryUnlock()}
        />
        <button className="btn-primary" onClick={tryUnlock}>
          ورود
        </button>
        <a className="admin-back-link" href="./">
          بازگشت به صفحه اصلی
        </a>
      </div>
    )
  }

  return (
    <div className="admin-panel">
      <div className="admin-head">
        <h2>پنل ادمین</h2>
        <div className="admin-head-actions">
          <button className="btn-mini" onClick={loadData}>
            بروزرسانی
          </button>
          <a className="admin-back-link" href="./">
            بازگشت به سایت
          </a>
        </div>
      </div>

      <div className="tabs">
        <button className={`tab ${tab === 'analyses' ? 'tab-active' : ''}`} onClick={() => setTab('analyses')}>
          سوابق تحلیل‌ها ({analyses.length})
        </button>
        <button className={`tab ${tab === 'demo' ? 'tab-active' : ''}`} onClick={() => setTab('demo')}>
          معاملات دمو ({demoTrades.length})
        </button>
      </div>

      {status === 'loading' && <div className="watchlist-status">در حال بارگذاری…</div>}
      {status === 'error' && <div className="watchlist-status">خطا در دریافت اطلاعات</div>}

      {status === 'ready' && tab === 'analyses' && <AnalysesTable rows={analyses} />}
      {status === 'ready' && tab === 'demo' && <DemoTradesTable rows={demoTrades} />}
    </div>
  )
}
