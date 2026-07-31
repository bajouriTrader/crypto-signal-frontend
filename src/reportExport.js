// ---------------------------------------------------------------------------
// توابع مشترکِ خواندن/فرمت‌کردن/خروجی‌گرفتن از معاملات دمو.
// قبلاً این منطق فقط داخل AdminPanel.jsx بود؛ چون دکمه‌ی «دانلود گزارش»
// بالای صفحه‌ی اصلی هم باید بدون باز کردن پنل گزارش، مستقیم فایل مارک‌داون
// رو دانلود کنه، این بخش مشترک به یک فایل جدا منتقل شد تا هم App.jsx و هم
// AdminPanel.jsx از همین یک نسخه استفاده کنن (نه دو کپی جدا که ممکنه با هم
// از هم جدا بیفتن).
// ---------------------------------------------------------------------------
import { authFetch } from './auth'

export function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('fa-IR')
  } catch {
    return iso
  }
}

export function modeLabel(mode) {
  if (mode === 'relaxed') return 'ساده‌گیر'
  if (mode === 'manual') return 'دستی'
  return 'سخت‌گیر'
}

export function statusLabel(status) {
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
export function outcomeGroup(status) {
  if (status === 'open') return 'open'
  if (status?.includes('win')) return 'win'
  if (status?.includes('loss')) return 'loss'
  return 'other'
}

export function computeSummary(rows) {
  const resolved = rows.filter((r) => outcomeGroup(r.status) === 'win' || outcomeGroup(r.status) === 'loss')
  const wins = resolved.filter((r) => outcomeGroup(r.status) === 'win').length
  const losses = resolved.length - wins
  const winRate = resolved.length ? Math.round((wins / resolved.length) * 1000) / 10 : null
  return { total: rows.length, resolved: resolved.length, wins, losses, winRate }
}

// ساخت متن کامل گزارش مارک‌داون از یک لیست معامله + خلاصه‌ی آماری‌اش.
// filters اختیاریه — وقتی از دکمه‌ی «دانلود سریع» بالای صفحه استفاده
// می‌شه، فیلتری اعمال نشده پس این پارامتر خالی می‌مونه.
// V.2.5 (تشخیصی): تفکیک نوع خروج معامله — چون هدف اصلی (`target`) و
// حد ضرر (`stop_loss`) در دیتابیس پویا آپدیت می‌شن (مکانیزم breakeven/
// profit-lock در demo_trade.py، وقتی پیشرفت به ۷۰٪ فاصله‌ی هدف برسه،
// حد ضرر به ۴۰٪ همون فاصله قفل می‌شه)، یک معامله‌ی «برد» می‌تونه یا با
// رسیدن کامل به هدف (full_tp) بسته شده باشه، یا با خوردن به همون حد
// ضررِ جابه‌جاشده (profit_lock — سود کوچیک‌تر از هدف اصلی). این دو حالت
// قبلاً هر دو فقط «برد» نشون داده می‌شدن و قابل‌تفکیک نبودن. exit_type
// از قبل در Supabase ذخیره می‌شه؛ این تغییر فقط نمایشش می‌ده، هیچ منطقی
// عوض نمی‌کنه.
function exitTypeLabel(exitType) {
  if (exitType === 'full_tp') return 'هدف کامل'
  if (exitType === 'profit_lock') return 'قفل سود (زودتر از هدف)'
  if (exitType === 'sl') return 'حد ضرر'
  if (exitType === 'timeout') return 'پایان بازه'
  if (exitType === 'manual_win' || exitType === 'manual_close') return 'دستی'
  return exitType ?? '—'
}

export function buildMarkdownReport(rows, summary, filters = null) {
  const headers = ['زمان', 'نماد', 'جهت', 'حالت', 'ورود', 'هدف', 'حد ضرر', 'وضعیت', 'نوع خروج', 'خروج', 'سود/زیان ($)', 'درصد خالص', 'امتیاز Confluence', 'Probation', 'نسخه']
  let md = `# گزارش معاملات دمو\n\n`
  md += `تاریخ تولید گزارش: ${new Date().toLocaleString('fa-IR')}\n\n`

  if (filters) {
    const activeFilters = []
    if (filters.from) activeFilters.push(`از ${filters.from}`)
    if (filters.to) activeFilters.push(`تا ${filters.to}`)
    if (filters.outcome !== 'all') activeFilters.push(`نتیجه: ${filters.outcome}`)
    if (filters.mode !== 'all') activeFilters.push(`حالت: ${filters.mode}`)
    if (filters.direction !== 'all') activeFilters.push(`جهت: ${filters.direction}`)
    if (filters.symbol) activeFilters.push(`نماد شامل: ${filters.symbol}`)
    if (activeFilters.length) md += `فیلترهای فعال: ${activeFilters.join(' | ')}\n\n`
  }

  md += `**تعداد کل:** ${summary.total} — **بسته‌شده:** ${summary.resolved} — **برد:** ${summary.wins} — **باخت:** ${summary.losses} — **Win Rate:** ${summary.winRate ?? '—'}%\n\n`

  md += `| ${headers.join(' | ')} |\n`
  md += `| ${headers.map(() => '---').join(' | ')} |\n`
  rows.forEach((r) => {
    md += `| ${fmtTime(r.opened_at)} | ${r.symbol} | ${r.direction === 'long' ? 'لانگ' : 'شورت'} | ${modeLabel(r.mode)} | ${r.entry} | ${r.target} | ${r.stop_loss} | ${statusLabel(r.status)} | ${exitTypeLabel(r.exit_type)} | ${r.exit_price ?? '—'} | ${r.realized_pnl ?? '—'} | ${r.realized_pnl_percent ?? '—'} | ${r.confluence_score ?? '—'} | ${r.is_probation_trade ? 'آزمایشی' : 'عادی'} | ${r.app_version ?? '—'} |\n`
  })

  return md
}

export function downloadMarkdownFile(md, filename) {
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function exportToMarkdown(rows, summary, filters) {
  const md = buildMarkdownReport(rows, summary, filters)
  downloadMarkdownFile(md, `demo-trades-${new Date().toISOString().slice(0, 10)}.md`)
}

// کل تاریخچه‌ی معاملات دمو رو از بک‌اند می‌گیره (بدون فیلتر) — همون
// endpointی که پنل گزارش هم برای خروجی کامل استفاده می‌کنه.
export async function fetchDemoTrades(apiBaseUrl) {
  const res = await authFetch(`${apiBaseUrl}/demo-trade/export`)
  if (!res.ok) throw new Error(`خطای سرور (کد ${res.status})`)
  const data = await res.json()
  return data.trades || []
}

// دانلود سریع کل گزارش مارک‌داون بدون نیاز به باز کردن پنل گزارش —
// برای دکمه‌ی «دانلود گزارش» بالای صفحه‌ی اصلی.
export async function quickDownloadFullReport(apiBaseUrl) {
  const rows = await fetchDemoTrades(apiBaseUrl)
  const summary = computeSummary(rows)
  exportToMarkdown(rows, summary, null)
  return summary
}
