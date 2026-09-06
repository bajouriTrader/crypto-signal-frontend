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

function fmtPnl(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(3)}`
}

function StatsPanel({ stats, backendVersion, breakeven, realStats = null }) {
  if (!stats && !realStats) {
    return <div style={{ padding: 20, color: '#9ab' }}>آمار هنوز بارگذاری نشده.</div>
  }

  const ver = realStats?.app_version || realStats?.version || backendVersion || '—'
  const equity = realStats?.equity_usdt
  const available = realStats?.available_usdt
  const daily = realStats?.daily_pnl
  const dailyPnl = daily && typeof daily === 'object' ? Number(daily.pnl || 0) : null
  const dailyDate = daily && typeof daily === 'object' ? daily.date : null
  const sampleN = Number(realStats?.closed ?? 0)
  const wins = Number(realStats?.wins ?? 0)
  const losses = Number(realStats?.losses ?? 0)
  const totalPnl = Number(realStats?.total_pnl_usdt ?? 0)
  const wr = realStats?.win_rate
  const openN = Number(realStats?.open ?? 0)

  return (
    <div className="report-real" style={{ color: '#e0e8f0' }}>
      <div className="breakeven-note" style={{ marginBottom: 14 }}>
        نقطه‌ی سر‌به‌سر تئوری با R:R فعلی: <strong dir="ltr">{breakeven}%</strong>
        {backendVersion ? (
          <span className="breakeven-source-note"> · نسخه سیستم: <b dir="ltr">{backendVersion}</b></span>
        ) : null}
      </div>

      {realStats && (
        <div className="stats-block report-real-card">
          <div className="report-real-head">
            <h3>معاملات واقعی Toobit</h3>
            <span className="report-badge" dir="ltr">{ver}</span>
          </div>
          <p className="report-real-note">
            اعداد زیر از <b>نمونه معاملات ریل ثبت‌شده در سرور</b> است (نه واریز/برداشت کیف پول).
            برای دیدن موجودی لحظه‌ای از صفحه اصلی / وضعیت استفاده کنید.
          </p>

          <div className="stats-summary-grid report-kpi-grid">
            <div className="stats-card">
              <span className="stats-card-label">PnL نمونه ریل</span>
              <span className="stats-card-value" dir="ltr" style={{ color: totalPnl >= 0 ? '#2DD4A7' : '#FF5C72' }}>
                {fmtPnl(totalPnl)} $
              </span>
              <span className="stats-card-sub">جمع تقریبی روی {sampleN} معامله بسته‌شده</span>
            </div>
            <div className="stats-card">
              <span className="stats-card-label">Win Rate ریل</span>
              <span className="stats-card-value" dir="ltr">
                {wr != null ? `${wr}%` : '—'}
              </span>
              <span className="stats-card-sub">برد {wins} · باخت {losses}</span>
            </div>
            <div className="stats-card">
              <span className="stats-card-label">بسته / باز</span>
              <span className="stats-card-value" dir="ltr">{sampleN} / {openN}</span>
              <span className="stats-card-sub">نمونه گزارش · پوزیشن زنده</span>
            </div>
            <div className="stats-card">
              <span className="stats-card-label">PnL امروز</span>
              <span
                className="stats-card-value"
                dir="ltr"
                style={{ color: (dailyPnl ?? 0) >= 0 ? '#2DD4A7' : '#FF5C72' }}
              >
                {dailyPnl == null ? '—' : `${fmtPnl(dailyPnl)} $`}
              </span>
              <span className="stats-card-sub">{dailyDate ? `تاریخ ${dailyDate}` : 'از /real-trade/status'}</span>
            </div>
            <div className="stats-card">
              <span className="stats-card-label">Equity فعلی</span>
              <span className="stats-card-value" dir="ltr">
                {equity != null ? `${Number(equity).toFixed(2)} $` : '—'}
              </span>
              <span className="stats-card-sub">
                آزاد: {available != null ? `${Number(available).toFixed(2)} $` : '—'}
              </span>
            </div>
          </div>

          {Array.isArray(realStats.recent) && realStats.recent.length > 0 && (
            <div className="admin-table-wrap report-table-wrap">
              <table className="admin-table report-table">
                <thead>
                  <tr>
                    <th>نماد</th>
                    <th>جهت</th>
                    <th>ورود</th>
                    <th>خروج</th>
                    <th>PnL</th>
                    <th>دلیل خروج</th>
                    <th>نسخه</th>
                  </tr>
                </thead>
                <tbody>
                  {realStats.recent.slice(0, 20).map((r, i) => {
                    const pnl = Number(r.approx_pnl)
                    const pnlOk = Number.isFinite(pnl)
                    return (
                      <tr key={`${r.symbol}-${r.exit_reason || ''}-${i}`}>
                        <td className="td-symbol">{r.symbol}</td>
                        <td>{r.direction === 'long' ? 'لانگ' : r.direction === 'short' ? 'شورت' : (r.direction || '—')}</td>
                        <td dir="ltr">{r.entry != null ? r.entry : '—'}</td>
                        <td dir="ltr">{r.exit_price != null ? r.exit_price : '—'}</td>
                        <td dir="ltr" className={pnlOk ? (pnl >= 0 ? 'pnl-pos' : 'pnl-neg') : ''}>
                          {pnlOk ? fmtPnl(pnl) : '—'}
                        </td>
                        <td className="td-reason">{r.exit_reason || '—'}</td>
                        <td dir="ltr" className="td-ver">{r.app_version || ver}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          <ul className="report-hints">
            <li>ستون «نسخه» = نسخه بک‌اند هنگام بستن معامله (اگر ثبت شده باشد).</li>
            <li>«PnL نمونه ریل» مجموع ردیف‌های همین جدول/نمونه است؛ معادل موجودی واریزی حساب نیست.</li>
            <li>برای قضاوت نسخه جدید، به معاملات با نسخه فعلی و PnL امروز نگاه کنید.</li>
          </ul>
          {realStats.note && <p className="report-source-note">{realStats.note}</p>}
        </div>
      )}
    </div>
  )
}

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
  const [realStats, setRealStats] = useState(null)

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
      // سبک: آمار ریل + وضعیت زنده (بدون دمو سنگین)
      const [realRes, statusRes] = await Promise.all([
        authFetch(`${API_BASE_URL}/real-trade/stats`).catch(() => null),
        authFetch(`${API_BASE_URL}/real-trade/status`).catch(() => null),
      ])
      let realData = null
      let statusData = null
      try {
        if (realRes && realRes.ok) realData = await realRes.json()
      } catch (_) {}
      try {
        if (statusRes && statusRes.ok) statusData = await statusRes.json()
      } catch (_) {}

      if (!realData && statusData) {
        const recent = Array.isArray(statusData.recent_closed) ? statusData.recent_closed : []
        let wins = 0
        let losses = 0
        let pnl = 0
        for (const r of recent) {
          const p = Number(r.approx_pnl || 0)
          pnl += p
          if (p > 0) wins += 1
          else if (p < 0) losses += 1
        }
        const n = wins + losses
        realData = {
          win_rate: n ? Math.round((wins / n) * 1000) / 10 : null,
          closed: n,
          open: statusData.open_positions || 0,
          wins,
          losses,
          total_pnl_usdt: pnl,
          recent,
          note: 'ساخته‌شده از /real-trade/status',
          version: statusData.app_version,
          app_version: statusData.app_version,
        }
      }

      if (realData && statusData) {
        realData = {
          ...realData,
          app_version: realData.app_version || statusData.app_version || realData.version,
          equity_usdt: statusData.equity_usdt,
          available_usdt: statusData.available_usdt,
          daily_pnl: statusData.daily_pnl,
          open: statusData.open_positions ?? realData.open,
        }
        if ((!realData.recent || !realData.recent.length) && Array.isArray(statusData.recent_closed)) {
          realData.recent = statusData.recent_closed
        }
      }

      setAnalyses([])
      setDemoTrades([])
      setStats(realData ? { win_rate: realData.win_rate } : null)
      setRealStats(realData)
      setStatus(realData ? 'ready' : 'error')
    } catch (e) {
      console.error('admin loadData', e)
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
    <div className="admin-panel" style={{ minHeight: '100vh', color: '#e0e8f0', padding: '12px 16px' }}>
      <div className="admin-head">
        <div>
          <h2 style={{ color: '#e8f0ff' }}>پنل گزارش</h2>
          <p className="admin-head-subtitle">
            خلاصه معاملات واقعی Toobit و نسخه سیستم —{' '}
            {backendVersion ? (
              <span dir="ltr">نسخه فعلی: {backendVersion}</span>
            ) : (
              'در حال خواندن نسخه…'
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
        <button className="tab tab-active" type="button">
          📊 معاملات واقعی / خلاصه
        </button>
      </div>

      {status === 'loading' && <div className="watchlist-status" style={{padding:20,color:'#9ab'}}>در حال بارگذاری گزارش…</div>}
      {status === 'error' && <div className="watchlist-status" style={{padding:20,color:'#FF5C72'}}>خطا در دریافت اطلاعات — دکمه بروزرسانی را بزنید</div>}

      {status === 'ready' && (
        <StatsPanel stats={stats} backendVersion={backendVersion} breakeven={breakevenWinRate} realStats={realStats} />
      )}
    </div>
  )
}
