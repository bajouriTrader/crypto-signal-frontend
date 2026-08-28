علت صفحه سیاه پنل گزارش:
  داخل StatsPanel از متغیر realStats استفاده می‌شد ولی در پارامترهای تابع نبود
  → ReferenceError در مرورگر → کل صفحه #admin سفید/سیاه

فایل: AdminPanel.jsx را در src/ جایگزین کن → push → صبر برای Deploy سبز → Ctrl+Shift+R روی #admin

--- SQL اختیاری در Supabase (جدول جدا برای ریل) ---
create table if not exists real_trades (
  id bigserial primary key,
  trade_id text unique,
  symbol text,
  direction text,
  entry double precision,
  target double precision,
  stop_loss double precision,
  leverage int,
  margin_usdt double precision,
  quantity text,
  status text,
  opened_at timestamptz,
  closed_at timestamptz,
  confluence_score double precision,
  app_version text,
  exit_reason text,
  exit_price double precision,
  approx_pnl double precision,
  approx_pnl_pct double precision
);

ستون app_version روی demo_trades را اگر قبلاً زدی کافی است؛ آن برای دموست نه ریل.
