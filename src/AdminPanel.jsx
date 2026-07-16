import { authFetch, getToken } from './auth'
import { useEffect, useMemo, useState } from 'react'
import * as XLSX from 'xlsx'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('fa-IR')
  } catch {
    return iso
  }
}

function modeLabel(mode) {
  if (mode === 'relaxed') return 'ساده‌گیر'
  if (mode === 'manual') return 'دستی'
  return 'سخت‌گیر'
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

// گروه‌بندی وضعیت‌های خام برای فیلتر «نتیجه»
function outcomeGroup(status) {
  if (status === 'open') return 'open'
  if (status?.includes('win')) return 'win'
  if (status?.includes('loss')) return 'loss'
  return 'other'
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
            <th>حالت</th>
            <th>مبلغ</th>
            <th>ورود</th>
            <th>هدف</th>
            <th>حد ضرر</th>
            <th>وضعیت</th>
            <th>خروج</th>
            <th>سود/زیان ($)</th>
            <th>درصد خالص (بدون اهرم)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.trade_id}>
              <td>{fmtTime(r.opened_at)}</td>
              <td>{r.symbol}</td>
              <td>{r.direction === 'long' ? 'لانگ' : 'شورت'}</td>
              <td>{modeLabel(r.mode)}</td>
              <td dir="ltr">{r.margin_usdt ?? 10}$ / {r.leverage}x</td>
              <td dir="ltr">{r.entry}</td>
              <td dir="ltr">{r.target}</td>
              <td dir="ltr">{r.stop_loss}</td>
              <td>{statusLabel(r.status)}</td>
              <td dir="ltr">{r.exit_price ?? '—'}</td>
              <td dir="ltr">{r.realized_pnl !== null && r.realized_pnl !== undefined ? `${r.realized_pnl >= 0 ? '+' : ''}${r.realized_pnl}$` : '—'}</td>
              <td dir="ltr">{r.realized_pnl_percent !== null && r.realized_pnl_percent !== undefined ? `${r.realized_pnl_percent >= 0 ? '+' : ''}${r.realized_pnl_percent}%` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// نقطه‌ی سر‌به‌سر بر اساس نسبت ریسک/ریوارد فعلی سیستم (SL=1.0×ATR / TP=1.6×ATR)
// یعنی حداقل ۳۸.۵٪ برد لازمه که استراتژی سودده باشه (نه فقط بی‌ضرر)
const BREAKEVEN_WIN_RATE = 38.5

function wrIndicator(winRate) {
  if (winRate === null || winRate === undefined) return { cls: '', label: '' }
  if (winRate >= BREAKEVEN_WIN_RATE + 5) return { cls: 'wr-above', label: '▲' }
  if (winRate < BREAKEVEN_WIN_RATE) return { cls: 'wr-below', label: '▼' }
  return { cls: 'wr-near', label: '●' }
}

function WinRateCell({ winRate }) {
  if (winRate === null || winRate === undefined) return <span>—</span>
  const { cls, label } = wrIndicator(winRate)
  return (
    <span className={`wr-cell ${cls}`}>
      {label} {winRate}%
    </span>
  )
}

function StatsPanel({ stats }) {
  if (!stats) return null

  return (
    <div>
      <div className="breakeven-note">
        نقطه‌ی سر‌به‌سر با نسبت ریسک/ریوارد فعلی سیستم: <strong dir="ltr">{BREAKEVEN_WIN_RATE}%</strong> —
        زیر این خط یعنی حتی با وین‌ریت مثبت، در مجموع ضرر می‌ده.
      </div>

      <div className="stats-summary-grid">
        <div className="stats-card">
          <span className="stats-card-label">Win Rate کلی</span>
          <span className="stats-card-value" dir="ltr">
            <WinRateCell winRate={stats.win_rate} />
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
                <td>{modeLabel(m)}</td>
                <td dir="ltr">{v.total}</td>
                <td dir="ltr">{v.wins}</td>
                <td dir="ltr"><WinRateCell winRate={v.win_rate} /></td>
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
                <td dir="ltr"><WinRateCell winRate={v.win_rate} /></td>
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
                <td dir="ltr"><WinRateCell winRate={s.win_rate} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// فیلتر + خروجی گزارش (Excel / Markdown)
// ---------------------------------------------------------------------------

const DEFAULT_FILTERS = {
  from: '',
  to: '',
  outcome: 'all', // all | win | loss | open
  mode: 'all', // all | strict | relaxed
  direction: 'all', // all | long | short
  symbol: '',
}

function applyFilters(rows, f) {
  return rows.filter((r) => {
    if (f.from && new Date(r.opened_at) < new Date(f.from)) return false
    if (f.to && new Date(r.opened_at) > new Date(`${f.to}T23:59:59`)) return false
    if (f.outcome !== 'all' && outcomeGroup(r.status) !== f.outcome) return false
    if (f.mode !== 'all' && r.mode !== f.mode) return false
    if (f.direction !== 'all' && r.direction !== f.direction) return false
    if (f.symbol && !r.symbol?.toUpperCase().includes(f.symbol.toUpperCase())) return false
    return true
  })
}

function computeSummary(rows) {
  const resolved = rows.filter((r) => outcomeGroup(r.status) === 'win' || outcomeGroup(r.status) === 'loss')
  const wins = resolved.filter((r) => outcomeGroup(r.status) === 'win').length
  const losses = resolved.length - wins
  const winRate = resolved.length ? Math.round((wins / resolved.length) * 1000) / 10 : null
  return { total: rows.length, resolved: resolved.length, wins, losses, winRate }
}

function exportToExcel(rows, summary) {
  const data = rows.map((r) => ({
    'زمان باز شدن': fmtTime(r.opened_at),
    'زمان بسته شدن': fmtTime(r.closed_at),
    'نماد': r.symbol,
    'جهت': r.direction === 'long' ? 'لانگ' : 'شورت',
    'حالت': modeLabel(r.mode),
    'مبلغ (USDT)': r.margin_usdt ?? 10,
    'اهرم': r.leverage,
    'ورود': r.entry,
    'هدف': r.target,
    'حد ضرر': r.stop_loss,
    'وضعیت': statusLabel(r.status),
    'قیمت خروج': r.exit_price ?? '',
    'سود/زیان ($)': r.realized_pnl ?? '',
    'درصد خالص (بدون اهرم)': r.realized_pnl_percent ?? '',
  }))

  const ws = XLSX.utils.json_to_sheet(data)
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'معاملات دمو')

  const summarySheet = XLSX.utils.json_to_sheet([
    { 'شاخص': 'تعداد کل', 'مقدار': summary.total },
    { 'شاخص': 'بسته‌شده', 'مقدار': summary.resolved },
    { 'شاخص': 'برد', 'مقدار': summary.wins },
    { 'شاخص': 'باخت', 'مقدار': summary.losses },
    { 'شاخص': 'Win Rate (%)', 'مقدار': summary.winRate ?? '—' },
  ])
  XLSX.utils.book_append_sheet(wb, summarySheet, 'خلاصه')

  XLSX.writeFile(wb, `demo-trades-${new Date().toISOString().slice(0, 10)}.xlsx`)
}

function exportToMarkdown(rows, summary, filters) {
  const headers = ['زمان', 'نماد', 'جهت', 'حالت', 'ورود', 'هدف', 'حد ضرر', 'وضعیت', 'خروج', 'سود/زیان ($)', 'درصد خالص']
  let md = `# گزارش معاملات دمو\n\n`
  md += `تاریخ تولید گزارش: ${new Date().toLocaleString('fa-IR')}\n\n`

  const activeFilters = []
  if (filters.from) activeFilters.push(`از ${filters.from}`)
  if (filters.to) activeFilters.push(`تا ${filters.to}`)
  if (filters.outcome !== 'all') activeFilters.push(`نتیجه: ${filters.outcome}`)
  if (filters.mode !== 'all') activeFilters.push(`حالت: ${filters.mode}`)
  if (filters.direction !== 'all') activeFilters.push(`جهت: ${filters.direction}`)
  if (filters.symbol) activeFilters.push(`نماد شامل: ${filters.symbol}`)
  if (activeFilters.length) md += `فیلترهای فعال: ${activeFilters.join(' | ')}\n\n`

  md += `**تعداد کل:** ${summary.total} — **بسته‌شده:** ${summary.resolved} — **برد:** ${summary.wins} — **باخت:** ${summary.losses} — **Win Rate:** ${summary.winRate ?? '—'}%\n\n`

  md += `| ${headers.join(' | ')} |\n`
  md += `| ${headers.map(() => '---').join(' | ')} |\n`
  rows.forEach((r) => {
    md += `| ${fmtTime(r.opened_at)} | ${r.symbol} | ${r.direction === 'long' ? 'لانگ' : 'شورت'} | ${modeLabel(r.mode)} | ${r.entry} | ${r.target} | ${r.stop_loss} | ${statusLabel(r.status)} | ${r.exit_price ?? '—'} | ${r.realized_pnl ?? '—'} | ${r.realized_pnl_percent ?? '—'} |\n`
  })

  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `demo-trades-${new Date().toISOString().slice(0, 10)}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function FilterBar({ filters, setFilters, summary, onExportExcel, onExportMarkdown }) {
  const update = (key) => (e) => setFilters((f) => ({ ...f, [key]: e.target.value }))

  return (
    <div className="report-filter-bar">
      <div className="report-filter-row">
        <label className="report-filter-field">
          <span>از تاریخ</span>
          <input type="date" value={filters.from} onChange={update('from')} />
        </label>
        <label className="report-filter-field">
          <span>تا تاریخ</span>
          <input type="date" value={filters.to} onChange={update('to')} />
        </label>
        <label className="report-filter-field">
          <span>نتیجه</span>
          <select value={filters.outcome} onChange={update('outcome')}>
            <option value="all">همه</option>
            <option value="win">فقط برد</option>
            <option value="loss">فقط باخت</option>
            <option value="open">هنوز باز</option>
          </select>
        </label>
        <label className="report-filter-field">
          <span>حالت</span>
          <select value={filters.mode} onChange={update('mode')}>
            <option value="all">همه</option>
            <option value="strict">سخت‌گیر</option>
            <option value="relaxed">ساده‌گیر</option>
            <option value="manual">دستی</option>
          </select>
        </label>
        <label className="report-filter-field">
          <span>جهت</span>
          <select value={filters.direction} onChange={update('direction')}>
            <option value="all">همه</option>
            <option value="long">لانگ</option>
            <option value="short">شورت</option>
          </select>
        </label>
        <label className="report-filter-field">
          <span>نماد</span>
          <input
            type="text"
            placeholder="مثلاً BTC"
            dir="ltr"
            value={filters.symbol}
            onChange={update('symbol')}
          />
        </label>
        <button
          className="btn-mini"
          onClick={() => setFilters(DEFAULT_FILTERS)}
        >
          پاک کردن فیلترها
        </button>
      </div>

      <div className="report-filter-summary">
        <span>
          {summary.total} معامله در فیلتر فعلی — {summary.resolved} بسته‌شده — Win Rate:{' '}
          <strong dir="ltr">{summary.winRate ?? '—'}%</strong>
        </span>
        <div className="report-export-buttons">
          <button className="btn-mini" disabled={!summary.total} onClick={onExportExcel}>
            خروجی Excel
          </button>
          <button className="btn-mini" disabled={!summary.total} onClick={onExportMarkdown}>
            خروجی Markdown
          </button>
        </div>
      </div>
    </div>
  )
}

export default function AdminPanel() {
  // پنل ادمین دیگه رمز جدای خودش رو نداره — همون ورود امن سراسری سایت
  // (SITE_PASSWORD واقعی که سمت سرور چک می‌شه) کافیه. اگه کاربر از قبل
  // وارد شده (توکن معتبر داره)، مستقیم پنل رو می‌بینه.
  const [unlocked] = useState(!!getToken())
  const [tab, setTab] = useState('stats') // 'stats' | 'analyses' | 'demo'
  const [analyses, setAnalyses] = useState([])
  const [demoTrades, setDemoTrades] = useState([])
  const [stats, setStats] = useState(null)
  const [status, setStatus] = useState('idle')
  const [filters, setFilters] = useState(DEFAULT_FILTERS)

  const loadData = async () => {
    setStatus('loading')
    try {
      const [analysesRes, demoRes, statsRes] = await Promise.all([
        authFetch(`${API_BASE_URL}/history?limit=30`),
        // limit بالاتر تا فیلتر بازه‌ی زمانی و خروجی گزارش روی دیتای کامل‌تری کار کنه
        authFetch(`${API_BASE_URL}/demo-trade/history?limit=1000`),
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

  const filteredDemoTrades = useMemo(
    () => applyFilters(demoTrades, filters),
    [demoTrades, filters]
  )
  const filteredSummary = useMemo(
    () => computeSummary(filteredDemoTrades),
    [filteredDemoTrades]
  )

  if (!unlocked) {
    return (
      <div className="admin-gate">
        <h2>نیاز به ورود</h2>
        <p style={{ color: 'var(--text-muted)', fontSize: 13.5, marginBottom: 16 }}>
          برای دیدن پنل ادمین، اول باید از صفحه‌ی اصلی با رمز سایت وارد بشی.
        </p>
        <a
          className="admin-back-link"
          href="./"
          onClick={(e) => {
            e.preventDefault()
            window.location.hash = ''
            window.location.href = './'
          }}
        >
          رفتن به صفحه‌ی ورود
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
      {status === 'ready' && tab === 'demo' && (
        <>
          <FilterBar
            filters={filters}
            setFilters={setFilters}
            summary={filteredSummary}
            onExportExcel={() => exportToExcel(filteredDemoTrades, filteredSummary)}
            onExportMarkdown={() => exportToMarkdown(filteredDemoTrades, filteredSummary, filters)}
          />
          <DemoTradesTable rows={filteredDemoTrades} />
        </>
      )}
    </div>
  )
}
