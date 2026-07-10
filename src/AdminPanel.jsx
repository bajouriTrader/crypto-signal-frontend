import { authFetch } from './auth'
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

function statusLabel(status) {
  if (status === 'open') return '⏳ باز'
  if (status === 'win') return '✅ برد'
  if (status === 'loss') return '❌ باخت'
  if (status === 'timeout_win') return '✅ برد (پایان بازه)'
  if (status === 'timeout_loss') return '❌ باخت (پایان بازه)'
  if (status === 'manual_win') return '✅ برد (دستی)'
  if (status === 'manual_loss') return '❌ باخت (دستی)'
  return status
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
            <th>حالت</th>
            <th>مبلغ</th>
            <th>ورود</th>
            <th>هدف</th>
            <th>حد ضرر</th>
            <th>وضعیت</th>
            <th>خروج</th>
            <th>سود/زیان</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.trade_id}>
              <td>{fmtTime(r.opened_at)}</td>
              <td>{r.symbol}</td>
              <td>{r.direction === 'long' ? 'لانگ' : 'شورت'}</td>
              <td>{r.mode === 'relaxed' ? 'ساده‌گیر' : 'سخت‌گیر'}</td>
              <td dir="ltr">{r.margin_usdt ?? 10}$ / {r.leverage}x</td>
              <td dir="ltr">{r.entry}</td>
              <td dir="ltr">{r.target}</td>
              <td dir="ltr">{r.stop_loss}</td>
              <td>{statusLabel(r.status)}</td>
              <td dir="ltr">{r.exit_price ?? '—'}</td>
              <td dir="ltr">{r.realized_pnl !== null && r.realized_pnl !== undefined ? `${r.realized_pnl >= 0 ? '+' : ''}${r.realized_pnl}$` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StatsPanel({ stats }) {
  if (!stats) return null

  return (
    <div>
      <div className="stats-summary-grid">
        <div className="stats-card">
          <span className="stats-card-label">Win Rate کلی</span>
          <span className="stats-card-value" dir="ltr">
            {stats.win_rate !== null ? `${stats.win_rate}%` : '—'}
          </span>
        </div>
        <div className="stats-card">
          <span className="stats-card-label">معاملات بسته‌شده</span>
          <span className="stats-card-value" dir="ltr">{stats.total_resolved}</span>
        </div>
        <div className="stats-card">
          <span className="stats-card-label">برد / باخت</span>
          <span className="stats-card-value" dir="ltr">
            {stats.wins} / {stats.losses}
          </span>
        </div>
        <div className="stats-card">
          <span className="stats-card-label">هنوز باز</span>
          <span className="stats-card-value" dir="ltr">{stats.total_open}</span>
        </div>
        <div className="stats-card">
          <span className="stats-card-label">بسته‌شده با Timeout</span>
          <span className="stats-card-value" dir="ltr">{stats.timeouts}</span>
        </div>
        <div className="stats-card">
          <span className="stats-card-label">بسته‌شده دستی</span>
          <span className="stats-card-value" dir="ltr">{stats.manual_closes}</span>
        </div>
      </div>

      <h3 className="stats-section-title">تفکیک بر اساس حالت (سخت‌گیر / ساده‌گیر)</h3>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>حالت</th>
              <th>تعداد</th>
              <th>برد</th>
              <th>Win Rate</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(stats.by_mode || {}).map(([m, v]) => (
              <tr key={m}>
                <td>{m === 'relaxed' ? 'ساده‌گیر' : 'سخت‌گیر'}</td>
                <td dir="ltr">{v.total}</td>
                <td dir="ltr">{v.wins}</td>
                <td dir="ltr">{v.win_rate !== null ? `${v.win_rate}%` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="stats-section-title">تفکیک بر اساس جهت</h3>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>جهت</th>
              <th>تعداد</th>
              <th>برد</th>
              <th>Win Rate</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(stats.by_direction || {}).map(([dir, v]) => (
              <tr key={dir}>
                <td>{dir === 'long' ? 'لانگ' : 'شورت'}</td>
                <td dir="ltr">{v.total}</td>
                <td dir="ltr">{v.wins}</td>
                <td dir="ltr">{v.win_rate !== null ? `${v.win_rate}%` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="stats-section-title">تفکیک بر اساس ارز</h3>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>ارز</th>
              <th>تعداد</th>
              <th>برد</th>
              <th>Win Rate</th>
            </tr>
          </thead>
          <tbody>
            {(stats.by_symbol || []).map((s) => (
              <tr key={s.symbol}>
                <td>{s.symbol}</td>
                <td dir="ltr">{s.total}</td>
                <td dir="ltr">{s.wins}</td>
                <td dir="ltr">{s.win_rate !== null ? `${s.win_rate}%` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function AdminPanel() {
  const [unlocked, setUnlocked] = useState(
    sessionStorage.getItem('admin_unlocked') === '1'
  )
  const [passInput, setPassInput] = useState('')
  const [tab, setTab] = useState('stats') // 'stats' | 'analyses' | 'demo'
  const [analyses, setAnalyses] = useState([])
  const [demoTrades, setDemoTrades] = useState([])
  const [stats, setStats] = useState(null)
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
      const [analysesRes, demoRes, statsRes] = await Promise.all([
        authFetch(`${API_BASE_URL}/history?limit=30`),
        authFetch(`${API_BASE_URL}/demo-trade/history?limit=50`),
        authFetch(`${API_BASE_URL}/demo-trade/stats`),
      ])
      const analysesData = await analysesRes.json()
      const demoData = await demoRes.json()
      const statsData = await statsRes.json()
      setAnalyses(analysesData.analyses || [])
      setDemoTrades(demoData.trades || [])
      setStats(statsData)
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
        <button className={`tab ${tab === 'stats' ? 'tab-active' : ''}`} onClick={() => setTab('stats')}>
          آمار Win Rate
        </button>
        <button className={`tab ${tab === 'analyses' ? 'tab-active' : ''}`} onClick={() => setTab('analyses')}>
          سوابق تحلیل‌ها ({analyses.length})
        </button>
        <button className={`tab ${tab === 'demo' ? 'tab-active' : ''}`} onClick={() => setTab('demo')}>
          معاملات دمو ({demoTrades.length})
        </button>
      </div>

      {status === 'loading' && <div className="watchlist-status">در حال بارگذاری…</div>}
      {status === 'error' && <div className="watchlist-status">خطا در دریافت اطلاعات</div>}

      {status === 'ready' && tab === 'stats' && <StatsPanel stats={stats} />}
      {status === 'ready' && tab === 'analyses' && <AnalysesTable rows={analyses} />}
      {status === 'ready' && tab === 'demo' && <DemoTradesTable rows={demoTrades} />}
    </div>
  )
}
