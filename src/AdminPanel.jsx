import { authFetch, getToken } from './auth'
import { useEffect, useMemo, useState } from 'react'
import * as XLSX from 'xlsx'
// V.2.4: fmtTime/modeLabel/statusLabel/outcomeGroup/computeSummary و
// exportToMarkdown قبلاً اینجا و هم در App.jsx (برای دانلود سریع) به‌صورت
// تکراری تعریف شده بودن. حالا هر دو فایل از همون یک نسخه‌ی مشترک در
// reportExport.js استفاده می‌کنن.
import {
  fmtTime,
  modeLabel,
  statusLabel,
  outcomeGroup,
  computeSummary,
  exportToMarkdown,
} from './reportExport'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

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
            <th>Probation</th>
            <th>نسخه</th>
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
              <td>{r.is_probation_trade ? '🧪 آزمایشی' : '—'}</td>
              <td dir="ltr">{r.app_version ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// V.2.4: نقطه‌ی سربه‌سر دیگه یک عدد hardcode جدا نیست — این دقیقاً همون
// چیزیه که باعث شد بعد از rollback از V.2.2 به V.2.3، این خط برای مدتی
// مقدار غلط (متعلق به R:R قدیمی V.2.2) نشون بده، چون کسی یادش نبود این
// ثابت رو هم‌زمان با تغییر R:R واقعی سرور آپدیت کنه. الان مقدار از
// GET /version (که خودش از SL_ATR_MULTIPLIER/TP_ATR_MULTIPLIER واقعی
// indicators.py می‌سازدش) خونده می‌شه — همیشه با نسخه‌ی در حال اجرا
// هماهنگه. تا وقتی جواب بک‌اند نرسیده، یک مقدار پیش‌فرض معقول (بر مبنای
// R:R فعلی V.2.3: SL=1.1×ATR / TP=1.8×ATR → ۱/(۱+۱.۸/۱.۱)=۳۷.۹٪) موقتاً
// نمایش داده می‌شه.
const DEFAULT_BREAKEVEN_WIN_RATE = 37.9

function wrIndicator(winRate, breakeven) {
  if (winRate === null || winRate === undefined) return { cls: '', label: '' }
  if (winRate >= breakeven + 5) return { cls: 'wr-above', label: '▲' }
  if (winRate < breakeven) return { cls: 'wr-below', label: '▼' }
  return { cls: 'wr-near', label: '●' }
}

function WinRateCell({ winRate, breakeven }) {
  if (winRate === null || winRate === undefined) return <span>—</span>
  const { cls, label } = wrIndicator(winRate, breakeven)
  return (
    <span className={`wr-cell ${cls}`}>
      {label} {winRate}%
    </span>
  )
}

// یک بخش آماری با عنوان + توضیح اختیاری، برای این‌که تفکیک‌های مختلف
// (نسخه/probation/حالت/جهت/ارز) به‌جای پشت سر هم افتادن روی صفحه، هرکدوم
// یک بلوک بصری جدا و مشخص داشته باشن
function StatsBlock({ title, note, children }) {
  return (
    <div className="stats-block">
      <h3 className="stats-section-title">{title}</h3>
      {note && <p className="stats-block-note">{note}</p>}
      {children}
    </div>
  )
}

function StatsPanel({ stats, backendVersion, breakeven }) {
  if (!stats) return null

  return (
    <div>
      <div className="breakeven-note">
        نقطه‌ی سر‌به‌سر با نسبت ریسک/ریوارد فعلی سیستم: <strong dir="ltr">{breakeven}%</strong> —
        زیر این خط یعنی حتی با وین‌ریت مثبت، در مجموع ضرر می‌ده.
        {backendVersion && (
          <span className="breakeven-source-note">
            {' '}
            (بر مبنای R:R نسخه‌ی فعلی «{backendVersion}» — از GET /version خونده می‌شه، نه از میانگین معاملات گذشته)
          </span>
        )}
      </div>

      <div className="stats-summary-grid">
        <div className="stats-card">
          <span className="stats-card-label">Win Rate کلی (همه‌ی نسخه‌ها با هم)</span>
          <span className="stats-card-value" dir="ltr">
            <WinRateCell winRate={stats.win_rate} breakeven={breakeven} />
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

      <StatsBlock
        title="تفکیک بر اساس نسخه‌ی کد (لحظه‌ی باز شدن معامله)"
        note="مهم‌ترین جدول این صفحه: چون گیت‌ها/آستانه‌ها بین نسخه‌ها عوض شده، Win Rate کلی بالا میانگین چند رژیم متفاوته و به‌تنهایی گمراه‌کننده‌ست — برای قضاوت درباره‌ی وضعیت فعلی سیستم فقط به ردیف نسخه‌ی فعلی نگاه کن."
      >
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>نسخه</th>
                <th>تعداد</th>
                <th>برد</th>
                <th>Win Rate</th>
              </tr>
            </thead>
            <tbody>
              {(stats.by_version || []).map((v) => (
                <tr key={v.version} className={v.version === backendVersion ? 'stats-row-current' : ''}>
                  <td>
                    {v.version}
                    {v.version === backendVersion && <span className="current-version-badge">فعلی</span>}
                  </td>
                  <td dir="ltr">{v.total}</td>
                  <td dir="ltr">{v.wins}</td>
                  <td dir="ltr"><WinRateCell winRate={v.win_rate} breakeven={breakeven} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </StatsBlock>

      <StatsBlock title="تفکیک بر اساس probation (V.1.5)">
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>نوع</th>
                <th>تعداد</th>
                <th>برد</th>
                <th>Win Rate</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats.by_probation || {}).map(([k, v]) => (
                <tr key={k}>
                  <td>{k === 'probation' ? 'تلاش آزمایشی probation' : 'عادی'}</td>
                  <td dir="ltr">{v.total}</td>
                  <td dir="ltr">{v.wins}</td>
                  <td dir="ltr"><WinRateCell winRate={v.win_rate} breakeven={breakeven} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </StatsBlock>

      <StatsBlock title="تفکیک بر اساس حالت (سخت‌گیر / ساده‌گیر)">
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
                  <td dir="ltr"><WinRateCell winRate={v.win_rate} breakeven={breakeven} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </StatsBlock>

      <StatsBlock title="تفکیک بر اساس جهت">
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
                  <td dir="ltr"><WinRateCell winRate={v.win_rate} breakeven={breakeven} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </StatsBlock>

      <StatsBlock title="تفکیک بر اساس ارز">
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
                  <td dir="ltr"><WinRateCell winRate={s.win_rate} breakeven={breakeven} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </StatsBlock>
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
  probation: 'all', // all | probation | normal — V.1.5
}

function applyFilters(rows, f) {
  return rows.filter((r) => {
    if (f.from && new Date(r.opened_at) < new Date(f.from)) return false
    if (f.to && new Date(r.opened_at) > new Date(`${f.to}T23:59:59`)) return false
    if (f.outcome !== 'all' && outcomeGroup(r.status) !== f.outcome) return false
    if (f.mode !== 'all' && r.mode !== f.mode) return false
    if (f.direction !== 'all' && r.direction !== f.direction) return false
    if (f.symbol && !r.symbol?.toUpperCase().includes(f.symbol.toUpperCase())) return false
    if (f.probation === 'probation' && !r.is_probation_trade) return false
    if (f.probation === 'normal' && r.is_probation_trade) return false
    return true
  })
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
    // V.1.1: امتیاز confluence برای این‌که بشه واقعاً بررسی کرد آیا گیت
    // MIN_CONFLUENCE_SCORE (فاز ۱) دارد اثر واقعی می‌گذارد یا نه
    'امتیاز Confluence': r.confluence_score ?? '',
    // V.1.5: آیا این معامله از طریق تلاش آزمایشی probation باز شده؟
    'Probation': r.is_probation_trade ? 'آزمایشی' : 'عادی',
    'نسخه': r.app_version ?? '',
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
          <span>Probation</span>
          <select value={filters.probation} onChange={update('probation')}>
            <option value="all">همه</option>
            <option value="probation">فقط آزمایشی</option>
            <option value="normal">فقط عادی</option>
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
  // V.2.4: اگه از لینک میان‌بر «خروجی گزارش» (#admin/demo) اومده باشیم،
  // مستقیم تب گزارش‌ها/دمو باز بشه، نه تب پیش‌فرض آمار.
  const [tab, setTab] = useState(window.location.hash.includes('demo') ? 'demo' : 'stats') // 'stats' | 'analyses' | 'demo'
  const [analyses, setAnalyses] = useState([])
  const [demoTrades, setDemoTrades] = useState([])
  const [stats, setStats] = useState(null)
  const [status, setStatus] = useState('idle')
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  // V.2.4: به‌جای نمایش کل تاریخچه (که می‌تونه هزاران ردیف بشه) توی یک
  // صفحه، جدول ۱۰۰ تا ۱۰۰ نمایش داده می‌شه. فیلتر/خروجی همچنان روی کل
  // داده‌ی فیلترشده کار می‌کنه — فقط نمایش جدول صفحه‌بندی شده.
  const PAGE_SIZE = 100
  const [page, setPage] = useState(0)
  // V.2.4: نسخه‌ی در حال اجرای فعلی بک‌اند، برای هایلایت‌کردن ردیف
  // متناظرش در جدول «تفکیک بر اساس نسخه‌ی کد» — بدون این، کاربر باید
  // دستی APP_VERSION رو با یکی از ردیف‌های جدول تطبیق بده
  const [backendVersion, setBackendVersion] = useState(null)
  // نقطه‌ی سربه‌سر واقعی، مستقیم از R:R نسخه‌ی در حال اجرا (نه از
  // میانگین معاملات گذشته) — تا وقتی جواب بک‌اند نرسیده مقدار پیش‌فرض
  // نمایش داده می‌شه
  const [breakevenWinRate, setBreakevenWinRate] = useState(DEFAULT_BREAKEVEN_WIN_RATE)

  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE_URL}/version`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data) return
        if (data.version) setBackendVersion(data.version)
        if (typeof data.breakeven_win_rate === 'number') setBreakevenWinRate(data.breakeven_win_rate)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const loadData = async () => {
    setStatus('loading')
    try {
      // V.2.9: سبک‌سازی — دیگر کل تاریخچه را در لود اولیه نمی‌کشیم.
      // فقط آمار تجمیعی + ۳۰۰ معامله‌ی اخیر. دانلود کامل فقط با دکمه Export.
      const [analysesRes, demoRes, statsRes] = await Promise.all([
        authFetch(`${API_BASE_URL}/history?limit=20`),
        authFetch(`${API_BASE_URL}/demo-trade/history?limit=300&offset=0`),
        authFetch(`${API_BASE_URL}/demo-trade/stats`),
      ])
      const analysesData = await analysesRes.json()
      const demoData = await demoRes.json()
      const statsData = await statsRes.json()
      setAnalyses(analysesData.analyses || [])
      setDemoTrades(demoData.trades || demoData || [])
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

  const pageCount = Math.max(1, Math.ceil(filteredDemoTrades.length / PAGE_SIZE))
  // اگه فیلتر عوض شد و صفحه‌ی فعلی دیگه معتبر نبود (مثلاً از صفحه‌ی ۵
  // به یه فیلتر با فقط ۲ صفحه اومدیم)، برگرد صفحه‌ی اول
  useEffect(() => {
    setPage(0)
  }, [filters])
  const pagedDemoTrades = useMemo(
    () => filteredDemoTrades.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [filteredDemoTrades, page]
  )

  if (!unlocked) {
    return (
      <div className="admin-gate">
        <h2>نیاز به ورود</h2>
        <p style={{ color: 'var(--text-muted)', fontSize: 13.5, marginBottom: 16 }}>
          برای دیدن پنل گزارش، اول باید از صفحه‌ی اصلی با رمز سایت وارد بشی.
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
        <div>
          <h2>پنل گزارش</h2>
          <p className="admin-head-subtitle">
            آمار Win Rate، سوابق تحلیل‌ها و تاریخچه‌ی معاملات دمو —{' '}
            {backendVersion ? (
              <span dir="ltr">نسخه‌ی فعلی سیستم: {backendVersion}</span>
            ) : (
              'در حال بررسی نسخه‌ی فعلی سیستم…'
            )}
          </p>
        </div>
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
          📊 آمار Win Rate
        </button>
        <button className={`tab ${tab === 'analyses' ? 'tab-active' : ''}`} onClick={() => setTab('analyses')}>
          🗂 سوابق تحلیل‌ها ({analyses.length})
        </button>
        <button className={`tab ${tab === 'demo' ? 'tab-active' : ''}`} onClick={() => setTab('demo')}>
          💹 معاملات دمو ({demoTrades.length})
        </button>
      </div>

      {status === 'loading' && <div className="watchlist-status">در حال بارگذاری…</div>}
      {status === 'error' && <div className="watchlist-status">خطا در دریافت اطلاعات</div>}

      {status === 'ready' && tab === 'stats' && (
        <StatsPanel stats={stats} backendVersion={backendVersion} breakeven={breakevenWinRate} />
      )}
      {status === 'ready' && tab === 'analyses' && <AnalysesTable rows={analyses} />}
      {status === 'ready' && tab === 'demo' && (
        <>
          <FilterBar
            filters={filters}
            setFilters={setFilters}
            summary={filteredSummary}
            onExportExcel={() => exportToExcel(filteredDemoTrades, filteredSummary)}
            onExportMarkdown={async () => {
              // V.2.9: فقط هنگام دانلود، کل داده را بکش
              try {
                const res = await authFetch(`${API_BASE_URL}/demo-trade/export`)
                const data = await res.json()
                const all = data.trades || []
                const filtered = applyFilters(all, filters)
                exportToMarkdown(filtered, computeSummary(filtered), filters)
              } catch (e) {
                exportToMarkdown(filteredDemoTrades, filteredSummary, filters)
              }
            }}
          />
          <div className="report-pagination">
            <button
              className="btn-mini"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              ← قبلی
            </button>
            <span dir="ltr">
              صفحه {page + 1} از {pageCount} — نمایش {pagedDemoTrades.length} از {filteredDemoTrades.length}
            </span>
            <button
              className="btn-mini"
              disabled={page >= pageCount - 1}
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            >
              بعدی →
            </button>
          </div>
          <DemoTradesTable rows={pagedDemoTrades} />
        </>
      )}
    </div>
  )
}
