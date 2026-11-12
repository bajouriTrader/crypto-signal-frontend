"""
V.2.10.95: BE≠hard-SL guards · soft-reject cooldown 90s (CHOP/ADX/anti-noise)
V.2.10.96: min_adx_1h_for_entry default 20 (post-CHOP recovery; CHOP/m5/CI untouched)
V.2.10.97: multi-strategy skeleton — range_scalp path for BTC WEAK/CHOP (half size, tighter SL, strategy_id)
لایه معامله واقعی روی Toobit با محدودیت‌های سخت مدیریت سرمایه + مدیریت خودکار خروج.

V.2.10.66 — strong ADX bypass BTC WEAK pause
V.2.10.65 — bypass BTC-ADX وقتی ADX نماد ≥30
V.2.10.64 — ADX UI در status-viewer
V.2.10.63 — min ADX entry gate (ضد TREND_OK قلابی)
V.2.10.86 — global entry lock session-only (never survive Space restart) (no pause after Space restart) + watchlist readiness obs
V.2.10.84 — cluster SL pause + weak-BTC same-dir cap + no 2nd long while underwater
V.2.10.62 — attribution fix (stale + soft close version stamp)
V.2.10.61 — stale_profit net floor 0.15
V.2.10.60 — Stale session exit
V.2.10.59 — Post-profit cooldown + soft hysteresis (ضد تعقیب بعد از برد)
- بعد از float/TP/profit_lock: کول‌داون طولانی‌تر روی symbol (پیش‌فرض ۳۶۰۰ث)
- جلوگیری از ورود دوباره سریع مثل OP دوم (برد → ۱۸دقیقه بعد → SL)
- هیسترزیس نرم اختیاری: در پنجرهٔ کوتاه بعد از برد، اگر ER/ADX ضعیف‌تر از baseline برد باشد رد
V.2.10.58 — Symbol WR probation (direction-aware)
- n>=3 و WR<40% → سایز ۵۰٪ (probation) نه رد کامل
- n>=5 و WR<45% → block همان نماد+جهت
- آمار WR بر اساس symbol+direction (نه فقط نماد)
- real_min_symbol_wr روی ریل هم اعمال می‌شود (نه فقط دمو)

V.2.10.57 — Report integrity: closed_at/opened_at + app_version فقط با match حافظه

V.2.10.56 — Accounting & Risk Integrity:
- Post-fill re-anchor SL/TP + validate (سقف SL / min RR روی Fill)
- Unified close ledger: همه مسیرهای close از _close_tracked
- Match دقیق history (price+qty+time) برای realized PnL
- Global SL فقط روی reasonهای واقعی SL (نه هر PnL منفی)
- DEFAULT regime_require_* = True (جلوگیری از regression)
- Recovery بدون record_realized_pnl(0)

V.2.10.55 — Execution Truth:
- signal_entry vs fill_entry (reconcile بعد از Open)
- Unified close path با realized PnL از تاریخچه صرافی
- Quantity retry با سقف ریسک (نه بزرگ‌کردن بی‌حدود)
- Recovery با age_unknown به‌جای سن مصنوعی
- Settings registry sync

V.2.9:
- حداکثر ۴ پوزیشن همزمان
- فقط سیگنال با امتیاز >= MIN_CONFLUENCE_REAL
- اهرم ۵x
- سایز هر معامله محدود به درصد کمی از موجودی
- حساسیت به کارمزد: اگر فاصله SL/TP بعد از fee منطقی نباشد رد می‌شود
- فلگ REAL_TRADING_ENABLED پیش‌فرض False تا تصادفی روشن نشود

V.2.10:
- مدیریت خودکار خروج پوزیشن‌های ریل (بدون نیاز به نگاه کردن کاربر)
- قفل سود: وقتی پیشرفت به سمت TP به آستانه رسید → بستن مارکت برای تثبیت سود
- سقف نگهداری ۲ ساعت → بستن اجباری
- ردیابی پوزیشن‌های باز در حافظه + همگام‌سازی با صرافی
- حلقه پس‌زمینه هر ۴۵ ثانیه
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Any

import toobit_private
import toobit_market
from version import APP_VERSION

def _format_open_reason(base: str, diagnostics: dict | None = None) -> str:
    """V.2.10.30 — reason قابل‌مشاهده برای last_attempts و لاگ."""
    parts = [base or "opened"]
    if isinstance(diagnostics, dict):
        rc = diagnostics.get("regime_confidence")
        rl = diagnostics.get("regime_label")
        if rc is not None and rl:
            parts.append(f"regime={rl}({rc})")
        if diagnostics.get("efficiency_ratio_1h") is not None:
            parts.append(f"er={diagnostics.get('efficiency_ratio_1h')}")
        if diagnostics.get("choppiness_1h") is not None:
            parts.append(f"ci={diagnostics.get('choppiness_1h')}")
        if diagnostics.get("ema_stack_1h"):
            parts.append(f"stack={diagnostics.get('ema_stack_1h')}")
        if diagnostics.get("adx_1h") is not None:
            parts.append(f"adx1h={diagnostics.get('adx_1h')}")
    return " | ".join(str(p) for p in parts)


logger = logging.getLogger("real_trade")

# --- فلگ اصلی ---
REAL_TRADING_ENABLED = os.getenv("REAL_TRADING_ENABLED", "false").lower() in ("1", "true", "yes")
# V.2.10.50 — سوئیچ UI برای توقف ورود جدید (مدیریت پوزیشن‌های باز ادامه دارد)
ENABLE_NEW_ENTRIES = True
# V.2.10.51 — توقف خودکار ورود وقتی رژیم BTC کثیف است (پوزیشن باز ادامه دارد)
AUTO_PAUSE_ENTRIES_ON_BTC_REGIME = True
AUTO_RESUME_MIN_BTC_CONF = 60.0
AUTO_PAUSE_ON_BTC_BEAR_STACK = True

# --- محدودیت‌های سرمایه ---
MAX_OPEN_POSITIONS = 4
MIN_CONFLUENCE_REAL = 98
LEVERAGE = 5
# مارجین همیشه نسبتی از موجودی آزاد (بدون سقف ثابت ۶ دلاری)
MARGIN_FRACTION = 0.20          # ۲۰٪ موجودی آزاد به‌عنوان مارجین
MIN_MARGIN_USDT = 3.0  # V.2.10.22: کف مارجین — پوزیشن ریز ممنوع
MAX_MARGIN_FRACTION = 0.30      # سقف نرم: حداکثر ۳۰٪ موجودی
MAX_MARGIN_USDT_ABS = 40.0      # سقف سخت ایمنی برای حساب‌های خیلی بزرگ
MIN_NOTIONAL_USDT = 25.0        # حداقل notional پایه (با تطبیق روی حساب کوچک)
MIN_SL_DISTANCE_PCT = 0.40   # V.2.10.15: کمی نرم‌تر از 0.45 برای سیگنال‌های لب‌مرزی (مثل SOL 0.42%)
MAX_SL_DISTANCE_PCT = 1.50   # V.2.10.33: سقف SL — جلوگیری از باخت‌های ~5% مثل ARB
ENABLE_ER_NOISE_FILTER_REAL = True
ER_NOISE_MAX = 0.22          # V.2.10.90: سخت‌تر از 0.15 — ER خیلی ضعیف = نویز
# V.2.10.90 — تشخیص نویز/روند ظاهری قبل از ورود
ENABLE_CI_NOISE_FILTER_REAL = True
CI_NOISE_MAX = 52.0           # CI >= این → بازار رنج/نویزی؛ ورود ریل رد
ENABLE_TREND_QUALITY_GATE = True
TREND_QUALITY_MIN_ER = 0.28   # اگر برچسب TREND ولی ER ضعیف
TREND_QUALITY_MAX_CI = 50.0   # و CI بالا → روند ظاهری، ورود رد
# V.2.10.91 — anti-noise قبل از ورود
ENABLE_ENTRY_CANDLE_CONFIRM = True
ENTRY_CONFIRM_CANDLES = 2          # حداقل ۲ کندل ۵m هم‌جهت بسته
ENABLE_CANDLE_NOISE_FILTER = True
CANDLE_NOISE_MAX_ATR = 1.50       # range آخرین کندل > 1.5×ATR → رد
CANDLE_NOISE_MAX_WICK = 0.60      # سایه خلاف‌جهت > 60% range → رد
ENABLE_TREND_TRANSITION_GUARD = True
TRANSITION_EMA_BUFFER_PCT = 0.05  # زیر/بالای EMA20 با حاشیه
ENABLE_ALT_ER_STRICT = True
ALT_ER_MIN = 0.28                # ER سخت‌تر فقط برای آلت (نه BTC)
# V.2.10.92 — سوراخ‌های ورود روی نویز / انتقال روند
ANTI_NOISE_FAIL_CLOSED = True         # بدون داده کندل → ورود رد (نه fail-open)
ENABLE_ADX_BYPASS_BTC_CHOP = False    # ADX قوی نماد، CHOP بیت‌کوین را دور نزند
ENABLE_REAL_M5_CLOSED_TRIGGER = True  # تریگر فقط ۱۵m برای ریل کافی نیست
# V.2.10.63 — کف ADX ورود: جلوی TREND_OK با ADX ضعیف
ENABLE_MIN_ADX_ENTRY = True
MIN_ADX_1H_FOR_ENTRY = 20.0      # V.2.10.96: روند تازه بعد از CHOP — 25 خفه می‌کرد
MIN_BTC_ADX_1H_FOR_ALT = 20.0    # برای آلت: ADX بیت‌کوین هم حداقل این
# V.2.10.65 — اگر ADX خود نماد خیلی قوی باشد، کف ADX بیت‌کوین برای آلت نادیده گرفته شود
ADX_STRONG_BYPASS_BTC = 30.0  # V.2.10.76: برای CHOP و WEAK هر دو معتبر
# V.2.10.98 — range engine is independent; weak_trend is a sized trend path
ENABLE_RANGE_SCALP = True
RANGE_MIN_CONFLUENCE = 85
RANGE_MAX_SL_DISTANCE_PCT = 1.10
RANGE_MIN_RR = 0.80          # net RR; 1.05 made midpoint targets impossible after fees
RANGE_MIN_TP_PCT = 0.45
RANGE_SIZE_MULT = 0.40
RANGE_MAX_OPEN_POSITIONS = 2
RANGE_CI_HARD_MAX = 68.0
RANGE_ER_FLOOR = 0.04
RANGE_ALLOW_BTC_WEAK = True
RANGE_ALLOW_BTC_CHOP = True
RANGE_SIGNAL_ONLY = False    # user wants live scalps; set true to observe only
RANGE_TIME_STOP_SEC = 90 * 60
RANGE_WIN_COOLDOWN_SEC = 20 * 60
RANGE_MAX_LOSS_USDT = 0.45  # after bumping size to exchange min notional
ENABLE_WEAK_TREND = True
WEAK_TREND_SIZE_MULT = 0.60
WEAK_TREND_MIN_CONFLUENCE = 90
WEAK_TREND_MIN_ADX = 18.0
WEAK_TREND_MAX_LOSS_USDT = 0.55
_pending_strategy: dict[str, str] = {}  # symbol → trend | range_scalp | weak_trend
_BOOT_TS = time.time()
_seen_on_exchange: set[str] = set()
# V.2.10.66 — اگر ADX نماد ≥ آستانه، pause مربوط به BTC WEAK/bear هم برای همان نماد نادیده گرفته شود
ENABLE_STRONG_ADX_BYPASS_BTC_PAUSE = True
# V.2.10.68 — توقف ورود در پنجره خبر high-impact (USD)
ENABLE_NEWS_BLACKOUT = True
NEWS_BLACKOUT_MINUTES_BEFORE = 30
NEWS_BLACKOUT_MINUTES_AFTER = 45

DAILY_LOSS_LIMIT_USDT = 3.0
# حداقل R:R بعد از کارمزد — هدف باید حداقل ۲ برابر فاصله SL باشد
MIN_RR_REAL = 1.2  # V.2.10.54: هم‌تراز با DEFAULTS/runtime (نه 1.6 پایهٔ قدیمی)
ROUND_TRIP_FRICTION_PCT = 0.18  # فی+اسلیپیج تقریبی رفت‌وبرگشت (٪ قیمت)
# حداقل فاصله TP به درصد قیمت
MIN_TP_DISTANCE_PCT = 0.72
# کول‌داون بعد از رد/خطا برای همان نماد (ثانیه)
SYMBOL_COOLDOWN_SECONDS = 12 * 60
POST_CLOSE_COOLDOWN_SECONDS = 12 * 60  # V.2.10.16: کول‌داون پس از بستن — پایدار روی دیسک (data/post_close_cooldown.json)
# V.2.10.47: کول‌داون طولانی‌تر فقط بعد از SL
POST_SL_COOLDOWN_SECONDS = 30 * 60
# V.2.10.75 — هر بستن با PnL منفی (حتی SCRATCH) → کول‌داون بلند؛ جلوگیری از باز شدن مجدد XLM
POST_NEGATIVE_COOLDOWN_SECONDS = 4 * 3600  # 4h
NEGATIVE_PNL_THRESHOLD_USDT = -0.01        # زیر این = منفی قطعی برای قفل

# V.2.10.59: بعد از برد (float/TP/lock) کول‌داون طولانی‌تر — ضد تعقیب همان نماد
POST_PROFIT_COOLDOWN_SECONDS = 60 * 60  # 1h
ENABLE_POST_PROFIT_HYSTERESIS = True
# در ۲ ساعت اول بعد از برد: ER باید حداقل این نسبت از baseline برد باشد (مثلاً نه افت شدید)
POST_PROFIT_HYST_WINDOW_SEC = 2 * 3600
POST_PROFIT_HYST_MIN_ER_RATIO = 0.95  # ER فعلی >= 0.95 * ER لحظهٔ برد (افت شدید بلاک)
POST_PROFIT_HYST_MIN_ADX_RATIO = 0.85
# V.2.10.47: قفل نماد بعد از ۲ استاپ در پنجرهٔ کوتاه
SYMBOL_SL_LOCK_COUNT = 2
SYMBOL_SL_LOCK_LOOKBACK_SEC = 3 * 3600
SYMBOL_SL_LOCK_SEC = 4 * 3600

# V.2.10.17 — محافظ‌های وین‌ریت (از الگوهای freqtrade)
GLOBAL_SL_LIMIT = 3                    # تعداد SL در پنجره → قفل سراسری
GLOBAL_SL_LOOKBACK_SEC = 60 * 60       # ۶۰ دقیقه
GLOBAL_SL_LOCK_SEC = 12 * 60           # مدت قفل سراسری بعد از تریگر
# V.2.10.84 — قفل خوشه‌ای سریع‌تر: ۲× SL سخت در ۲h → pause ورود ۳h
CLUSTER_SL_LIMIT = 2
CLUSTER_SL_LOOKBACK_SEC = 2 * 3600
CLUSTER_SL_LOCK_SEC = 3 * 3600
# وقتی BTC ضعیف/چاپ است سقف هم‌جهت = ۱
WEAK_BTC_MAX_SAME_DIRECTION = 1
# اگر لانگ/شورت باز با ضرر شناور باشد، هم‌جهت جدید ممنوع
UNDERWATER_BLOCK_SAME_DIR = True
UNDERWATER_MIN_LOSS_PCT = 0.05  # زیر −0.05٪ قیمتی = underwater
UNDERWATER_MIN_LOSS_USDT = 0.02  # V.2.11.6 — قابل تنظیم (قبلاً ثابت در کد)
PAPER_TRACK_UNDERWATER_REJECTS = True  # V.2.11.6
# V.2.10.85: بعد از ریست Space قفل سراسری ورود را از دیسک برنگردان (پوزیشن‌های باز recover می‌شوند)
CLEAR_GLOBAL_ENTRY_LOCK_ON_BOOT = os.getenv("CLEAR_GLOBAL_ENTRY_LOCK_ON_BOOT", "true").lower() in ("1", "true", "yes")
# V.2.10.86: قفل سراسری فقط داخل همین process — بعد از ریست Space هرگز از دیسک برنمی‌گردد
_SESSION_START_TS = time.time()
PERSIST_GLOBAL_ENTRY_LOCK = os.getenv("PERSIST_GLOBAL_ENTRY_LOCK", "false").lower() in ("1", "true", "yes")

ROLLING_LOW_PROFIT_WINDOW_SEC = 120 * 60  # ۲ ساعت
ROLLING_LOW_PROFIT_MIN_TRADES = 2
ROLLING_LOW_PROFIT_LOCK_SEC = 12 * 60

# ورود سخت‌تر: WR دمو/تاریخچه برای نماد
REAL_MIN_SYMBOL_WR = 45.0  # block live وقتی n>=5 و WR کمتر از این
REAL_MIN_SYMBOL_SAMPLES = 8  # دمو
# V.2.10.58 — probation / block لایه‌ای (live، direction-aware)
LIVE_WR_BLOCK_MIN_N = 5
LIVE_WR_BLOCK_PCT = 45.0          # هم‌تراز real_min_symbol_wr
LIVE_WR_PROBATION_MIN_N = 3
LIVE_WR_PROBATION_PCT = 40.0
LIVE_WR_PROBATION_SIZE_MULT = 0.50
# تا موجودی زیر این، حداکثر ۱ پوزیشن همزمان (V.2.10.20: نرم‌تر برای ~۳۰$)
LOW_BALANCE_MAX_POS = 22.0
# V.2.10.14: سقف پوزیشن هم‌جهت
MAX_SAME_DIRECTION_POSITIONS = 2
ENABLE_CHOP_FILTER_REAL = True
CHOP_ADX_THRESHOLD = 20.0
# V.2.10.27: فیلتر هم‌جهت با رژیم (soft، فقط ریل)
ENABLE_REGIME_ALIGN_REAL = True
# V.2.10.48: وقتی BTC چاپ است ورود آلت سخت‌گیر/مسدود
ENABLE_BTC_CHOP_GATE = True
BTC_CHOP_BLOCK_ALTS = True          # CHOP → آلت باز نشود
BTC_WEAK_MIN_CONF = 55.0            # WEAK با conf کمتر از این → آلت رد
REGIME_MIN_ADX = 18.0  # حداقل یکی از ADX15/30 باید ≥ این باشد
REGIME_REQUIRE_BTC_ALIGN = True  # اگر BTC هردو HTF یک‌جهت بودند، خلافش رد
REGIME_REQUIRE_SYMBOL_HTF = True  # جهت باید با h4/h1 نماد یکی باشد

# V.2.10.32: خروج نرم وقتی رژیم خلاف پوزیشن است (نه reverse)
ENABLE_REGIME_SOFT_EXIT = True
REGIME_EXIT_CACHE_SEC = 120
REGIME_EXIT_BE_PCT = 0.15          # BE زودتر در رژیم مخالف
REGIME_EXIT_LOCK_PROGRESS = 0.50   # قفل زودتر
REGIME_EXIT_LOCK_MIN_PROFIT = 0.35
REGIME_EXIT_FLAT_MIN_ELAPSED = 360  # حداقل ۶ دقیقه قبل از soft-exit
REGIME_EXIT_FLAT_MIN_PNL_PCT = 0.15  # V.2.10.35: ≥۰.۱۵٪ تا بعد از فی راندتریپ (~۰.۰۸٪) منفی نشود
MIN_NET_CLOSE_PNL_PCT = 0.15       # مشترک: timeout و soft-exit
REGIME_EXIT_MIN_CONF = 55          # حداقل اعتماد رژیم برای اقدام
# V.2.10.89 — قطع ضرر وقتی جهت بازار برمی‌گردد
ENABLE_REGIME_ADVERSE_LOSS_EXIT = True
REGIME_ADVERSE_LOSS_MIN_ELAPSED_SEC = 180
REGIME_ADVERSE_LOSS_PNL_PCT = -0.18
REGIME_ADVERSE_LOSS_MIN_CONF = 50
REGIME_ADVERSE_BTC_HOSTILE = True


def _effective_min_notional(available: float) -> float:
    """حداقل notional — هرگز کمتر از کف مارجین × اهرم نباشد."""
    floor = MIN_MARGIN_USDT * LEVERAGE  # مثلاً 3 * 5 = 15
    if available <= 0:
        return max(MIN_NOTIONAL_USDT, floor)
    adaptive = available * 0.40 * LEVERAGE
    # کف: max(floor, 12) — سقف: MIN_NOTIONAL مگر adaptive بالاتر بخواهد در حساب بزرگ
    return max(floor, min(max(MIN_NOTIONAL_USDT, floor), max(adaptive, floor)))


def _effective_max_positions(available: float) -> int:
    """سقف پوزیشن بر اساس موجودی — V.2.10.20: از ~۲۲$ دو پوزیشن مجاز."""
    if available < LOW_BALANCE_MAX_POS:
        return 1
    if available < 45:
        return 2
    if available < 75:
        return 3
    return MAX_OPEN_POSITIONS

# --- مدیریت خروج ---
# V.2.10.21: قفل دیرتر (0.72) + min_profit 0.55 — کاهش عدم‌تقارن برد/باخت
# بعد به SL کامل برمی‌گردند (NEAR/DOGE). 0.78 مسیر تا TP خیلی دیر بود.
PROFIT_LOCK_TRIGGER_RATIO = 0.72
MIN_PROFIT_PCT_TO_LOCK = 0.55
MAX_HOLD_SECONDS = 2 * 3600
MANAGER_INTERVAL_SECONDS = 45

# V.2.10.60 — خروج کهنه پس از سقف نگهداری
ENABLE_STALE_SESSION_EXIT = True
STALE_PROFIT_MIN_PCT = 0.15          # V.2.10.61: هم‌تراز min_net_close — جلوگیری از بستن خالص‌منفی (درس SOL)
STALE_NEUTRAL_MIN_PCT = -0.12
STALE_NEUTRAL_HAD_LOSS_PCT = -0.25
# V.2.10.75 — فقط نزدیک صفرِ بعد از کارمزد (نه باند گشاد −0.40 که XLM را −0.08$ بست)
STALE_FLAT_MIN_PCT = -0.05
STALE_FLAT_MAX_LOSS_USDT = 0.02   # |ضرر| دلاری بعد از تخمین fee بسته ≤ این
STALE_FLAT_EXIT_FEE_EST = 0.02    # تخمین پایه کارمزد پایانی یک‌طرفه
FALLBACK_PROFIT_PCT = 0.55
# BE روی صرافی کمی زودتر (قبلاً 0.40)
BREAKEVEN_TRIGGER_PCT = 0.30
BREAKEVEN_MIN_R = 0.80                 # V.2.10.94: حداقل ۰.۸R قبل از انتقال SL به BE
MAX_SECONDS_WITHOUT_EXCHANGE_SL = 60  # V.2.10.37: بدون SL صرافی بیش از ۱ دقیقه نماند

# V.2.10.36 — بستن شناور سود برای آزاد کردن اسلات (وقتی سقف پوزیشن پر است)
# مثال: LINK تا +0.3$ رفت ولی به قفل 0.72 نرسید و برگشت → اسلات قفل ماند
ENABLE_FLOAT_PROFIT_EXIT = True
FLOAT_MIN_PROFIT_USDT = 0.22          # کف دلاری ایمنی
FLOAT_MIN_PROFIT_PCT = 0.28           # کف ٪ (legacy) — V.2.10.40: اولویت با R
FLOAT_MIN_R = 1.20                    # V.2.10.94: حداقل ۱.۲R تا بردها زود قطع نشوند
FLOAT_MIN_ELAPSED_SEC = 420           # حداقل ~7 دقیقه باز باشد
FLOAT_ONLY_IF_SLOTS_FULL = True        # V.2.10.94: فقط وقتی اسلات پر است

# V.2.10.37 — سقف زیان تحقق‌نیافته (ضد اسلیپیج/گپ مثل ARB ~4.9%)
# حتی اگر SL صرافی نخورده یا با گپ رد شده، مدیر مارکت می‌بندد
ENABLE_EMERGENCY_LOSS_EXIT = True
MAX_UNREALIZED_LOSS_PCT = 2.0         # اگر uPnL ≤ −۲٪ → بستن اضطراری
EMERGENCY_LOSS_MIN_ELAPSED_SEC = 30   # حداقل ۳۰ث بعد از ورود

# V.2.10.38 — تنگ کردن SL وقتی رژیم مخالف + پوزیشن در ضرر (کاهش زیان باقی‌مانده)
# بستن اجباری در ضرر نمی‌کند؛ فقط SL را نزدیک قیمت می‌آورد تا حداکثر زیان بیشتر محدود شود
ENABLE_REGIME_TIGHTEN_SL = True
REGIME_TIGHTEN_MIN_ELAPSED_SEC = 300   # حداقل ۵ دقیقه
REGIME_TIGHTEN_BUFFER_PCT = 0.15       # SL حدود ۰.۱۵٪ پشت قیمت جاری
REGIME_TIGHTEN_ONLY_IF_LOSS = True

def apply_runtime_settings() -> dict:
    """اعمال تنظیمات ذخیره‌شده از UI روی متغیرهای ماژول.
    V.2.10.93: قبل از load، cache را خالی می‌کند تا مقدار Save‌شده در Settings
    (مثلاً min_rr=1.05) بلافاصله در فیلتر ورود دیده شود و با DEFAULTS/کش کهنه قاطی نشود.
    """
    global MIN_CONFLUENCE_REAL, MIN_SL_DISTANCE_PCT, MIN_RR_REAL, MIN_TP_DISTANCE_PCT
    global MAX_SL_DISTANCE_PCT, ROUND_TRIP_FRICTION_PCT, ENABLE_ER_NOISE_FILTER_REAL, ER_NOISE_MAX
    global REAL_MIN_SYMBOL_WR, SYMBOL_COOLDOWN_SECONDS, POST_CLOSE_COOLDOWN_SECONDS
    global POST_SL_COOLDOWN_SECONDS, SYMBOL_SL_LOCK_COUNT, SYMBOL_SL_LOCK_LOOKBACK_SEC, SYMBOL_SL_LOCK_SEC, POST_PROFIT_COOLDOWN_SECONDS, ENABLE_POST_PROFIT_HYSTERESIS, POST_PROFIT_HYST_WINDOW_SEC, POST_PROFIT_HYST_MIN_ER_RATIO, POST_PROFIT_HYST_MIN_ADX_RATIO
    global PROFIT_LOCK_TRIGGER_RATIO, MIN_PROFIT_PCT_TO_LOCK, BREAKEVEN_TRIGGER_PCT
    global MAX_HOLD_SECONDS, DAILY_LOSS_LIMIT_USDT, MARGIN_FRACTION
    global MAX_OPEN_POSITIONS, LEVERAGE, ENABLE_CHOP_FILTER_REAL, CHOP_ADX_THRESHOLD
    global ENABLE_REGIME_ALIGN_REAL, REGIME_MIN_ADX, REGIME_REQUIRE_BTC_ALIGN, REGIME_REQUIRE_SYMBOL_HTF
    global ENABLE_BTC_CHOP_GATE, BTC_CHOP_BLOCK_ALTS, BTC_WEAK_MIN_CONF
    global MAX_SAME_DIRECTION_POSITIONS, ENABLE_NEW_ENTRIES
    global AUTO_PAUSE_ENTRIES_ON_BTC_REGIME, AUTO_RESUME_MIN_BTC_CONF, AUTO_PAUSE_ON_BTC_BEAR_STACK
    try:
        import runtime_settings as rs
        if hasattr(rs, "reset_cache"):
            rs.reset_cache()
        cfg = rs.load()
    except Exception as e:
        logger.warning("apply_runtime_settings: %s", e)
        return {}
    ENABLE_NEW_ENTRIES = bool(cfg.get("enable_new_entries", ENABLE_NEW_ENTRIES))
    AUTO_PAUSE_ENTRIES_ON_BTC_REGIME = bool(cfg.get("auto_pause_entries_on_btc_regime", AUTO_PAUSE_ENTRIES_ON_BTC_REGIME))
    try:
        AUTO_RESUME_MIN_BTC_CONF = float(cfg.get("auto_resume_min_btc_conf", AUTO_RESUME_MIN_BTC_CONF))
    except (TypeError, ValueError):
        pass
    AUTO_PAUSE_ON_BTC_BEAR_STACK = bool(cfg.get("auto_pause_on_btc_bear_stack", AUTO_PAUSE_ON_BTC_BEAR_STACK))
    MIN_CONFLUENCE_REAL = int(cfg.get("min_confluence", MIN_CONFLUENCE_REAL))
    MIN_SL_DISTANCE_PCT = float(cfg.get("min_sl_distance_pct", MIN_SL_DISTANCE_PCT))
    MAX_SL_DISTANCE_PCT = float(cfg.get("max_sl_distance_pct", MAX_SL_DISTANCE_PCT))
    ENABLE_ER_NOISE_FILTER_REAL = bool(cfg.get("enable_er_noise_filter", ENABLE_ER_NOISE_FILTER_REAL))
    ER_NOISE_MAX = float(cfg.get("er_noise_max", ER_NOISE_MAX))
    global ENABLE_CI_NOISE_FILTER_REAL, CI_NOISE_MAX, ENABLE_TREND_QUALITY_GATE
    global TREND_QUALITY_MIN_ER, TREND_QUALITY_MAX_CI
    ENABLE_CI_NOISE_FILTER_REAL = bool(cfg.get("enable_ci_noise_filter", ENABLE_CI_NOISE_FILTER_REAL))
    CI_NOISE_MAX = float(cfg.get("ci_noise_max", CI_NOISE_MAX))
    ENABLE_TREND_QUALITY_GATE = bool(cfg.get("enable_trend_quality_gate", ENABLE_TREND_QUALITY_GATE))
    TREND_QUALITY_MIN_ER = float(cfg.get("trend_quality_min_er", TREND_QUALITY_MIN_ER))
    TREND_QUALITY_MAX_CI = float(cfg.get("trend_quality_max_ci", TREND_QUALITY_MAX_CI))
    global ENABLE_ENTRY_CANDLE_CONFIRM, ENTRY_CONFIRM_CANDLES, ENABLE_CANDLE_NOISE_FILTER
    global CANDLE_NOISE_MAX_ATR, CANDLE_NOISE_MAX_WICK, ENABLE_TREND_TRANSITION_GUARD
    global TRANSITION_EMA_BUFFER_PCT, ENABLE_ALT_ER_STRICT, ALT_ER_MIN
    global ANTI_NOISE_FAIL_CLOSED, ENABLE_ADX_BYPASS_BTC_CHOP, ENABLE_REAL_M5_CLOSED_TRIGGER
    global ENABLE_RANGE_SCALP, RANGE_MIN_CONFLUENCE, RANGE_MAX_SL_DISTANCE_PCT, RANGE_MIN_RR
    global RANGE_SIZE_MULT, RANGE_MAX_OPEN_POSITIONS, RANGE_CI_HARD_MAX, RANGE_ER_FLOOR
    global RANGE_ALLOW_BTC_WEAK, RANGE_ALLOW_BTC_CHOP
    global RANGE_MIN_TP_PCT, RANGE_SIGNAL_ONLY, RANGE_TIME_STOP_SEC, RANGE_WIN_COOLDOWN_SEC, RANGE_MAX_LOSS_USDT
    global ENABLE_WEAK_TREND, WEAK_TREND_SIZE_MULT, WEAK_TREND_MIN_CONFLUENCE, WEAK_TREND_MIN_ADX, WEAK_TREND_MAX_LOSS_USDT
    ENABLE_ENTRY_CANDLE_CONFIRM = bool(cfg.get("enable_entry_candle_confirm", ENABLE_ENTRY_CANDLE_CONFIRM))
    ENTRY_CONFIRM_CANDLES = int(cfg.get("entry_confirm_candles", ENTRY_CONFIRM_CANDLES))
    ENABLE_CANDLE_NOISE_FILTER = bool(cfg.get("enable_candle_noise_filter", ENABLE_CANDLE_NOISE_FILTER))
    CANDLE_NOISE_MAX_ATR = float(cfg.get("candle_noise_max_atr", CANDLE_NOISE_MAX_ATR))
    CANDLE_NOISE_MAX_WICK = float(cfg.get("candle_noise_max_wick", CANDLE_NOISE_MAX_WICK))
    ENABLE_TREND_TRANSITION_GUARD = bool(cfg.get("enable_trend_transition_guard", ENABLE_TREND_TRANSITION_GUARD))
    TRANSITION_EMA_BUFFER_PCT = float(cfg.get("transition_ema_buffer_pct", TRANSITION_EMA_BUFFER_PCT))
    ENABLE_ALT_ER_STRICT = bool(cfg.get("enable_alt_er_strict", ENABLE_ALT_ER_STRICT))
    ALT_ER_MIN = float(cfg.get("alt_er_min", ALT_ER_MIN))
    ANTI_NOISE_FAIL_CLOSED = bool(cfg.get("anti_noise_fail_closed", ANTI_NOISE_FAIL_CLOSED))
    ENABLE_ADX_BYPASS_BTC_CHOP = bool(cfg.get("enable_adx_bypass_btc_chop", ENABLE_ADX_BYPASS_BTC_CHOP))
    ENABLE_RANGE_SCALP = bool(cfg.get("enable_range_scalp", ENABLE_RANGE_SCALP))
    RANGE_MIN_CONFLUENCE = int(cfg.get("range_min_confluence", RANGE_MIN_CONFLUENCE))
    RANGE_MAX_SL_DISTANCE_PCT = float(cfg.get("range_max_sl_distance_pct", RANGE_MAX_SL_DISTANCE_PCT))
    RANGE_MIN_RR = float(cfg.get("range_min_rr", RANGE_MIN_RR))
    RANGE_SIZE_MULT = float(cfg.get("range_size_mult", RANGE_SIZE_MULT))
    RANGE_MAX_OPEN_POSITIONS = int(cfg.get("range_max_open_positions", RANGE_MAX_OPEN_POSITIONS))
    RANGE_CI_HARD_MAX = float(cfg.get("range_ci_hard_max", RANGE_CI_HARD_MAX))
    RANGE_ER_FLOOR = float(cfg.get("range_er_floor", RANGE_ER_FLOOR))
    RANGE_ALLOW_BTC_WEAK = bool(cfg.get("range_allow_btc_weak", RANGE_ALLOW_BTC_WEAK))
    RANGE_ALLOW_BTC_CHOP = bool(cfg.get("range_allow_btc_chop", RANGE_ALLOW_BTC_CHOP))
    RANGE_MIN_TP_PCT = float(cfg.get("range_min_tp_pct", RANGE_MIN_TP_PCT))
    RANGE_SIGNAL_ONLY = bool(cfg.get("range_signal_only", RANGE_SIGNAL_ONLY))
    RANGE_TIME_STOP_SEC = int(cfg.get("range_time_stop_sec", RANGE_TIME_STOP_SEC))
    RANGE_WIN_COOLDOWN_SEC = int(cfg.get("range_win_cooldown_sec", RANGE_WIN_COOLDOWN_SEC))
    RANGE_MAX_LOSS_USDT = float(cfg.get("range_max_loss_usdt", RANGE_MAX_LOSS_USDT))
    ENABLE_WEAK_TREND = bool(cfg.get("enable_weak_trend", ENABLE_WEAK_TREND))
    WEAK_TREND_SIZE_MULT = float(cfg.get("weak_trend_size_mult", WEAK_TREND_SIZE_MULT))
    WEAK_TREND_MIN_CONFLUENCE = int(cfg.get("weak_trend_min_confluence", WEAK_TREND_MIN_CONFLUENCE))
    WEAK_TREND_MIN_ADX = float(cfg.get("weak_trend_min_adx", WEAK_TREND_MIN_ADX))
    WEAK_TREND_MAX_LOSS_USDT = float(cfg.get("weak_trend_max_loss_usdt", WEAK_TREND_MAX_LOSS_USDT))
    ENABLE_REAL_M5_CLOSED_TRIGGER = bool(cfg.get("enable_real_m5_closed_trigger", ENABLE_REAL_M5_CLOSED_TRIGGER))
    global ENABLE_MIN_ADX_ENTRY, MIN_ADX_1H_FOR_ENTRY, MIN_BTC_ADX_1H_FOR_ALT, ADX_STRONG_BYPASS_BTC
    ENABLE_MIN_ADX_ENTRY = bool(cfg.get("enable_min_adx_entry", ENABLE_MIN_ADX_ENTRY))
    MIN_ADX_1H_FOR_ENTRY = float(cfg.get("min_adx_1h_for_entry", MIN_ADX_1H_FOR_ENTRY))
    MIN_BTC_ADX_1H_FOR_ALT = float(cfg.get("min_btc_adx_1h_for_alt", MIN_BTC_ADX_1H_FOR_ALT))
    ADX_STRONG_BYPASS_BTC = float(cfg.get("adx_strong_bypass_btc", ADX_STRONG_BYPASS_BTC))
    global ENABLE_STRONG_ADX_BYPASS_BTC_PAUSE
    ENABLE_STRONG_ADX_BYPASS_BTC_PAUSE = bool(cfg.get("enable_strong_adx_bypass_btc_pause", ENABLE_STRONG_ADX_BYPASS_BTC_PAUSE))
    global ENABLE_NEWS_BLACKOUT, NEWS_BLACKOUT_MINUTES_BEFORE, NEWS_BLACKOUT_MINUTES_AFTER
    ENABLE_NEWS_BLACKOUT = bool(cfg.get("enable_news_blackout", ENABLE_NEWS_BLACKOUT))
    NEWS_BLACKOUT_MINUTES_BEFORE = int(cfg.get("news_blackout_minutes_before", NEWS_BLACKOUT_MINUTES_BEFORE))
    NEWS_BLACKOUT_MINUTES_AFTER = int(cfg.get("news_blackout_minutes_after", NEWS_BLACKOUT_MINUTES_AFTER))
    try:
        from news_blackout import apply_news_settings
        apply_news_settings({
            "enable_news_blackout": ENABLE_NEWS_BLACKOUT,
            "news_blackout_minutes_before": NEWS_BLACKOUT_MINUTES_BEFORE,
            "news_blackout_minutes_after": NEWS_BLACKOUT_MINUTES_AFTER,
            # V.2.11.2 — پله‌های خبر
            "news_tiered": cfg.get("news_tiered", True),
            "news_tier_b_minutes_before": cfg.get("news_tier_b_minutes_before", 10),
            "news_tier_b_minutes_after": cfg.get("news_tier_b_minutes_after", 20),
            "news_block_tier_c": cfg.get("news_block_tier_c", False),
        })
    except Exception as _ne:
        logger.debug("news settings: %s", _ne)
    MIN_RR_REAL = float(cfg.get("min_rr", MIN_RR_REAL))
    logger.info("apply_runtime_settings min_rr=%s", MIN_RR_REAL)
    ROUND_TRIP_FRICTION_PCT = float(cfg.get("round_trip_friction_pct", ROUND_TRIP_FRICTION_PCT))
    MIN_TP_DISTANCE_PCT = float(cfg.get("min_tp_distance_pct", MIN_TP_DISTANCE_PCT))
    REAL_MIN_SYMBOL_WR = float(cfg.get("real_min_symbol_wr", REAL_MIN_SYMBOL_WR))
    global LIVE_WR_BLOCK_MIN_N, LIVE_WR_BLOCK_PCT, LIVE_WR_PROBATION_MIN_N, LIVE_WR_PROBATION_PCT, LIVE_WR_PROBATION_SIZE_MULT
    LIVE_WR_BLOCK_MIN_N = int(cfg.get("live_wr_block_min_n", LIVE_WR_BLOCK_MIN_N))
    LIVE_WR_BLOCK_PCT = float(cfg.get("live_wr_block_pct", LIVE_WR_BLOCK_PCT))
    LIVE_WR_PROBATION_MIN_N = int(cfg.get("live_wr_probation_min_n", LIVE_WR_PROBATION_MIN_N))
    LIVE_WR_PROBATION_PCT = float(cfg.get("live_wr_probation_pct", LIVE_WR_PROBATION_PCT))
    LIVE_WR_PROBATION_SIZE_MULT = float(cfg.get("live_wr_probation_size_mult", LIVE_WR_PROBATION_SIZE_MULT))
    SYMBOL_COOLDOWN_SECONDS = int(cfg.get("symbol_cooldown_sec", SYMBOL_COOLDOWN_SECONDS))
    POST_CLOSE_COOLDOWN_SECONDS = int(cfg.get("post_close_cooldown_sec", POST_CLOSE_COOLDOWN_SECONDS))
    POST_SL_COOLDOWN_SECONDS = int(cfg.get("post_sl_cooldown_sec", POST_SL_COOLDOWN_SECONDS))
    global POST_NEGATIVE_COOLDOWN_SECONDS, NEGATIVE_PNL_THRESHOLD_USDT
    POST_NEGATIVE_COOLDOWN_SECONDS = int(cfg.get("post_negative_cooldown_sec", POST_NEGATIVE_COOLDOWN_SECONDS))
    NEGATIVE_PNL_THRESHOLD_USDT = float(cfg.get("negative_pnl_threshold_usdt", NEGATIVE_PNL_THRESHOLD_USDT))
    global GLOBAL_SL_LIMIT, GLOBAL_SL_LOOKBACK_SEC, GLOBAL_SL_LOCK_SEC
    GLOBAL_SL_LIMIT = int(cfg.get("global_sl_limit", GLOBAL_SL_LIMIT))
    GLOBAL_SL_LOOKBACK_SEC = int(cfg.get("global_sl_lookback_sec", GLOBAL_SL_LOOKBACK_SEC))
    GLOBAL_SL_LOCK_SEC = int(cfg.get("global_sl_lock_sec", GLOBAL_SL_LOCK_SEC))
    POST_PROFIT_COOLDOWN_SECONDS = int(cfg.get("post_profit_cooldown_sec", POST_PROFIT_COOLDOWN_SECONDS))
    ENABLE_POST_PROFIT_HYSTERESIS = bool(cfg.get("enable_post_profit_hysteresis", ENABLE_POST_PROFIT_HYSTERESIS))
    POST_PROFIT_HYST_WINDOW_SEC = int(cfg.get("post_profit_hyst_window_sec", POST_PROFIT_HYST_WINDOW_SEC))
    POST_PROFIT_HYST_MIN_ER_RATIO = float(cfg.get("post_profit_hyst_min_er_ratio", POST_PROFIT_HYST_MIN_ER_RATIO))
    POST_PROFIT_HYST_MIN_ADX_RATIO = float(cfg.get("post_profit_hyst_min_adx_ratio", POST_PROFIT_HYST_MIN_ADX_RATIO))
    SYMBOL_SL_LOCK_COUNT = int(cfg.get("symbol_sl_lock_count", SYMBOL_SL_LOCK_COUNT))
    SYMBOL_SL_LOCK_LOOKBACK_SEC = int(cfg.get("symbol_sl_lock_lookback_sec", SYMBOL_SL_LOCK_LOOKBACK_SEC))
    SYMBOL_SL_LOCK_SEC = int(cfg.get("symbol_sl_lock_sec", SYMBOL_SL_LOCK_SEC))
    PROFIT_LOCK_TRIGGER_RATIO = float(cfg.get("profit_lock_trigger", PROFIT_LOCK_TRIGGER_RATIO))
    MIN_PROFIT_PCT_TO_LOCK = float(cfg.get("min_profit_pct", MIN_PROFIT_PCT_TO_LOCK))
    BREAKEVEN_TRIGGER_PCT = float(cfg.get("breakeven_trigger_pct", BREAKEVEN_TRIGGER_PCT))
    global BREAKEVEN_MIN_R
    BREAKEVEN_MIN_R = float(cfg.get("breakeven_min_r", BREAKEVEN_MIN_R))
    MAX_HOLD_SECONDS = int(cfg.get("max_hold_seconds", MAX_HOLD_SECONDS))
    global ENABLE_STALE_SESSION_EXIT, STALE_PROFIT_MIN_PCT, STALE_NEUTRAL_MIN_PCT, STALE_NEUTRAL_HAD_LOSS_PCT
    ENABLE_STALE_SESSION_EXIT = bool(cfg.get("enable_stale_session_exit", ENABLE_STALE_SESSION_EXIT))
    STALE_PROFIT_MIN_PCT = float(cfg.get("stale_profit_min_pct", STALE_PROFIT_MIN_PCT))
    STALE_NEUTRAL_MIN_PCT = float(cfg.get("stale_neutral_min_pct", STALE_NEUTRAL_MIN_PCT))
    STALE_NEUTRAL_HAD_LOSS_PCT = float(cfg.get("stale_neutral_had_loss_pct", STALE_NEUTRAL_HAD_LOSS_PCT))
    global STALE_FLAT_MIN_PCT, STALE_FLAT_MAX_LOSS_USDT, STALE_FLAT_EXIT_FEE_EST
    STALE_FLAT_MIN_PCT = float(cfg.get("stale_flat_min_pct", STALE_FLAT_MIN_PCT))
    STALE_FLAT_MAX_LOSS_USDT = float(cfg.get("stale_flat_max_loss_usdt", STALE_FLAT_MAX_LOSS_USDT))
    STALE_FLAT_EXIT_FEE_EST = float(cfg.get("stale_flat_exit_fee_est", STALE_FLAT_EXIT_FEE_EST))
    DAILY_LOSS_LIMIT_USDT = float(cfg.get("daily_loss_limit", DAILY_LOSS_LIMIT_USDT))
    MARGIN_FRACTION = float(cfg.get("margin_fraction", MARGIN_FRACTION))
    MAX_OPEN_POSITIONS = int(cfg.get("max_open_positions", MAX_OPEN_POSITIONS))
    LEVERAGE = int(cfg.get("leverage", LEVERAGE))
    ENABLE_CHOP_FILTER_REAL = bool(cfg.get("enable_chop_filter", ENABLE_CHOP_FILTER_REAL))
    CHOP_ADX_THRESHOLD = float(cfg.get("chop_adx_threshold", CHOP_ADX_THRESHOLD))
    ENABLE_REGIME_ALIGN_REAL = bool(cfg.get("enable_regime_align", ENABLE_REGIME_ALIGN_REAL))
    ENABLE_BTC_CHOP_GATE = bool(cfg.get("enable_btc_chop_gate", ENABLE_BTC_CHOP_GATE))
    BTC_CHOP_BLOCK_ALTS = bool(cfg.get("btc_chop_block_alts", BTC_CHOP_BLOCK_ALTS))
    BTC_WEAK_MIN_CONF = float(cfg.get("btc_weak_min_conf", BTC_WEAK_MIN_CONF))
    REGIME_MIN_ADX = float(cfg.get("regime_min_adx", REGIME_MIN_ADX))
    REGIME_REQUIRE_BTC_ALIGN = bool(cfg.get("regime_require_btc_align", REGIME_REQUIRE_BTC_ALIGN))
    REGIME_REQUIRE_SYMBOL_HTF = bool(cfg.get("regime_require_symbol_htf", REGIME_REQUIRE_SYMBOL_HTF))
    global ENABLE_REGIME_SOFT_EXIT, REGIME_EXIT_BE_PCT, REGIME_EXIT_LOCK_PROGRESS, REGIME_EXIT_LOCK_MIN_PROFIT
    global REGIME_EXIT_FLAT_MIN_ELAPSED, REGIME_EXIT_FLAT_MIN_PNL_PCT
    ENABLE_REGIME_SOFT_EXIT = bool(cfg.get("enable_regime_soft_exit", ENABLE_REGIME_SOFT_EXIT))
    global ENABLE_REGIME_ADVERSE_LOSS_EXIT, REGIME_ADVERSE_LOSS_MIN_ELAPSED_SEC, REGIME_ADVERSE_LOSS_PNL_PCT
    global REGIME_ADVERSE_LOSS_MIN_CONF, REGIME_ADVERSE_BTC_HOSTILE
    ENABLE_REGIME_ADVERSE_LOSS_EXIT = bool(cfg.get("enable_regime_adverse_loss_exit", ENABLE_REGIME_ADVERSE_LOSS_EXIT))
    REGIME_ADVERSE_LOSS_MIN_ELAPSED_SEC = float(cfg.get("regime_adverse_loss_min_elapsed_sec", REGIME_ADVERSE_LOSS_MIN_ELAPSED_SEC))
    REGIME_ADVERSE_LOSS_PNL_PCT = float(cfg.get("regime_adverse_loss_pnl_pct", REGIME_ADVERSE_LOSS_PNL_PCT))
    REGIME_ADVERSE_LOSS_MIN_CONF = float(cfg.get("regime_adverse_loss_min_conf", REGIME_ADVERSE_LOSS_MIN_CONF))
    REGIME_ADVERSE_BTC_HOSTILE = bool(cfg.get("regime_adverse_btc_hostile", REGIME_ADVERSE_BTC_HOSTILE))
    REGIME_EXIT_BE_PCT = float(cfg.get("regime_exit_be_pct", REGIME_EXIT_BE_PCT))
    REGIME_EXIT_LOCK_PROGRESS = float(cfg.get("regime_exit_lock_progress", REGIME_EXIT_LOCK_PROGRESS))
    REGIME_EXIT_LOCK_MIN_PROFIT = float(cfg.get("regime_exit_lock_min_profit", REGIME_EXIT_LOCK_MIN_PROFIT))
    REGIME_EXIT_FLAT_MIN_ELAPSED = float(cfg.get("regime_exit_flat_min_elapsed", REGIME_EXIT_FLAT_MIN_ELAPSED))
    REGIME_EXIT_FLAT_MIN_PNL_PCT = float(cfg.get("regime_exit_flat_min_pnl_pct", REGIME_EXIT_FLAT_MIN_PNL_PCT))
    global MIN_NET_CLOSE_PNL_PCT
    MIN_NET_CLOSE_PNL_PCT = float(cfg.get("min_net_close_pnl_pct", MIN_NET_CLOSE_PNL_PCT))
    MAX_SAME_DIRECTION_POSITIONS = int(cfg.get("max_same_direction", MAX_SAME_DIRECTION_POSITIONS))
    global ENABLE_FLOAT_PROFIT_EXIT, FLOAT_MIN_PROFIT_USDT, FLOAT_MIN_PROFIT_PCT
    global FLOAT_MIN_ELAPSED_SEC, FLOAT_ONLY_IF_SLOTS_FULL
    ENABLE_FLOAT_PROFIT_EXIT = bool(cfg.get("enable_float_profit_exit", ENABLE_FLOAT_PROFIT_EXIT))
    FLOAT_MIN_PROFIT_USDT = float(cfg.get("float_min_profit_usdt", FLOAT_MIN_PROFIT_USDT))
    FLOAT_MIN_PROFIT_PCT = float(cfg.get("float_min_profit_pct", FLOAT_MIN_PROFIT_PCT))
    FLOAT_MIN_ELAPSED_SEC = float(cfg.get("float_min_elapsed_sec", FLOAT_MIN_ELAPSED_SEC))
    global FLOAT_MIN_R
    FLOAT_MIN_R = float(cfg.get("float_min_r", FLOAT_MIN_R))
    FLOAT_ONLY_IF_SLOTS_FULL = bool(cfg.get("float_only_if_slots_full", FLOAT_ONLY_IF_SLOTS_FULL))
    global ENABLE_EMERGENCY_LOSS_EXIT, MAX_UNREALIZED_LOSS_PCT, EMERGENCY_LOSS_MIN_ELAPSED_SEC
    global MAX_SECONDS_WITHOUT_EXCHANGE_SL
    ENABLE_EMERGENCY_LOSS_EXIT = bool(cfg.get("enable_emergency_loss_exit", ENABLE_EMERGENCY_LOSS_EXIT))
    MAX_UNREALIZED_LOSS_PCT = float(cfg.get("max_unrealized_loss_pct", MAX_UNREALIZED_LOSS_PCT))
    EMERGENCY_LOSS_MIN_ELAPSED_SEC = float(cfg.get("emergency_loss_min_elapsed_sec", EMERGENCY_LOSS_MIN_ELAPSED_SEC))
    MAX_SECONDS_WITHOUT_EXCHANGE_SL = int(cfg.get("max_seconds_without_exchange_sl", MAX_SECONDS_WITHOUT_EXCHANGE_SL))
    global ENABLE_REGIME_TIGHTEN_SL, REGIME_TIGHTEN_MIN_ELAPSED_SEC, REGIME_TIGHTEN_BUFFER_PCT
    global REGIME_TIGHTEN_ONLY_IF_LOSS
    ENABLE_REGIME_TIGHTEN_SL = bool(cfg.get("enable_regime_tighten_sl", ENABLE_REGIME_TIGHTEN_SL))
    REGIME_TIGHTEN_MIN_ELAPSED_SEC = float(cfg.get("regime_tighten_min_elapsed_sec", REGIME_TIGHTEN_MIN_ELAPSED_SEC))
    REGIME_TIGHTEN_BUFFER_PCT = float(cfg.get("regime_tighten_buffer_pct", REGIME_TIGHTEN_BUFFER_PCT))
    REGIME_TIGHTEN_ONLY_IF_LOSS = bool(cfg.get("regime_tighten_only_if_loss", REGIME_TIGHTEN_ONLY_IF_LOSS))
    # V.2.11.0
    global BTC_DRIFT_GUARD_RANGE, BTC_DRIFT_MIN_RET_PCT, BTC_DRIFT_WINDOW_MIN, BTC_DRIFT_TREND_FOLLOW
    global BTC_DRIFT_FOLLOW_MIN_SYMBOL_CONF, BTC_DRIFT_SAME_DIR_CAP, PAPER_TRACK_BLOCKED
    BTC_DRIFT_GUARD_RANGE = bool(cfg.get("btc_drift_guard_range", BTC_DRIFT_GUARD_RANGE))
    BTC_DRIFT_MIN_RET_PCT = float(cfg.get("btc_drift_min_ret_pct", BTC_DRIFT_MIN_RET_PCT))
    BTC_DRIFT_WINDOW_MIN = int(cfg.get("btc_drift_window_min", BTC_DRIFT_WINDOW_MIN))
    BTC_DRIFT_TREND_FOLLOW = bool(cfg.get("btc_drift_trend_follow", BTC_DRIFT_TREND_FOLLOW))
    BTC_DRIFT_FOLLOW_MIN_SYMBOL_CONF = float(cfg.get("btc_drift_follow_min_symbol_conf", BTC_DRIFT_FOLLOW_MIN_SYMBOL_CONF))
    BTC_DRIFT_SAME_DIR_CAP = int(cfg.get("btc_drift_same_dir_cap", BTC_DRIFT_SAME_DIR_CAP))
    global PAPER_TRACK_OVEREXT_REJECTS, OVEREXT_STRONG_ER, OVEREXT_STRONG_ADX  # V.2.11.11
    PAPER_TRACK_OVEREXT_REJECTS = bool(cfg.get("paper_track_overext_rejects", PAPER_TRACK_OVEREXT_REJECTS))
    OVEREXT_STRONG_ER = float(cfg.get("overext_strong_er", OVEREXT_STRONG_ER))
    OVEREXT_STRONG_ADX = float(cfg.get("overext_strong_adx", OVEREXT_STRONG_ADX))
    global PAPER_TRACK_SLMIN_REJECTS, PAPER_TRACK_SAMEDIR_CAP_REJECTS  # V.2.11.10
    PAPER_TRACK_SLMIN_REJECTS = bool(cfg.get("paper_track_slmin_rejects", PAPER_TRACK_SLMIN_REJECTS))
    PAPER_TRACK_SAMEDIR_CAP_REJECTS = bool(cfg.get("paper_track_samedir_cap_rejects", PAPER_TRACK_SAMEDIR_CAP_REJECTS))
    global BACKTEST_ENABLED, BACKTEST_DAYS, BACKTEST_EVERY_HOURS, BACKTEST_FEE_RT_PCT, BACKTEST_STOP_SLIP_PCT  # V.2.12.0
    global BACKTEST_TREND_ENABLED  # V.2.12.1
    global TREND_MAKER_TP, MAKER_TP_SELFTEST  # V.2.12.3
    global SIZE_UP_ENABLED, SIZE_UP_MULT  # V.2.16.0
    SIZE_UP_ENABLED = bool(cfg.get("size_up_enabled", SIZE_UP_ENABLED))
    SIZE_UP_MULT = float(cfg.get("size_up_mult", SIZE_UP_MULT))
    global RSI_ENABLED  # V.2.18.1
    RSI_ENABLED = bool(cfg.get("rs_intraday_enabled", RSI_ENABLED)) and LEGACY_LIVE_ENABLED   # V.2.35.1
    global INTRADAY_MAX_HOLD_HOURS  # V.2.18.3
    INTRADAY_MAX_HOLD_HOURS = float(cfg.get("intraday_max_hold_hours", INTRADAY_MAX_HOLD_HOURS))
    global BACKTEST_INTRADAY_ENABLED, BACKTEST_UNIVERSE_N  # V.2.18.0
    BACKTEST_INTRADAY_ENABLED = bool(cfg.get("backtest_intraday_enabled", BACKTEST_INTRADAY_ENABLED))
    BACKTEST_UNIVERSE_N = int(cfg.get("backtest_universe_n", BACKTEST_UNIVERSE_N))
    global TSMOM_ENABLED, TSMOM_LIVE_SL_CAP_PCT, BACKTEST_DAILY_ENABLED  # V.2.17.0
    TSMOM_ENABLED = bool(cfg.get("tsmom_enabled", TSMOM_ENABLED))
    TSMOM_LIVE_SL_CAP_PCT = float(cfg.get("tsmom_live_sl_cap_pct", TSMOM_LIVE_SL_CAP_PCT))
    global TREND_ATR_ENABLED  # V.2.20.0
    TREND_ATR_ENABLED = bool(cfg.get("trend_atr_enabled", TREND_ATR_ENABLED))
    global GH_PAPER_ENABLED  # V.2.22.0
    GH_PAPER_ENABLED = bool(cfg.get("gh_paper_enabled", GH_PAPER_ENABLED))
    global GH_LIVE_ENABLED  # V.2.22.1
    GH_LIVE_ENABLED = bool(cfg.get("gh_live_enabled", GH_LIVE_ENABLED))
    BACKTEST_DAILY_ENABLED = bool(cfg.get("backtest_daily_enabled", BACKTEST_DAILY_ENABLED))
    global RS_ENABLED  # V.2.15.0
    RS_ENABLED = bool(cfg.get("rel_strength_enabled", RS_ENABLED)) and LEGACY_LIVE_ENABLED   # V.2.35.1
    global AUTO_MATRIX, MATRIX_MIN_N_ON, MATRIX_MIN_N_PROBE, MATRIX_PROBE_MAX_OPEN, MATRIX_DEMOTE_MIN_N, MATRIX_DEMOTE_AVG_PCT  # V.2.13.0
    AUTO_MATRIX = bool(cfg.get("auto_matrix", AUTO_MATRIX))
    MATRIX_MIN_N_ON = int(cfg.get("matrix_min_n_on", MATRIX_MIN_N_ON))
    MATRIX_MIN_N_PROBE = int(cfg.get("matrix_min_n_probe", MATRIX_MIN_N_PROBE))
    MATRIX_PROBE_MAX_OPEN = int(cfg.get("matrix_probe_max_open", MATRIX_PROBE_MAX_OPEN))
    MATRIX_DEMOTE_MIN_N = int(cfg.get("matrix_demote_min_n", MATRIX_DEMOTE_MIN_N))
    MATRIX_DEMOTE_AVG_PCT = float(cfg.get("matrix_demote_avg_pct", MATRIX_DEMOTE_AVG_PCT))
    # V.2.18.4 — maker TP خاموش (تنظیم نادیده گرفته می‌شود): سفارش limit بستن کل مقدار پوزیشن را قفل می‌کرد
    # (available=0) ⇒ SL شرطی صرافی موقع فعال شدن اجرا نشد و حذف شد (OP ۱۰ اکتبر) و بستن مارکت ربات هم رد می‌شد.
    TREND_MAKER_TP = False
    MAKER_TP_SELFTEST = False
    BACKTEST_TREND_ENABLED = bool(cfg.get("backtest_trend_enabled", BACKTEST_TREND_ENABLED))
    BACKTEST_ENABLED = bool(cfg.get("backtest_enabled", BACKTEST_ENABLED))
    BACKTEST_DAYS = int(cfg.get("backtest_days", BACKTEST_DAYS))
    BACKTEST_EVERY_HOURS = int(cfg.get("backtest_every_hours", BACKTEST_EVERY_HOURS))
    BACKTEST_FEE_RT_PCT = float(cfg.get("backtest_fee_rt_pct", BACKTEST_FEE_RT_PCT))
    BACKTEST_STOP_SLIP_PCT = float(cfg.get("backtest_stop_slip_pct", BACKTEST_STOP_SLIP_PCT))
    global RANGE_SMALL_TP_AUTO, RANGE_SMALL_TP_MIN_N, RANGE_SMALL_TP_MIN_DELTA_PP  # V.2.11.9
    RANGE_SMALL_TP_AUTO = bool(cfg.get("range_small_tp_auto", RANGE_SMALL_TP_AUTO))
    RANGE_SMALL_TP_MIN_N = int(cfg.get("range_small_tp_min_n", RANGE_SMALL_TP_MIN_N))
    RANGE_SMALL_TP_MIN_DELTA_PP = float(cfg.get("range_small_tp_min_delta_pp", RANGE_SMALL_TP_MIN_DELTA_PP))
    if not RANGE_SMALL_TP_AUTO and _SMALL_TP_STATE.get("enabled_rule"):
        _SMALL_TP_STATE["enabled_rule"] = None  # خاموش دستی فوری
        _SMALL_TP_STATE["decision"] = "خاموش دستی (range_small_tp_auto=false)"
    global RANGE_FAIL_EXIT, RANGE_FAIL_EXIT_MIN_SEC, RANGE_FAIL_EXIT_MFE_MAX_PCT, RANGE_FAIL_EXIT_ADVERSE_R, RANGE_PROFIT_LOCK
    RANGE_FAIL_EXIT = bool(cfg.get("range_fail_exit", RANGE_FAIL_EXIT))
    RANGE_FAIL_EXIT_MIN_SEC = int(cfg.get("range_fail_exit_min_sec", RANGE_FAIL_EXIT_MIN_SEC))
    RANGE_FAIL_EXIT_MFE_MAX_PCT = float(cfg.get("range_fail_exit_mfe_max_pct", RANGE_FAIL_EXIT_MFE_MAX_PCT))
    RANGE_FAIL_EXIT_ADVERSE_R = float(cfg.get("range_fail_exit_adverse_r", RANGE_FAIL_EXIT_ADVERSE_R))
    RANGE_PROFIT_LOCK = bool(cfg.get("range_profit_lock", RANGE_PROFIT_LOCK))
    global BTC_DRIFT_STRONG_RET_PCT, BTC_DRIFT_STRONG_RET_1H_PCT  # V.2.11.7
    BTC_DRIFT_STRONG_RET_PCT = float(cfg.get("btc_drift_strong_ret_pct", BTC_DRIFT_STRONG_RET_PCT))
    BTC_DRIFT_STRONG_RET_1H_PCT = float(cfg.get("btc_drift_strong_ret_1h_pct", BTC_DRIFT_STRONG_RET_1H_PCT))
    PAPER_TRACK_BLOCKED = bool(cfg.get("paper_track_blocked", PAPER_TRACK_BLOCKED))
    global PAPER_TRACK_RR_REJECTS
    PAPER_TRACK_RR_REJECTS = bool(cfg.get("paper_track_rr_rejects", PAPER_TRACK_RR_REJECTS))
    # V.2.11.6
    global UNDERWATER_MIN_LOSS_PCT, UNDERWATER_MIN_LOSS_USDT, PAPER_TRACK_UNDERWATER_REJECTS, UNDERWATER_BLOCK_SAME_DIR
    UNDERWATER_BLOCK_SAME_DIR = bool(cfg.get("underwater_block_same_dir", UNDERWATER_BLOCK_SAME_DIR))
    UNDERWATER_MIN_LOSS_PCT = float(cfg.get("underwater_min_loss_pct", UNDERWATER_MIN_LOSS_PCT))
    UNDERWATER_MIN_LOSS_USDT = float(cfg.get("underwater_min_loss_usdt", UNDERWATER_MIN_LOSS_USDT))
    PAPER_TRACK_UNDERWATER_REJECTS = bool(cfg.get("paper_track_underwater_rejects", PAPER_TRACK_UNDERWATER_REJECTS))
    # V.2.11.3
    global ENTRY_PROTECTED_IOC, ENTRY_MAX_SLIPPAGE_PCT, ENTRY_PROTECTED_SELFTEST
    ENTRY_PROTECTED_IOC = bool(cfg.get("entry_protected_ioc", ENTRY_PROTECTED_IOC))
    ENTRY_MAX_SLIPPAGE_PCT = float(cfg.get("entry_max_slippage_pct", ENTRY_MAX_SLIPPAGE_PCT))
    ENTRY_PROTECTED_SELFTEST = bool(cfg.get("entry_protected_ioc_selftest", ENTRY_PROTECTED_SELFTEST))
    # V.2.10.100
    global PRE_ORDER_SLIP_BAND_PCT, RANGE_EXIT_IGNORE_REGIME
    PRE_ORDER_SLIP_BAND_PCT = float(cfg.get("pre_order_slip_band_pct", PRE_ORDER_SLIP_BAND_PCT))
    RANGE_EXIT_IGNORE_REGIME = bool(cfg.get("range_exit_ignore_regime", RANGE_EXIT_IGNORE_REGIME))
    return cfg

try:
    apply_runtime_settings()
except Exception:
    pass


# ردیابی ضرر روزانه
_daily_pnl: dict[str, float] = {"date": "", "pnl": 0.0}
_symbol_dir_policy_cache: dict[str, dict] = {}

# پوزیشن‌های باز ریل که خودمان باز کرده‌ایم (کلید = symbol نرمال‌شده)
_tracked: dict[str, dict[str, Any]] = {}
_supabase_restored: bool = False
# V.2.10.41 — پایداری _tracked روی دیسک (ضد پاک‌شدن با ری‌استارت/دیپلوی)
_TRACKED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tracked_positions.json")
_DAILY_PNL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "daily_pnl.json")

# تاریخچه بسته‌شده‌ها در حافظه (برای گزارش حتی اگر Supabase جدول نداشته باشد)
_history: list[dict[str, Any]] = []
# آخرین تلاش‌های ورود ریل (برای شفافیت در status-viewer)
_last_attempts: dict[str, dict[str, Any]] = {}

# --- پایداری کول‌داون پس از بستن (دیسک + اختیاری Supabase) ---
_COOLDOWN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "post_close_cooldown.json")
_close_cooldown_map: dict[str, float] = {}  # symbol -> closed_at unix
_close_cooldown_dur: dict[str, int] = {}  # symbol -> duration sec (SL vs normal vs profit)
_close_cooldown_meta: dict[str, dict] = {}  # symbol -> {kind, er, adx, exit_reason}



def _load_tracked() -> None:
    """V.2.10.41 — بازخوانی پوزیشن‌های ردیابی‌شده از دیسک بعد از ری‌استارت."""
    global _tracked
    try:
        os.makedirs(os.path.dirname(_TRACKED_FILE), exist_ok=True)
        if not os.path.isfile(_TRACKED_FILE):
            return
        with open(_TRACKED_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return
        restored = 0
        for k, v in raw.items():
            if not isinstance(v, dict):
                continue
            key = str(k).upper()
            status = str(v.get("status") or "")
            # فقط open را نگه دار؛ closedهای قدیمی را در history بگذار
            if status == "open":
                _tracked[key] = dict(v)
                restored += 1
            elif status in ("closed", "closed_external"):
                # برای آمار کوتاه‌مدت
                try:
                    _history.insert(0, dict(v))
                except Exception:
                    pass
        if len(_history) > 300:
            del _history[300:]
        if restored:
            logger.info("V.2.10.41 loaded tracked open positions: %s", list(_tracked.keys()))
    except Exception as e:
        logger.warning("load tracked positions failed: %s", e)


def _save_tracked() -> None:
    """ذخیرهٔ فوری _tracked روی دیسک."""
    try:
        os.makedirs(os.path.dirname(_TRACKED_FILE), exist_ok=True)
        payload = {}
        for k, v in _tracked.items():
            if not isinstance(v, dict):
                continue
            # کپی سبک بدون قفل/آشیانهٔ غیرقابل‌سریال
            row = {kk: vv for kk, vv in v.items() if kk not in ("closing",)}
            payload[str(k).upper()] = row
        with open(_TRACKED_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=0)
    except Exception as e:
        logger.warning("save tracked positions failed: %s", e)


async def restore_tracked_from_supabase() -> int:
    """V.2.10.42 — بازیابی پوزیشن‌های open از Supabase بعد از دیپلوی (ماندگار بین دیپلوی‌ها)."""
    global _tracked
    try:
        from database.supabase_client import get_open_real_trades
        rows = await get_open_real_trades()
    except Exception as e:
        logger.warning("restore_tracked_from_supabase fetch failed: %s", e)
        return 0
    if not rows:
        return 0
    restored = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _norm_symbol(str(row.get("symbol") or ""))
        if not key:
            continue
        # اگر از دیسک قبلاً آمده و open است، دیسک اولویت دارد مگر Supabase کامل‌تر باشد
        existing = _tracked.get(key)
        if existing and existing.get("status") == "open" and not existing.get("recovered"):
            # فقط levels را در صورت نیاز هم‌سان کن
            continue
        meta_json = row.get("meta_json") or {}
        if isinstance(meta_json, str):
            try:
                import json as _json
                meta_json = _json.loads(meta_json)
            except Exception:
                meta_json = {}
        if not isinstance(meta_json, dict):
            meta_json = {}

        opened_at = meta_json.get("opened_at_unix")
        if opened_at is None and row.get("opened_at"):
            try:
                from datetime import datetime
                oa = str(row["opened_at"]).replace("Z", "+00:00")
                opened_at = datetime.fromisoformat(oa).timestamp()
            except Exception:
                opened_at = time.time()
        try:
            opened_at = float(opened_at)
        except Exception:
            opened_at = time.time()

        meta = {
            "trade_id": row.get("trade_id") or f"sb_{key}",
            "symbol": key,
            "direction": str(row.get("direction") or "long").lower(),
            "entry": float(row.get("entry") or 0),
            "stop_loss": float(row.get("stop_loss") or 0),
            "original_stop_loss": float(
                meta_json.get("original_stop_loss") or row.get("stop_loss") or 0
            ),
            "target": float(row.get("target") or 0),
            "quantity": str(row.get("quantity") or ""),
            "margin_usdt": float(row.get("margin_usdt") or 0),
            "leverage": int(row.get("leverage") or LEVERAGE),
            "score": float(row.get("confluence_score") or meta_json.get("score") or 0),
            "opened_at": opened_at,
            "opened_at_source": meta_json.get("opened_at_source") or "supabase",
            "status": "open",
            "app_version": row.get("app_version") or meta_json.get("app_version"),  # V.2.11.6: جعل نسخه نه
            "settings_snapshot": meta_json.get("settings_snapshot"),
            "sl_client_order_id": meta_json.get("sl_client_order_id"),
            "tp_client_order_id": meta_json.get("tp_client_order_id"),
            "close_client_order_id": meta_json.get("close_client_order_id"),
            "breakeven_set": bool(meta_json.get("breakeven_set")),
            "regime_sl_tightened": bool(meta_json.get("regime_sl_tightened")),
            "profit_locked": bool(meta_json.get("profit_locked")),
            "sl_on_exchange": bool(meta_json.get("sl_on_exchange")),
            "tp_on_exchange": bool(meta_json.get("tp_on_exchange")),
            "restored_from_supabase": True,
        }
        snap = meta.get("settings_snapshot") if isinstance(meta.get("settings_snapshot"), dict) else {}
        sid = meta_json.get("strategy_id") or snap.get("strategy_id")
        if sid:
            meta["strategy_id"] = str(sid)
        for fld in ("range_low", "range_high", "range_mid", "time_stop_deadline", "initial_risk"):
            val = meta_json.get(fld)
            if val is None:
                val = snap.get(fld)
            if val is not None:
                meta[fld] = val
        # V.2.11.6 — بقیهٔ زمینهٔ معامله (نوع ورود، fill، هندسهٔ سیگنال، notional، رانش BTC، …)
        for _k, _v in (meta_json or {}).items():
            if _v is None or _k in meta or _k in ("opened_at_unix",):
                continue
            meta[_k] = _v
        _tracked[key] = meta
        restored += 1
        logger.info(
            "V.2.10.42 restored from Supabase %s opened_at=%.0f entry=%s",
            key, opened_at, meta.get("entry"),
        )
        print(
            f"[real_trade] RESTORED_FROM_SUPABASE {key} opened_at={opened_at} "
            f"sl={meta.get('stop_loss')} tp={meta.get('target')}",
            flush=True,
        )
    if restored:
        try:
            _save_tracked()
        except Exception:
            pass
    return restored



def _load_daily_pnl() -> None:
    """V.2.10.41 — daily_pnl پایدار روی دیسک."""
    global _daily_pnl
    try:
        os.makedirs(os.path.dirname(_DAILY_PNL_FILE), exist_ok=True)
        if not os.path.isfile(_DAILY_PNL_FILE):
            return
        with open(_DAILY_PNL_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict) and raw.get("date"):
            _daily_pnl = {"date": str(raw["date"]), "pnl": float(raw.get("pnl") or 0)}
            # اگر فایل دیسک با باگ .81 خراب شده (|pnl| غیرواقعی)، صفر کن
            try:
                if abs(float(_daily_pnl.get("pnl") or 0)) > 25.0:
                    logger.warning("reset absurd daily_pnl from disk: %s", _daily_pnl)
                    _daily_pnl = {"date": str(raw.get("date") or ""), "pnl": 0.0}
            except Exception:
                pass
            logger.info("loaded daily_pnl: %s", _daily_pnl)
    except Exception as e:
        logger.warning("load daily_pnl failed: %s", e)


def _save_daily_pnl() -> None:
    try:
        os.makedirs(os.path.dirname(_DAILY_PNL_FILE), exist_ok=True)
        with open(_DAILY_PNL_FILE, "w", encoding="utf-8") as f:
            json.dump(_daily_pnl, f)
    except Exception as e:
        logger.warning("save daily_pnl failed: %s", e)


def _load_close_cooldowns() -> None:
    """بارگذاری کول‌داون‌های پس از بستن از دیسک."""
    global _close_cooldown_map, _close_cooldown_dur, _close_cooldown_meta
    try:
        os.makedirs(os.path.dirname(_COOLDOWN_FILE), exist_ok=True)
        if not os.path.isfile(_COOLDOWN_FILE):
            return
        with open(_COOLDOWN_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        now = time.time()
        out_ts: dict[str, float] = {}
        out_dur: dict[str, int] = {}
        out_meta: dict[str, dict] = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                key = str(k).upper()
                if isinstance(v, dict):
                    ts = float(v.get("ts") or 0)
                    dur = int(v.get("dur") or POST_CLOSE_COOLDOWN_SECONDS)
                    meta = {mk: v[mk] for mk in ("kind", "er", "adx", "exit_reason") if mk in v}
                else:
                    ts = float(v or 0)
                    dur = POST_CLOSE_COOLDOWN_SECONDS
                    meta = {}
                max_keep = max(
                    POST_CLOSE_COOLDOWN_SECONDS,
                    POST_SL_COOLDOWN_SECONDS,
                    POST_PROFIT_COOLDOWN_SECONDS,
                    POST_PROFIT_HYST_WINDOW_SEC,
                ) * 2
                if ts > 0 and now - ts < max_keep:
                    out_ts[key] = ts
                    out_dur[key] = dur
                    if meta:
                        out_meta[key] = meta
        _close_cooldown_map = out_ts
        _close_cooldown_dur = out_dur
        _close_cooldown_meta = out_meta
        if out_ts:
            logger.info("loaded post-close cooldowns: %s", list(out_ts.keys()))
    except Exception as e:
        logger.warning("load post-close cooldown file failed: %s", e)


def _save_close_cooldowns() -> None:
    try:
        os.makedirs(os.path.dirname(_COOLDOWN_FILE), exist_ok=True)
        now = time.time()
        max_keep = max(
            POST_CLOSE_COOLDOWN_SECONDS,
            POST_SL_COOLDOWN_SECONDS,
            POST_PROFIT_COOLDOWN_SECONDS,
            POST_PROFIT_HYST_WINDOW_SEC,
        ) * 2
        payload = {}
        for k, ts in list(_close_cooldown_map.items()):
            if now - float(ts) < max_keep:
                row = {
                    "ts": float(ts),
                    "dur": int(_close_cooldown_dur.get(k) or POST_CLOSE_COOLDOWN_SECONDS),
                }
                meta = _close_cooldown_meta.get(k) or {}
                if meta:
                    row.update(meta)
                payload[k] = row
        _close_cooldown_map.clear()
        _close_cooldown_dur.clear()
        _close_cooldown_meta.clear()
        for k, row in payload.items():
            _close_cooldown_map[k] = float(row["ts"])
            _close_cooldown_dur[k] = int(row["dur"])
            meta = {mk: row[mk] for mk in ("kind", "er", "adx", "exit_reason") if mk in row}
            if meta:
                _close_cooldown_meta[k] = meta
        with open(_COOLDOWN_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception as e:
        logger.warning("save post-close cooldown file failed: %s", e)


def _is_sl_exit_reason(reason: str | None) -> bool:
    """نام دلیل شبیه SL (شامل breakeven_sl) — برای نمایش/legacy."""
    r = (reason or "").lower()
    return (
        "stop_loss" in r
        or r.endswith("_sl")
        or "no_exchange_sl" in r
        or "force_close_no_sl" in r
        or r == "sl"
        or "breakeven" in r
    )


def _is_hard_sl_for_guards(reason: str | None, pnl: float | None = None) -> bool:
    """V.2.10.95: فقط ضرر واقعی استاپ برای cluster/global/symbol-SL.
    BE و خروج نزدیک صفر (scratch) قفل ۳ ساعته نمی‌سازند.
    """
    r = (reason or "").lower()
    if "breakeven" in r or "profit_floor" in r or r in ("be", "scratch", "breakeven_sl", "breakeven_exit"):
        return False
    if not (
        "stop_loss" in r
        or (r.endswith("_sl") and "breakeven" not in r)
        or "no_exchange_sl" in r
        or "force_close_no_sl" in r
        or "emergency_loss" in r
        or r == "sl"
    ):
        return False
    if pnl is not None:
        try:
            if float(pnl) >= -0.05:
                return False
        except (TypeError, ValueError):
            pass
    return True


def _is_soft_market_reject(reason: str | None) -> bool:
    """ردهای موقت رژیم/تأیید — نباید ۱۲ دقیقه ورود را بعد از بهبود بازار نگه دارند."""
    r = (reason or "").lower()
    markers = (
        "chop", "weak", "btc=", "توقف خودکار", "رژیم",
        "anti-noise", "تأیید", "کندل", "candle",
        "adx", "overext", "تعقیب", "noise", "چاپ",
        "m15", "م15", "parse", "داده ناکافی", "fail-closed",
        "ci ", "ci≥", "er ", "er_noise", "htf", "pre_order", "entry_ioc_unfilled",
    )
    return any(m in r for m in markers)


def _is_profit_exit_reason(reason: str | None) -> bool:
    """V.2.10.59+: خروج‌های سودده که باید کول‌داون طولانی‌تر بگیرند."""
    r = (reason or "").lower()
    return (
        "float_profit" in r
        or "profit_lock" in r
        or "take_profit" in r
        or "stale_profit" in r
        or r in ("tp", "exchange_take_profit", "exchange_take_profit_approx")
    )


def _mark_symbol_closed(
    symbol: str,
    exit_reason: str | None = None,
    regime_snapshot: dict | None = None,
    pnl: float | None = None,
    at: float | None = None,
) -> None:
    """ثبت زمان بستن نماد برای کول‌داون پایدار.
    V.2.10.47: بعد از SL مدت طولانی‌تر.
    V.2.10.59: بعد از برد (float/TP/lock) مدت POST_PROFIT_COOLDOWN_SECONDS.
    V.2.10.75: هر بستن با PnL منفی → POST_NEGATIVE_COOLDOWN (۴h) حتی اگر SCRATCH باشد.
    """
    key = _norm_symbol(symbol)
    # V.2.10.99: کول‌داون از «زمان واقعی بستن» حساب می‌شود، نه لحظهٔ کشف بعد از ری‌استارت
    ts = time.time()
    try:
        if at is not None and 0 < float(at) <= ts:
            ts = float(at)
    except (TypeError, ValueError):
        ts = time.time()
    try:
        pnl_f = float(pnl) if pnl is not None else None
    except (TypeError, ValueError):
        pnl_f = None
    is_neg = pnl_f is not None and pnl_f <= float(NEGATIVE_PNL_THRESHOLD_USDT)
    is_hard_sl = _is_hard_sl_for_guards(exit_reason, pnl_f)
    is_be_like = (
        ("breakeven" in str(exit_reason or "").lower())
        or (pnl_f is not None and float(pnl_f) >= -0.05 and _is_sl_exit_reason(exit_reason) and not is_hard_sl)
    )
    rlow = str(exit_reason or "").lower()
    if rlow in ("range_time_stop", "range_invalidated", "range_fail_exit", "range_small_tp",
                "range_profit_floor", "profit_floor_sl", "rs_time_stop", "tsmom_time_stop", "tsmom_trend_exit", "rsi_time_stop",
                "rsi_time_stop", "rs_trail_close", "rs_trail_stop"):
        # زمان‌محور یا ابطال رنج می‌تواند سود یا زیان باشد؛ منفی‌بودن ≠ استاپ سخت
        if pnl_f is not None and pnl_f > 0:
            dur = int(RANGE_WIN_COOLDOWN_SEC)
            kind = "range_win"
            label = "برد رنج"
        else:
            dur = int(POST_CLOSE_COOLDOWN_SECONDS)
            kind = "range_exit"
            label = "خروج رنج"
    elif is_hard_sl or (is_neg and not is_be_like):
        # ضرر واقعی / SL سخت
        dur = max(int(POST_SL_COOLDOWN_SECONDS), int(POST_NEGATIVE_COOLDOWN_SECONDS if is_neg else POST_SL_COOLDOWN_SECONDS))
        if is_neg and not is_hard_sl:
            kind = "negative"
            label = "منفی"
        else:
            kind = "sl"
            label = "SL"
    elif is_be_like:
        # V.2.10.95: BE/scratch → فقط کول‌داون عادی بستن (نه ۴h منفی)
        dur = POST_CLOSE_COOLDOWN_SECONDS
        kind = "breakeven"
        label = "BE"
    elif _is_profit_exit_reason(exit_reason):
        dur = POST_PROFIT_COOLDOWN_SECONDS
        kind = "profit"
        label = "profit"
    else:
        dur = POST_CLOSE_COOLDOWN_SECONDS
        kind = "close"
        label = "close"
    if time.time() - ts >= float(dur):
        # V.2.10.99: این کول‌داون قبلاً تمام شده (بستن قدیمی) — چیزی ثبت نکن
        logger.info("cooldown skipped %s: close at %.0f already older than %ss", key, ts, dur)
        return
    _close_cooldown_map[key] = ts
    _close_cooldown_dur[key] = int(dur)
    meta: dict = {"kind": kind, "exit_reason": str(exit_reason or ""), "pnl": pnl_f}
    if isinstance(regime_snapshot, dict):
        try:
            if regime_snapshot.get("er") is not None:
                meta["er"] = float(regime_snapshot["er"])
            if regime_snapshot.get("adx") is not None:
                meta["adx"] = float(regime_snapshot["adx"])
        except Exception:
            pass
    _close_cooldown_meta[key] = meta
    _save_close_cooldowns()
    try:
        _record_attempt(key, False, f"بسته شد — کول‌داون پس از {label} ({dur}s)")
    except Exception:
        pass
    try:
        from database.supabase_client import save_real_cooldown
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(save_real_cooldown(key, ts))
    except Exception:
        pass


def _post_close_remaining(symbol: str) -> int:
    """ثانیه‌های باقی‌مانده کول‌داون پس از بستن؛ ۰ یعنی آزاد."""
    key = _norm_symbol(symbol)
    ts = _close_cooldown_map.get(key)
    if not ts:
        return 0
    dur = int(_close_cooldown_dur.get(key) or POST_CLOSE_COOLDOWN_SECONDS)
    left = int(dur - (time.time() - float(ts)))
    return max(0, left)


def _check_post_profit_hysteresis(symbol: str, current_er: float | None, current_adx: float | None) -> tuple[bool, str]:
    """V.2.10.59: بعد از برد، در پنجرهٔ کوتاه اگر کیفیت رژیم افت کرده باشد ورود را رد کن.
    Returns (allowed, reason).
    """
    if not ENABLE_POST_PROFIT_HYSTERESIS:
        return True, ""
    key = _norm_symbol(symbol)
    ts = _close_cooldown_map.get(key)
    meta = _close_cooldown_meta.get(key) or {}
    if not ts or meta.get("kind") != "profit":
        return True, ""
    age = time.time() - float(ts)
    if age < 0 or age > POST_PROFIT_HYST_WINDOW_SEC:
        return True, ""
    # هنوز داخل کول‌داون زمانی؟ همانجا بلاک می‌شود؛ این چک برای بعد از اتمام dur هم هست اگر dur < window
    base_er = meta.get("er")
    base_adx = meta.get("adx")
    try:
        if base_er is not None and current_er is not None and float(base_er) > 0:
            if float(current_er) < float(base_er) * POST_PROFIT_HYST_MIN_ER_RATIO:
                return False, (
                    f"هیسترزیس پس‌از‌برد {key}: ER={float(current_er):.3f} < "
                    f"{float(base_er)*POST_PROFIT_HYST_MIN_ER_RATIO:.3f} (baseline برد {float(base_er):.3f})"
                )
        if base_adx is not None and current_adx is not None and float(base_adx) > 0:
            if float(current_adx) < float(base_adx) * POST_PROFIT_HYST_MIN_ADX_RATIO:
                return False, (
                    f"هیسترزیس پس‌از‌برد {key}: ADX={float(current_adx):.1f} < "
                    f"{float(base_adx)*POST_PROFIT_HYST_MIN_ADX_RATIO:.1f} (baseline برد {float(base_adx):.1f})"
                )
    except Exception:
        return True, ""
    return True, ""


# بارگذاری اولیه
try:
    _load_close_cooldowns()
except Exception:
    pass


# --- V.2.10.17 risk guards state ---
_RISK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "risk_guards.json")
_global_sl_times: list[float] = []
_global_sl_lock_until: float = 0.0
_rolling_symbol_pnl: dict[str, list] = {}  # symbol -> [[ts, pnl], ...]
_symbol_low_profit_lock_until: dict[str, float] = {}
_symbol_sl_times: dict[str, list] = {}  # symbol -> [ts, ...]
_symbol_sl_lock_until: dict[str, float] = {}


def _load_risk_guards() -> None:
    global _global_sl_times, _global_sl_lock_until, _rolling_symbol_pnl, _symbol_low_profit_lock_until
    global _symbol_sl_times, _symbol_sl_lock_until
    try:
        os.makedirs(os.path.dirname(_RISK_FILE), exist_ok=True)
        if not os.path.isfile(_RISK_FILE):
            return
        with open(_RISK_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        now = time.time()
        # V.2.10.86: قفل سراسری ورود / cluster هرگز از دیسک لود نمی‌شود (مگر PERSIST_GLOBAL_ENTRY_LOCK)
        # تا بعد از هر دیپلوی/ریست Space دوباره pause چندساعته نیاید.
        _raw_sl_times = [float(x) for x in (raw.get("global_sl_times") or [])]
        _saved_lock = float(raw.get("global_sl_lock_until") or 0)
        if PERSIST_GLOBAL_ENTRY_LOCK and not CLEAR_GLOBAL_ENTRY_LOCK_ON_BOOT:
            _keep_win = max(GLOBAL_SL_LOOKBACK_SEC, CLUSTER_SL_LOOKBACK_SEC) * 2
            _global_sl_times = [x for x in _raw_sl_times if now - x < _keep_win]
            _global_sl_lock_until = _saved_lock
        else:
            if _saved_lock > now or _raw_sl_times:
                logger.warning(
                    "V.2.10.86 BOOT: drop persisted global lock (was %.0fs, %d times) — session-only lock",
                    max(0, _saved_lock - now), len(_raw_sl_times),
                )
            _global_sl_times = []
            _global_sl_lock_until = 0.0
        _symbol_low_profit_lock_until = {
            str(k).upper(): float(v)
            for k, v in (raw.get("symbol_low_profit_lock_until") or {}).items()
            if float(v) > now
        }
        _symbol_sl_lock_until = {
            str(k).upper(): float(v)
            for k, v in (raw.get("symbol_sl_lock_until") or {}).items()
            if float(v) > now
        }
        sst = {}
        for k, rows in (raw.get("symbol_sl_times") or {}).items():
            kept = [float(x) for x in rows if now - float(x) < SYMBOL_SL_LOCK_LOOKBACK_SEC * 2]
            if kept:
                sst[str(k).upper()] = kept
        _symbol_sl_times = sst
        rp = {}
        for k, rows in (raw.get("rolling_symbol_pnl") or {}).items():
            kept = [[float(a), float(b)] for a, b in rows if now - float(a) < ROLLING_LOW_PROFIT_WINDOW_SEC * 2]
            if kept:
                rp[str(k).upper()] = kept
        _rolling_symbol_pnl = rp
        logger.info(
            "loaded risk guards: global_sl=%s lock_until=%.0f low_profit_locks=%s clear_on_boot=%s",
            len(_global_sl_times), _global_sl_lock_until, list(_symbol_low_profit_lock_until.keys()),
            CLEAR_GLOBAL_ENTRY_LOCK_ON_BOOT,
        )
        if CLEAR_GLOBAL_ENTRY_LOCK_ON_BOOT:
            try:
                _save_risk_guards()
            except Exception:
                pass
    except Exception as e:
        logger.warning("load risk guards failed: %s", e)


def _save_risk_guards() -> None:
    try:
        os.makedirs(os.path.dirname(_RISK_FILE), exist_ok=True)
        now = time.time()
        payload = {
            # V.2.10.86: پیش‌فرض روی دیسک قفل سراسری ذخیره نشود
            "global_sl_times": (
                [x for x in _global_sl_times if now - x < GLOBAL_SL_LOOKBACK_SEC * 2]
                if PERSIST_GLOBAL_ENTRY_LOCK else []
            ),
            "global_sl_lock_until": (_global_sl_lock_until if PERSIST_GLOBAL_ENTRY_LOCK else 0),
            "symbol_low_profit_lock_until": {
                k: v for k, v in _symbol_low_profit_lock_until.items() if v > now
            },
            "symbol_sl_lock_until": {
                k: v for k, v in _symbol_sl_lock_until.items() if v > now
            },
            "symbol_sl_times": {
                k: [x for x in rows if now - float(x) < SYMBOL_SL_LOCK_LOOKBACK_SEC * 2]
                for k, rows in _symbol_sl_times.items()
            },
            "rolling_symbol_pnl": {
                k: [[a, b] for a, b in rows if now - a < ROLLING_LOW_PROFIT_WINDOW_SEC * 2]
                for k, rows in _rolling_symbol_pnl.items()
            },
        }
        with open(_RISK_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception as e:
        logger.warning("save risk guards failed: %s", e)


def _register_closed_trade(
    symbol: str, approx_pnl: float, exit_reason: str = "", at: float | None = None,
) -> None:
    """ثبت بستن برای قفل سراسری SL و قفل کم‌سود نماد.
    V.2.10.99: at = زمان واقعی بستن (برای بستن‌هایی که بعد از ری‌استارت کشف می‌شوند).
    بستن قبل از boot وارد cluster/global نمی‌شود (همان boot-grace) و قفل نماد از همان زمان می‌گذرد.
    """
    global _global_sl_lock_until
    key = _norm_symbol(symbol)
    now = time.time()
    try:
        if at is not None and 0 < float(at) <= now:
            now = float(at)
    except (TypeError, ValueError):
        now = time.time()
    reason = (exit_reason or "").lower()
    # V.2.10.95: فقط HARD SL برای cluster/global/symbol — BE و near-zero نه
    is_sl = _is_hard_sl_for_guards(exit_reason, approx_pnl)
    # V.2.10.76.1 — NEGATIVE CLOSE ≠ HARD SL
    # V.2.10.95 — BE/scratch هم شمارنده SL را پر نمی‌کند
    # rolling pnl
    rows = _rolling_symbol_pnl.setdefault(key, [])
    rows.append([now, float(approx_pnl or 0)])
    rows[:] = [r for r in rows if now - r[0] < ROLLING_LOW_PROFIT_WINDOW_SEC * 2]
    # low-profit lock
    recent = [r for r in rows if now - r[0] <= ROLLING_LOW_PROFIT_WINDOW_SEC]
    if len(recent) >= ROLLING_LOW_PROFIT_MIN_TRADES:
        s = sum(r[1] for r in recent)
        if s < 0:
            _symbol_low_profit_lock_until[key] = now + ROLLING_LOW_PROFIT_LOCK_SEC
            logger.warning(
                "LOW-PROFIT LOCK %s for %ss (sum_pnl=%.4f over %d trades)",
                key, ROLLING_LOW_PROFIT_LOCK_SEC, s, len(recent),
            )
    # global SL streak + V.2.10.84 cluster SL
    if is_sl:
        # فقط SLهای همین session (بعد از boot) — reconcile قدیمی بعد از دیپلوی قفل ۳h نمی‌سازد
        if now < float(_SESSION_START_TS) + 90:
            # ۹۰ثانیه اول بعد از boot: فقط لاگ، بدون cluster (جلوگیری از رگبار external close)
            logger.info(
                "V.2.10.86 skip global cluster during boot grace (%ss) symbol=%s reason=%s",
                int(now - _SESSION_START_TS), key, reason[:40],
            )
        else:
            _global_sl_times.append(now)
            _keep = max(GLOBAL_SL_LOOKBACK_SEC, CLUSTER_SL_LOOKBACK_SEC) * 2
            _global_sl_times[:] = [
                x for x in _global_sl_times
                if now - x <= _keep and x >= float(_SESSION_START_TS)
            ]
            _in_global = [x for x in _global_sl_times if now - x <= GLOBAL_SL_LOOKBACK_SEC]
            if len(_in_global) >= GLOBAL_SL_LIMIT:
                _global_sl_lock_until = max(_global_sl_lock_until, now + GLOBAL_SL_LOCK_SEC)
                logger.error(
                    "GLOBAL SL GUARD: %d SL in %ds → lock all entries %ds",
                    len(_in_global), GLOBAL_SL_LOOKBACK_SEC, GLOBAL_SL_LOCK_SEC,
                )
            _in_cluster = [x for x in _global_sl_times if now - x <= CLUSTER_SL_LOOKBACK_SEC]
            if len(_in_cluster) >= CLUSTER_SL_LIMIT:
                _global_sl_lock_until = max(_global_sl_lock_until, now + CLUSTER_SL_LOCK_SEC)
                logger.error(
                    "CLUSTER SL GUARD: %d hard SL in %ds → pause entries %ds",
                    len(_in_cluster), CLUSTER_SL_LOOKBACK_SEC, CLUSTER_SL_LOCK_SEC,
                )
        # V.2.10.47: قفل نماد بعد از N استاپ در lookback
        rows_sl = _symbol_sl_times.setdefault(key, [])
        rows_sl.append(now)
        rows_sl[:] = [x for x in rows_sl if now - float(x) <= SYMBOL_SL_LOCK_LOOKBACK_SEC]
        if len(rows_sl) >= SYMBOL_SL_LOCK_COUNT:
            _symbol_sl_lock_until[key] = now + SYMBOL_SL_LOCK_SEC
            logger.warning(
                "SYMBOL SL LOCK %s for %ss (%d SL in %ds)",
                key, SYMBOL_SL_LOCK_SEC, len(rows_sl), SYMBOL_SL_LOCK_LOOKBACK_SEC,
            )
    _save_risk_guards()


def _global_sl_remaining() -> int:
    global _global_sl_lock_until
    # اگر قفل از session قبل مانده یا بدون SL همین session — صفر کن
    if _global_sl_lock_until > time.time():
        sess_sl = [x for x in _global_sl_times if x >= float(_SESSION_START_TS)]
        if not sess_sl and not PERSIST_GLOBAL_ENTRY_LOCK:
            _global_sl_lock_until = 0.0
            return 0
    left = int(_global_sl_lock_until - time.time())
    return max(0, left)


def _low_profit_remaining(symbol: str) -> int:
    key = _norm_symbol(symbol)
    until = _symbol_low_profit_lock_until.get(key) or 0
    left = int(until - time.time())
    return max(0, left)


def _symbol_sl_lock_remaining(symbol: str) -> int:
    key = _norm_symbol(symbol)
    until = float(_symbol_sl_lock_until.get(key) or 0)
    left = int(until - time.time())
    return max(0, left)


try:
    _load_risk_guards()
except Exception:
    pass

# V.2.10.85.1: تضمین نهایی — بعد از هر boot قفل سراسری ورود صفر
try:
    if CLEAR_GLOBAL_ENTRY_LOCK_ON_BOOT and _global_sl_lock_until > time.time():
        logger.warning("V.2.10.85 BOOT final: force-clear global_sl_lock_until")
        _global_sl_lock_until = 0.0
        _global_sl_times = []
        _save_risk_guards()
except Exception:
    pass


try:
    _load_tracked()
    _load_daily_pnl()
except Exception as e:
    logger.warning("boot tracked/daily load failed: %s", e)






def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def record_realized_pnl(pnl: float) -> None:
    """مقدار موقت تا بازسازی بعدی از صرافی (V.2.10.100: بازسازی جایگزین می‌کند، جمع نمی‌زند)."""
    d = _today()
    if _daily_pnl["date"] != d:
        _daily_pnl["date"] = d
        _daily_pnl["pnl"] = 0.0
    _daily_pnl["pnl"] += float(pnl)
    _daily_pnl["source"] = "provisional"
    try:
        _save_daily_pnl()
    except Exception:
        pass


def daily_loss_breached() -> bool:
    d = _today()
    if _daily_pnl["date"] != d:
        return False
    return _daily_pnl["pnl"] <= -abs(DAILY_LOSS_LIMIT_USDT)


def _open_sl_risk_usdt() -> float:
    """V.2.36.2 — ضرر تخمینی همهٔ پوزیشن‌های باز اگر به حد ضرر فعلی‌شان بخورند (SL در سود/سربه‌سر ⇒ ۰)."""
    tot = 0.0
    for m in list(_tracked.values()):
        if not isinstance(m, dict) or m.get("status") != "open":
            continue
        try:
            e = float(m.get("fill_entry") if m.get("fill_entry") is not None else m.get("entry") or 0)
            sl = float(m.get("stop_loss") or 0)
            n = float(m.get("notional_actual") or 25.0)
        except (TypeError, ValueError):
            continue
        if e <= 0 or sl <= 0:
            continue
        long_ = str(m.get("direction") or "long") == "long"
        if (long_ and sl >= e) or (not long_ and sl <= e):
            continue
        tot += n * (abs(e - sl) / e * 100.0 + ROUND_TRIP_FRICTION_PCT) / 100.0
    return tot


def _committed_risk_block(est_new: float) -> str | None:
    """V.2.36.2 — مناظرهٔ پیشنهاددهنده/منتقد (day-trader-skill): سقف ضرر روزانه فقط ضرر بسته‌شده را می‌شمرد؛
    با ۲ پوزیشن SL ۱۰٪ (۲ × ۲٫۵۵$) ضرر ممکن روز از ۳$ رد می‌شد. حالا: ضرر امروز + ریسک SLهای باز + ریسک ورود تازه."""
    realized = float(_daily_pnl.get("pnl") or 0) if _daily_pnl.get("date") == _today() else 0.0
    if not daily_loss_breached():   # هم‌خوان با گیت سقف ضرر روزانه (اگر آن پر شده بود، این‌جا نمی‌رسیدیم)
        realized = max(realized, -abs(DAILY_LOSS_LIMIT_USDT) + 0.01)
    committed = min(0.0, realized) - _open_sl_risk_usdt() - max(0.0, float(est_new or 0))
    if committed < -abs(DAILY_LOSS_LIMIT_USDT) - 1e-9:
        return (f"ریسک کل روز {committed:+.2f}$ (بسته {realized:+.2f}، SL باز {_open_sl_risk_usdt():.2f}، "
                f"ورود تازه {est_new:.2f}) از سقف ضرر روزانه {DAILY_LOSS_LIMIT_USDT}$ بیشتر می‌شود")
    return None


DAILY_PNL_REFRESH_MIN_SEC = 60.0
_daily_pnl_refreshed_at = 0.0


async def _refresh_daily_pnl_from_exchange(force: bool = False) -> bool:
    """V.2.10.100 — PnL روزانه (UTC) = جمع PnL خالص پوزیشن‌های بسته‌شدهٔ امروز در خود صرافی.

    در .99 اگر مقدار امروز غیرصفر بود اصلاً صرافی خوانده نمی‌شد، و بستن‌های سمت صرافی (SL/TP/BE)
    هیچ‌وقت record نمی‌شدند → PnL روزانه و سقف ضرر روزانه این زیان‌ها را نمی‌دیدند.
    حالا هر بار (حداکثر هر ۶۰ ثانیه، یا فوری با force) کل امروز از صرافی بازسازی و جایگزین می‌شود؛
    record_realized_pnl فقط مقدار موقت بین دو بازسازی است، پس شمارش تکراری ممکن نیست.
    خطای صرافی → مقدار قبلی دست نمی‌خورد. خروجی: True اگر بازسازی انجام شد.
    """
    global _daily_pnl, _daily_pnl_refreshed_at
    now = time.time()
    if not force and now - float(_daily_pnl_refreshed_at or 0) < DAILY_PNL_REFRESH_MIN_SEC:
        return False
    rows = await _exchange_history_rows(limit=100, max_age=0 if force else 15)
    if rows is None:
        return False
    d = _today()
    try:
        import calendar
        day_start = calendar.timegm(time.strptime(d + " 00:00:00", "%Y-%m-%d %H:%M:%S"))
    except Exception:
        day_start = now - 86400
    day_end = day_start + 86400
    seen: set[str] = set()
    total = 0.0
    n = 0
    for r in rows:
        if str(r.get("leverage") or "") not in ("", "5", "5.0"):
            continue
        ts = float(r.get("closed_ts") or 0)
        if ts < day_start or ts >= day_end:
            continue
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        total += float(r.get("pnl") or 0)
        n += 1
    _daily_pnl = {
        "date": d,
        "pnl": round(total, 6),
        "source": "exchange",
        "n_closes": n,
        "refreshed_at": now,
    }
    _daily_pnl_refreshed_at = now
    try:
        _save_daily_pnl()
    except Exception:
        pass
    return True


async def _hydrate_daily_pnl_from_exchange() -> None:
    """سازگاری با فراخوانی‌های قدیمی (.53) — حالا همیشه از صرافی (با محدودیت نرخ)."""
    try:
        await _refresh_daily_pnl_from_exchange(force=False)
    except Exception as e:
        logger.warning("refresh daily_pnl failed: %s", e)


def _norm_symbol(symbol: str) -> str:
    s = (symbol or "").upper().replace("-SWAP-USDT", "").replace("USDT", "").strip()
    return s


async def _available_balance() -> float:
    bal = await toobit_private.get_futures_balance()
    if isinstance(bal, dict) and bal.get("error"):
        return 0.0
    return toobit_private.parse_usdt_available(bal)


async def _equity_balance() -> float:
    """کل موجودی (equity) نه فقط آزاد — برای سقف پوزیشن و سایز پایه."""
    bal = await toobit_private.get_futures_balance()
    if isinstance(bal, dict) and bal.get("error"):
        return 0.0
    return toobit_private.parse_usdt_equity(bal)


async def _open_positions_count() -> tuple[int, list | None]:
    """V.2.10.94: در خطای API مقدار rows=None برمی‌گردد تا manager اشتباه «بسته خارجی» نزند."""
    pos = await toobit_private.get_futures_positions()
    if isinstance(pos, dict) and pos.get("error"):
        return 99, None
    if pos is None:
        return 99, None
    rows = pos.get("data") or pos.get("list") or [] if isinstance(pos, dict) else pos
    if isinstance(pos, list):
        rows = pos
    if not isinstance(rows, list):
        # پاسخ نامعتبر — نه لیست خالی قطعی
        return 99, None
    open_rows = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        qty = toobit_private.parse_position_qty(r)
        if qty > 0:
            open_rows.append(r)
    return len(open_rows), open_rows


# ─────────────────────────────────────────────────────────────
# V.2.11.0 — هم‌راستایی با رانش کوتاه‌مدت BTC
# شاهد (۱ اکتبر): BTC در ۲ ساعت بالا رفت (stack ۱h از bear به bull) در حالی که برچسب رژیمش WEAK/CHOP ماند.
# موتور رنج سقف آلت‌ها را شورت کرد (۳ از ۴ SL: AVAX، ADA، OP؛ هیچ‌کدام بیش از +0.16٪ سود شناور نگرفتند)،
# قفل خوشه‌ای ۳ ساعته همهٔ ورودها را بست، و ده‌ها سیگنال LONG روند (امتیاز ۹۰–۱۰۰) به‌خاطر pause رد شدند.
# ۱) رنجِ خلاف رانش تأییدشدهٔ BTC باز نمی‌شود (به‌جایش «کاغذی» دنبال می‌شود تا اثر فیلتر سنجیده شود).
# ۲) سیگنال روندِ هم‌جهت رانش، در pause هم با سایز weak_trend مجاز است (نماد TREND یا WEAK با conf≥۶۰).
# ۳) سقف هم‌جهت برای جهتِ هم‌راستا با رانش ۲ است (به‌جای ۱ در BTC ضعیف).
# رانش «تأییدشده» = stack ۱h بیت‌کوین + بازده ۲ ساعت اخیر (کندل‌های بستهٔ ۱۵m) هر دو هم‌جهت.
# ─────────────────────────────────────────────────────────────
BTC_DRIFT_GUARD_RANGE = True
BTC_DRIFT_MIN_RET_PCT = 0.30
BTC_DRIFT_WINDOW_MIN = 120
BTC_DRIFT_TREND_FOLLOW = True
BTC_DRIFT_FOLLOW_MIN_SYMBOL_CONF = 60.0
BTC_DRIFT_SAME_DIR_CAP = 2
BTC_DRIFT_CACHE_SEC = 60.0
# V.2.11.7 — «حرکت قوی» بدون نیاز به stack: stack ۱h بیت‌کوین کند است و در برگشت‌های تند دیر می‌چرخد.
# ۲ اکتبر ۱۸:۳۲–۱۹:۴۹ تهران: BTC −۰٫۹٪ تا −۱٫۶٪ در ۲ ساعت ولی stack هنوز bull ⇒ رانش «none» ⇒
# ۵ LONG رنج (ETH، SOL، ATOM، DOGE، XRP) در سقوط باز شدند: خالص ≈ −۰٫۴۲$ و قفل خوشه‌ای ۳ ساعته.
BTC_DRIFT_STRONG_RET_PCT = 0.60      # |بازده ۲ساعت| ≥ این ⇒ رانش در جهت حرکت، بدون توجه به stack
BTC_DRIFT_STRONG_RET_1H_PCT = 0.45   # |بازده ۱ساعت| ≥ این ⇒ همان (برای شروع یک حرکت تند)
PAPER_TRACK_BLOCKED = True
# V.2.11.8 — قواعد خروج رنج بر پایهٔ ۲۰ معامله با مسیر ۱m (exit_whatif):
#   «بستن ورود ناموفق» در هر ۶ بازبینی بهترین بود (۳ کمک، ۰ ضرر) ⇒ روشن
#   قفل سود ۷۲٪ هیچ‌بار کمک نکرد؛ هر ۵ برد قفل‌شده به TP می‌رسیدند (≈ −۱٫۰۶٪) ⇒ برای رنج خاموش (TP صرافی = میانهٔ رنج)
#   سربه‌سر 0.8R کمک کرد (ARB شورت −۰٫۶۸ → +۰٫۰۸) ⇒ بدون تغییر
RANGE_FAIL_EXIT = True
RANGE_FAIL_EXIT_MIN_SEC = 600
RANGE_FAIL_EXIT_MFE_MAX_PCT = 0.15
RANGE_FAIL_EXIT_ADVERSE_R = 0.30
RANGE_PROFIT_LOCK = False
PAPER_FEE_PCT = 0.08          # کارمزد رفت‌وبرگشت اندازه‌گیری‌شده (نه friction محافظه‌کار ۰٫۱۸)
PAPER_NOTIONAL_USDT = 25.0
PAPER_MAX_OPEN = 24   # V.2.18.2/2.19.0 — کاغذیِ ردشده + آزمون رو به جلو
PAPER_REOPEN_COOLDOWN_SEC = 900
_BTC_DRIFT_CACHE: dict[str, Any] = {"ts": 0.0, "state": None}
_paper_open_map: dict[str, dict] = {}
_paper_closed: list[dict] = []
_PAPER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "paper_trades.json")


async def _btc_drift_state(force: bool = False) -> dict:
    """رانش کوتاه‌مدت BTC: dir ∈ {up, down, none}. خطای داده → none (هیچ چیز مسدود نمی‌شود)."""
    now = time.time()
    st = _BTC_DRIFT_CACHE.get("state")
    if not force and st is not None and now - float(_BTC_DRIFT_CACHE.get("ts") or 0) < BTC_DRIFT_CACHE_SEC:
        return dict(st)
    out: dict[str, Any] = {"dir": "none", "ret_pct": None, "h1": None, "window_min": int(BTC_DRIFT_WINDOW_MIN),
                           "min_ret_pct": float(BTC_DRIFT_MIN_RET_PCT), "ts": now}
    try:
        from indicators import get_btc_regime_snapshot
        snap = get_btc_regime_snapshot() or {}
        out["h1"] = snap.get("h1")
        out["btc_label"] = snap.get("label")
        out["btc_conf"] = snap.get("confidence")
    except Exception:
        pass
    try:
        bars = max(2, int(round(float(BTC_DRIFT_WINDOW_MIN) / 15.0)))
        kl = await toobit_market.get_klines("BTC", "15m", limit=bars + 3)
        closes = [float(x) for x in list(kl["close"])] if kl is not None and len(kl) > bars else []
        if len(closes) > bars and closes[-1 - bars] > 0:
            ret = (closes[-1] / closes[-1 - bars] - 1.0) * 100.0
            out["ret_pct"] = round(ret, 4)
            ret1 = None
            if len(closes) > 4 and closes[-5] > 0:
                ret1 = (closes[-1] / closes[-5] - 1.0) * 100.0
                out["ret_1h_pct"] = round(ret1, 4)
            h1 = str(out.get("h1") or "").lower()
            strong = float(BTC_DRIFT_STRONG_RET_PCT)
            strong1 = float(BTC_DRIFT_STRONG_RET_1H_PCT)
            if h1 == "long" and ret >= float(BTC_DRIFT_MIN_RET_PCT):
                out["dir"], out["why"] = "up", "stack+ret"
            elif h1 == "short" and ret <= -float(BTC_DRIFT_MIN_RET_PCT):
                out["dir"], out["why"] = "down", "stack+ret"
            elif ret >= strong or (ret1 is not None and ret1 >= strong1 and ret > 0):
                out["dir"], out["why"] = "up", "strong_move"
            elif ret <= -strong or (ret1 is not None and ret1 <= -strong1 and ret < 0):
                out["dir"], out["why"] = "down", "strong_move"
    except Exception as e:
        out["error"] = str(e)[:120]
    _BTC_DRIFT_CACHE.update({"ts": now, "state": dict(out)})
    return out


def _against_drift(direction: str, drift: dict | None) -> bool:
    d = str((drift or {}).get("dir") or "none")
    s_ = str(direction or "").lower()
    return (d == "up" and s_ == "short") or (d == "down" and s_ == "long")


def _with_drift(direction: str, drift: dict | None) -> bool:
    d = str((drift or {}).get("dir") or "none")
    s_ = str(direction or "").lower()
    return (d == "up" and s_ == "long") or (d == "down" and s_ == "short")


def _drift_label(drift: dict | None) -> str:
    d = drift or {}
    arrow = {"up": "↑", "down": "↓"}.get(str(d.get("dir")), "→")
    r = d.get("ret_pct")
    why = f", {d.get('why')}" if d.get("why") else ""
    return (f"BTC{arrow} {r:+.2f}%/{int(d.get('window_min') or 120)}m (h1={d.get('h1') or '?'}{why})"
            if r is not None else f"BTC{arrow} (h1={d.get('h1') or '?'})")


def _kv_save_async(key: str, value: dict) -> bool:
    """V.2.11.5 — ذخیرهٔ ماندگار در Supabase (همان KV تنظیمات) تا بعد از دیپلوی/بازسازی Space گم نشود.
    فایل محلی data/ با هر دیپلوی پاک می‌شود (۲ اکتبر: ۵ معاملهٔ کاغذی رانش بعد از دیپلوی 2.11.4 از گزارش رفت)."""
    try:
        import asyncio as _aio
        from database.supabase_client import save_app_kv
        loop = _aio.get_running_loop()
        loop.create_task(save_app_kv(key, value))
        return True
    except RuntimeError:
        return False  # بدون event loop (مثلاً تست sync) — فایل محلی کافی است
    except Exception as e:
        logger.debug("kv save %s failed: %s", key, e)
        return False


PAPER_KV_MAX_CLOSED = 150


def _save_paper() -> None:
    try:
        os.makedirs(os.path.dirname(_PAPER_FILE), exist_ok=True)
        with open(_PAPER_FILE, "w", encoding="utf-8") as f:
            json.dump({"open": _paper_open_map, "closed": _paper_closed[:200]}, f, ensure_ascii=False)
    except Exception as e:
        logger.debug("save paper failed: %s", e)
    _kv_save_async("paper_trades", {
        "open": _paper_open_map, "closed": _paper_closed[:PAPER_KV_MAX_CLOSED], "saved_at": time.time(),
    })


_REMOTE_STATE_LOADED: dict[str, bool] = {"paper": False, "news": False}
_REMOTE_STATE_RESULT: dict[str, Any] = {}


def _paper_key(c: dict) -> tuple:
    return (str(c.get("symbol")), str(c.get("direction")), int(float(c.get("opened_at") or 0)))


async def _load_remote_state_once() -> dict:
    """یک بار بعد از بوت: معاملات کاغذی و تاریخچهٔ اثر خبر را از Supabase برگردان (ادغام، بدون تکرار).
    کاغذیِ بازی که مهلتش در زمان خاموشی تمام شده، کنار گذاشته می‌شود (مسیر قیمتش دیده نشده — شمرده نمی‌شود)."""
    out = {"paper_merged": 0, "paper_dropped_expired": 0, "news_merged": 0}
    try:
        from database.supabase_client import load_app_kv
    except Exception:
        return out
    if not _REMOTE_STATE_LOADED["paper"]:
        _REMOTE_STATE_LOADED["paper"] = True
        try:
            d = await load_app_kv("paper_trades") or {}
            now = time.time()
            for k, v in (d.get("open") or {}).items():
                if k in _paper_open_map or not isinstance(v, dict):
                    continue
                if float(v.get("deadline") or 0) < now:
                    out["paper_dropped_expired"] += 1
                    continue
                _paper_open_map[k] = v
                out["paper_merged"] += 1
            seen = {_paper_key(c) for c in _paper_closed}
            for c in d.get("closed") or []:
                if isinstance(c, dict) and _paper_key(c) not in seen:
                    _paper_closed.append(c)
                    seen.add(_paper_key(c))
                    out["paper_merged"] += 1
            _paper_closed.sort(key=lambda c: float(c.get("closed_at") or 0), reverse=True)
            del _paper_closed[200:]
        except Exception as e:
            logger.debug("remote paper load failed: %s", e)
    if not _REMOTE_STATE_LOADED["news"]:
        _REMOTE_STATE_LOADED["news"] = True
        try:
            d = await load_app_kv("news_impact") or {}
            for k, v in (d.get("items") or {}).items():
                if k not in _NEWS_IMPACT and isinstance(v, dict):
                    _NEWS_IMPACT[k] = v
                    out["news_merged"] += 1
        except Exception as e:
            logger.debug("remote news impact load failed: %s", e)
    if not _REMOTE_STATE_LOADED.get("matrix"):
        _REMOTE_STATE_LOADED["matrix"] = True
        try:
            d = await load_app_kv("strategy_matrix") or {}
            if d.get("policy") and not _MATRIX.get("policy"):
                _MATRIX.update({k: v for k, v in d.items() if k in ("policy", "built_at", "source_finished_at",
                                                                     "source_days", "demoted", "liveness_pick",
                                                                     "symbol_filter", "gate_mode", "exit_mode")})
                out["matrix_restored"] = True
                try:   # V.2.18.10 — قواعد جدید فوراً روی جدول بازیابی‌شده (نه بعد از ۲ ساعت بک‌تست)
                    out["matrix_rules_off"] = _matrix_enforce_rules()
                except Exception as _mre:
                    logger.debug("matrix rules on restore failed: %s", _mre)
            elif not _MATRIX.get("policy") and (_BACKTEST_STATE.get("result") or {}).get("cells"):
                _matrix_apply_backtest()
        except Exception as e:
            logger.debug("remote matrix load failed: %s", e)
    if not _REMOTE_STATE_LOADED.get("scan_slots"):   # V.2.18.5 — اسکن هر بازه فقط یک بار، حتی با دیپلوی وسط بازه
        try:
            d = await load_app_kv("scan_slots") or {}
            for k_, v_ in d.items():
                try:
                    if int(v_) > int(_SCAN_SLOTS.get(k_) or -1):
                        _SCAN_SLOTS[k_] = int(v_)
                except (TypeError, ValueError):
                    continue
        except Exception as e:
            logger.debug("remote scan slots load failed: %s", e)
        try:   # V.2.18.9 — آخرین نتیجهٔ اسکن‌ها
            d2 = await load_app_kv("scan_last") or {}
            for _st, _k in ((_RSI_STATE, "rs_intraday_50"), (_RS_STATE, "rel_strength"), (_TSMOM_STATE, "tsmom_daily"),
                            (_TATR_STATE, "trend_atr_daily")):
                if not _st.get("last_result") and isinstance(d2.get(_k), dict):
                    _st["last_result"] = dict(d2[_k], restored=True)
        except Exception as e:
            logger.debug("remote scan last load failed: %s", e)
        try:   # V.2.22.1 — حالت زندهٔ استراتژی‌های گیت‌هاب
            _gl = await load_app_kv("gh_live") or {}
            for _k, _v in _gl.items():
                if isinstance(_v, dict):
                    _GH_LIVE[_k] = _v
            # V.2.24.4 — حالت‌هایی که قبل از بارگذاری ساخته شده‌اند (گزارش زودهنگام) و در KV نیستند ⇒ همین الان ذخیره
            if any(n not in _gl for n in GH_LIVE_STRATEGIES):
                for n in GH_LIVE_STRATEGIES:
                    _GH_LIVE.setdefault(n, {"mode": "auto", "since": time.time(), "history": [], "why": "V.2.22.1 — شروع"})
                _kv_save_async("gh_live", dict(_GH_LIVE))
        except Exception as e:
            logger.debug("remote gh live load failed: %s", e)
        try:   # V.2.22.0 — دفتر کاغذی استراتژی‌های گیت‌هاب
            import backtest_github as _bgh
            _gd = await load_app_kv("gh_paper") or {}
            for _k in ("start", "trades", "keys", "last_run", "pp_start", "pp_trades", "pp_keys",
                       "ext_start", "ext_trades", "ext_keys"):   # V.2.39.2 + سبد کاغذی
                if _gd.get(_k) is not None:
                    _bgh.FWD[_k] = _gd[_k]
            _bgh.FWD["pp_trades"] = [x for x in (_bgh.FWD.get("pp_trades") or []) if x.get("strategy") in _bgh.STRATEGIES]
            _bgh.FWD["ext_trades"] = [x for x in (_bgh.FWD.get("ext_trades") or [])   # V.2.40.1 — کاغذی سهام/کالا پاک
                                      if str(x.get("symbol") or "") in GH_EXT_CRYPTO_ALLOW]
            # V.2.24.0 — معاملات کاغذی استراتژی‌های حذف‌شده پاک
            _bgh.FWD["trades"] = [x for x in (_bgh.FWD.get("trades") or []) if x.get("strategy") in _bgh.STRATEGIES]
        except Exception as e:
            logger.debug("remote gh paper load failed: %s", e)
        try:   # V.2.19.0 — وضعیت آزمون رو به جلو
            d3 = await load_app_kv("forward_state") or {}
            for k_, v_ in d3.items():
                if isinstance(v_, dict) and v_.get("mode") in ("paper", "live"):
                    _FWD[k_] = v_
        except Exception as e:
            logger.debug("remote forward state load failed: %s", e)
        _REMOTE_STATE_LOADED["scan_slots"] = True
    if not _REMOTE_STATE_LOADED.get("maker"):
        _REMOTE_STATE_LOADED["maker"] = True
        try:
            d = await load_app_kv("maker_selftest") or {}
            if d.get("ts") and not _MAKER_SELFTEST.get("ts"):
                _MAKER_SELFTEST.update(d)
        except Exception as e:
            logger.debug("remote maker selftest load failed: %s", e)
    if not _REMOTE_STATE_LOADED.get("mig2140"):
        _REMOTE_STATE_LOADED["mig2140"] = True
        try:
            mig4 = await load_app_kv("migrations") or {}
            if not mig4.get("2140_backtest_days_90"):
                import runtime_settings as _rs4
                saved4 = _rs4.save({"backtest_days": 90})
                apply_runtime_settings()
                try:
                    await _rs4.save_to_supabase(saved4)
                except Exception:
                    pass
                mig4["2140_backtest_days_90"] = time.time()
                mig4.setdefault("2123_backtest_days_60", time.time())
                _kv_save_async("migrations", mig4)
                out["migration_2140_backtest_days_90"] = True
        except Exception as e:
            logger.debug("migration 2140 failed: %s", e)
    if not _REMOTE_STATE_LOADED.get("mig2123"):
        _REMOTE_STATE_LOADED["mig2123"] = True
        try:
            mig3 = await load_app_kv("migrations") or {}
            if (not mig3.get("2123_backtest_days_60") and not mig3.get("2140_backtest_days_90")
                    and not out.get("migration_2140_backtest_days_90")):
                import runtime_settings as _rs3
                saved3 = _rs3.save({"backtest_days": 60})
                apply_runtime_settings()
                try:
                    await _rs3.save_to_supabase(saved3)
                except Exception:
                    pass
                mig3["2123_backtest_days_60"] = time.time()
                _kv_save_async("migrations", mig3)
                out["migration_2123_backtest_days_60"] = True
        except Exception as e:
            logger.debug("migration 2123 failed: %s", e)
    if not _REMOTE_STATE_LOADED.get("mig2121"):
        _REMOTE_STATE_LOADED["mig2121"] = True
        try:
            mig = await load_app_kv("migrations") or {}
            if not mig.get("2121_range_signal_only"):
                # V.2.12.1 — بک‌تست ۳۰ روزه: رنج بعد از کارمزد منفی (۲۶۹ معامله، −۰٫۱۰٪/معامله) ⇒ فقط سیگنال (یک بار؛ بعداً دستی قابل تغییر)
                import runtime_settings as _rs
                saved = _rs.save({"range_signal_only": True})
                apply_runtime_settings()
                try:
                    await _rs.save_to_supabase(saved)
                except Exception:
                    pass
                mig["2121_range_signal_only"] = time.time()
                _kv_save_async("migrations", mig)
                out["migration_2121_range_signal_only"] = True
        except Exception as e:
            logger.debug("migration 2121 failed: %s", e)
    if not _REMOTE_STATE_LOADED.get("backtest"):
        _REMOTE_STATE_LOADED["backtest"] = True
        try:
            d = await load_app_kv("backtest_last") or {}
            if d.get("result") and not _BACKTEST_STATE.get("result"):
                _BACKTEST_STATE.update({"state": "done", "result": d.get("result"), "recommend": d.get("recommend"),
                                        "variants": d.get("variants"), "trend": d.get("trend"),
                                        "walk_forward": d.get("walk_forward"), "new_strategies": d.get("new_strategies"),
                                        "rs_robustness": d.get("rs_robustness"),
                                        "daily_research": d.get("daily_research"),
                                        "intraday_research": d.get("intraday_research"), "universe": d.get("universe"),
                                        "github_research": d.get("github_research"),
                                        "app_version": d.get("app_version"), "days": d.get("days"),
                                        "sources": d.get("sources") or {}, "finished_at": d.get("finished_at"),
                                        "started_at": d.get("started_at"), "restored": True})
        except Exception as e:
            logger.debug("remote backtest load failed: %s", e)
    if not _REMOTE_STATE_LOADED.get("small_tp"):
        _REMOTE_STATE_LOADED["small_tp"] = True
        try:
            d = await load_app_kv("range_small_tp_state") or {}
            if d.get("history") and not _SMALL_TP_STATE.get("history"):
                _SMALL_TP_STATE["history"] = list(d.get("history"))[:10]
            # خود تصمیم از داده دوباره حساب می‌شود؛ فقط زمان روشن شدن قبلی حفظ می‌شود
            if d.get("enabled_rule") and d.get("since"):
                _SMALL_TP_STATE["since_previous"] = d.get("since")
        except Exception as e:
            logger.debug("remote small tp state load failed: %s", e)
    if any(out.values()) or not _REMOTE_STATE_RESULT:
        _REMOTE_STATE_RESULT.update(out)
        _REMOTE_STATE_RESULT["ts"] = time.time()
    return out


def _load_paper() -> None:
    global _paper_open_map, _paper_closed
    try:
        if os.path.isfile(_PAPER_FILE):
            with open(_PAPER_FILE, "r", encoding="utf-8") as f:
                d = json.load(f) or {}
            _paper_open_map = dict(d.get("open") or {})
            _paper_closed = list(d.get("closed") or [])[:200]
    except Exception as e:
        logger.debug("load paper failed: %s", e)


def _paper_open(symbol: str, direction: str, entry: float, stop_loss: float, target: float,
                strategy_id: str, reason: str, score: Any = None, drift: dict | None = None,
                time_stop_sec: float | None = None, extra: dict | None = None) -> bool:
    """معاملهٔ کاغذی برای سیگنالی که فقط به‌خاطر یک فیلتر رد شد — برای سنجش اثر همان فیلتر."""
    if not PAPER_TRACK_BLOCKED:
        return False
    key = _norm_symbol(symbol)
    try:
        e, sl, tp = float(entry), float(stop_loss), float(target)
    except (TypeError, ValueError):
        return False
    # V.2.19.1 — آزمون رو به جلو: هر استراتژی جای خودش (NEAR در rs_intraday_50 و rel_strength هم‌زمان)
    mkey = f"{key}#{strategy_id}" if reason == "forward_test" else key
    if e <= 0 or sl <= 0 or tp <= 0 or mkey in _paper_open_map or len(_paper_open_map) >= PAPER_MAX_OPEN:
        return False
    now = time.time()
    for c in _paper_closed[:30]:
        if c.get("symbol") == key and c.get("direction") == direction and now - float(c.get("closed_at") or 0) < PAPER_REOPEN_COOLDOWN_SEC:
            return False
    _paper_open_map[mkey] = {
        "symbol": key, "direction": str(direction).lower(), "entry": e, "stop_loss": sl, "target": tp,
        "strategy_id": strategy_id, "blocked_by": reason, "score": score, "btc_ctx": drift,
        "opened_at": now, "deadline": now + float(time_stop_sec or RANGE_TIME_STOP_SEC),
        "mfe_pct": 0.0, "mae_pct": 0.0, "app_version": APP_VERSION,
    }
    if extra:
        _paper_open_map[mkey].update(extra)
    _save_paper()
    return True


async def _paper_update() -> list[dict]:
    """هر دور مدیر: قیمت لحظه‌ای → MFE/MAE، برخورد SL/TP، time-stop. (نمونه‌برداری ≈۴۵ ثانیه؛ تقریبی)."""
    closed_now: list[dict] = []
    for key, p in list(_paper_open_map.items()):
        try:
            lp = await toobit_market.get_live_price(str(p.get("symbol") or key).split("#")[0])
            px = float((lp or {}).get("price") or 0)
        except Exception:
            px = 0.0
        if px <= 0:
            continue
        e, sl, tp = float(p["entry"]), float(p["stop_loss"]), float(p["target"])
        sign = 1.0 if p["direction"] == "long" else -1.0
        move = sign * (px / e - 1.0) * 100.0
        p["mfe_pct"] = round(max(float(p.get("mfe_pct") or 0), move), 4)
        p["mae_pct"] = round(min(float(p.get("mae_pct") or 0), move), 4)
        exit_px, why = None, None
        if (sign > 0 and px <= sl) or (sign < 0 and px >= sl):
            exit_px, why = sl, ("trail_sl" if p.get("sl_moved") else "sl")
        elif (sign > 0 and px >= tp) or (sign < 0 and px <= tp):
            exit_px, why = tp, "tp"
        elif time.time() >= float(p.get("deadline") or 0):
            exit_px, why = px, "time_stop"
        if exit_px is None:
            # V.2.19.0 — کاغذی هم همان خروج زنده (سربه‌سر / SL متحرک) را اجرا می‌کند
            try:
                import backtest_exits as _bx
                _md = _bx.EXIT_MODES.get(str(p.get("exit_mode") or "base")) or {}
                if (_md.get("be_r") is not None or _md.get("trail_from_r") is not None) and p.get("sl_pct0"):
                    _tg = _bx.mode_sl_target(p["direction"], e, float(p["sl_pct0"]), float(p["mfe_pct"]), _md,
                                             abs(float(ROUND_TRIP_FRICTION_PCT)))
                    if _tg is not None and ((sign > 0 and _tg > sl) or (sign < 0 and _tg < sl)):
                        p["stop_loss"] = _tg
                        p["sl_moved"] = True
            except Exception:
                pass
            continue
        gross = sign * (exit_px / e - 1.0) * 100.0
        net = gross - float(PAPER_FEE_PCT)
        if p.get("blocked_by") == "forward_test" and why in ("sl", "trail_sl"):
            net -= float(BACKTEST_STOP_SLIP_PCT)   # V.2.19.0 — مثل بک‌تست، محافظه‌کارانه
        rec = dict(p)
        rec.update({
            "exit_price": exit_px, "exit_reason": why, "closed_at": time.time(),
            "gross_pct": round(gross, 4), "net_pct": round(net, 4),
            "net_usdt_est": round(float(PAPER_NOTIONAL_USDT) * net / 100.0, 4),
        })
        _paper_closed.insert(0, rec)
        del _paper_open_map[key]
        closed_now.append(rec)
        if rec.get("blocked_by") == "forward_test":
            try:
                _fwd_record_paper(rec)
            except Exception:
                pass
    if closed_now:
        del _paper_closed[200:]
        _save_paper()
    return closed_now


def _paper_summary() -> dict:
    closed = list(_paper_closed)
    by: dict[str, dict] = {}
    for c in closed:
        k = f"{c.get('strategy_id')}|{c.get('direction')}"
        b = by.setdefault(k, {"n": 0, "wins": 0, "net_usdt_est": 0.0})
        b["n"] += 1
        b["wins"] += 1 if float(c.get("net_pct") or 0) > 0 else 0
        b["net_usdt_est"] = round(b["net_usdt_est"] + float(c.get("net_usdt_est") or 0), 4)
    by_filter: dict[str, dict] = {}
    for c in closed:
        k = f"{c.get('blocked_by')}|{c.get('strategy_id')}|{c.get('direction')}"
        b = by_filter.setdefault(k, {"n": 0, "wins": 0, "net_usdt_est": 0.0})
        b["n"] += 1
        b["wins"] += 1 if float(c.get("net_pct") or 0) > 0 else 0
        b["net_usdt_est"] = round(b["net_usdt_est"] + float(c.get("net_usdt_est") or 0), 4)
    return {
        "note": ("معاملات کاغذیِ سیگنال‌هایی که فقط به‌خاطر یک فیلتر رد شدند (btc_drift_guard = رانش BTC، "
                 "rr_net = فقط R:R خالص)؛ فقط SL/TP/time-stop، قیمت هر ~۴۵ث، کارمزد ۰٫۰۸٪، notional ۲۵$ — تقریبی"),
        "by_filter": by_filter,
        "open": list(_paper_open_map.values()),
        "closed_n": len(closed),
        "closed_net_usdt_est": round(sum(float(c.get("net_usdt_est") or 0) for c in closed), 4),
        "by_strategy_direction": by,
        "closed_recent": closed[:15],
    }


def _drift_follow_ok(diagnostics: dict | None) -> tuple[bool, str]:
    """کیفیت لازم برای ورود روندیِ هم‌جهت رانش BTC در pause (فقط برچسب نماد شل‌تر از weak_trend)."""
    d = diagnostics if isinstance(diagnostics, dict) else {}
    lab = str(d.get("regime_label") or d.get("regime") or "").upper()
    try:
        conf = float(d.get("regime_confidence") or 0)
        er = d.get("efficiency_ratio_1h") if d.get("efficiency_ratio_1h") is not None else d.get("er")
        ci = d.get("choppiness_1h") if d.get("choppiness_1h") is not None else d.get("ci")
        adx = d.get("adx_1h") if d.get("adx_1h") is not None else d.get("adx")
        er_f = float(er) if er is not None else None
        ci_f = float(ci) if ci is not None else None
        adx_f = float(adx) if adx is not None else None
    except (TypeError, ValueError):
        return False, "diag نامعتبر"
    if not ("TREND" in lab or ("WEAK" in lab and conf >= float(BTC_DRIFT_FOLLOW_MIN_SYMBOL_CONF))):
        return False, f"برچسب نماد {lab or '?'}({conf:.0f})"
    if er_f is None or er_f < 0.28:
        return False, f"ER {er_f}"
    if ci_f is not None and ci_f >= 55:
        return False, f"CI {ci_f:.0f}"
    if adx_f is None or adx_f < float(WEAK_TREND_MIN_ADX):
        return False, f"ADX {adx_f}"
    return True, "ok"


_pending_drift_follow: dict[str, bool] = {}

# V.2.11.4 — سیگنال روندی که «فقط» به‌خاطر R:R خالص رد شد → کاغذی (بدون تغییر پارامتر ورود)
PAPER_TRACK_RR_REJECTS = True
# V.2.11.10 — دو سنجش کاغذی دیگر (بدون تغییر رفتار زنده)
PAPER_TRACK_SLMIN_REJECTS = True       # روند با SL کوچک‌تر از حداقل ⇒ SL تا حداقل باز، TP تا کمترین مقدار مجاز
PAPER_TRACK_SAMEDIR_CAP_REJECTS = True  # سقف «یک هم‌جهت وقتی BTC ضعیف است»
# V.2.11.11 — «تعقیب افراطی» (overextension ≥ 1.25 ATR) در روندهای قوی مانع اصلی ورود شد (۲، ۴ و ۵ اکتبر)
PAPER_TRACK_OVEREXT_REJECTS = True
OVEREXT_STRONG_ER = 0.70
OVEREXT_STRONG_ADX = 35.0


def _overext_label(diagnostics: dict | None) -> tuple[str, dict]:
    """تفکیک بر اساس شدت روند نماد: overext_strong (ER≥0.7 و ADX1h≥35) یا overext_other."""
    d = diagnostics if isinstance(diagnostics, dict) else {}
    try:
        er = float(d.get("efficiency_ratio_1h") if d.get("efficiency_ratio_1h") is not None else d.get("er") or 0)
        adx = float(d.get("adx_1h") if d.get("adx_1h") is not None else d.get("adx") or 0)
        ox = float(d.get("overextension_atr") or 0)
    except (TypeError, ValueError):
        er, adx, ox = 0.0, 0.0, 0.0
    strong = er >= float(OVEREXT_STRONG_ER) and adx >= float(OVEREXT_STRONG_ADX)
    return ("overext_strong" if strong else "overext_other"), {"er": round(er, 3), "adx_1h": round(adx, 1),
                                                                "overextension_atr": round(ox, 2)}


def _widen_geometry(direction: str, entry: float, stop_loss: float, target: float) -> tuple[float, float, dict]:
    """SL کوچک‌تر از حداقل ⇒ SL = حداقل(+۰٫۰۱٪)، TP = کمترین مقداری که همهٔ قواعد هزینه را رد کند
    (حداقل فاصلهٔ TP و R:R خالص). نگه داشتن نسبت ۱٫۶۴ با SL ۰٫۴٪ این قواعد را نقض می‌کرد (TP ۰٫۶۶٪ < ۰٫۷۲٪ و R:R ۰٫۸۲)."""
    e = float(entry)
    sign = 1.0 if str(direction).lower() != "short" else -1.0
    fr = abs(float(ROUND_TRIP_FRICTION_PCT))
    sl_pct = float(MIN_SL_DISTANCE_PCT) + 0.01
    tp_pct = max(float(MIN_TP_DISTANCE_PCT) + 0.005, float(MIN_RR_REAL) * (sl_pct + fr) + fr + 0.005)
    orig = _geom(e, stop_loss, target)
    new_sl = e * (1.0 - sign * sl_pct / 100.0)
    new_tp = e * (1.0 + sign * tp_pct / 100.0)
    return new_sl, new_tp, {"orig": orig, "sl_pct": round(sl_pct, 4), "tp_pct": round(tp_pct, 4),
                            "gross_rr": round(tp_pct / sl_pct, 3)}


async def _paper_rr_probe(symbol: str, direction: str, entry: float, stop_loss: float, target: float,
                          score: Any, diagnostics: dict | None, rr_reason: str, strategy_id: str,
                          skip: str = "rr", label: str = "rr_net", only_note: str = "فقط R:R مانع بود",
                          after_note: str = "بعد از R:R هم رد", extra_info: dict | None = None) -> str:
    """پاس دوم can_open با نادیده گرفتن فقط یک گیت (rr | underwater). اگر همهٔ گیت‌های دیگر رد شوند ⇒ کاغذی.
    دلیل رد ثبت‌شده همان گیت اول می‌ماند (+ توضیح)؛ هیچ سفارشی فرستاده نمی‌شود."""
    key = _norm_symbol(symbol)
    try:
        ok2, why2 = await can_open_real_trade(
            symbol, direction, entry, stop_loss, target, score, diagnostics=diagnostics,
            _skip_rr=(skip == "rr"), _skip_underwater=(skip == "underwater"),
            _skip_samedir_cap=(skip == "samedir"), _skip_overext=(skip == "overext"), _probe=True,
        )
    except Exception as e:
        logger.debug("rr probe failed %s: %s", symbol, e)
        return rr_reason
    finally:
        for _d in (_pending_strategy, _pending_drift_follow, _pending_range_source, _pending_matrix):
            try:
                _d.pop(key, None)
            except Exception:
                pass
    if not ok2:
        return f"{rr_reason} | {after_note}: {str(why2).split(' | ')[0][:90]}"
    g = _geom(entry, stop_loss, target)
    _ts = float(RANGE_TIME_STOP_SEC) if strategy_id == "range_scalp" else float(MAX_HOLD_SECONDS)
    papered = _paper_open(
        symbol, direction, entry, stop_loss, target, strategy_id, label, score=score,
        drift=dict(_BTC_DRIFT_CACHE.get("state") or {}), time_stop_sec=_ts,
        extra={"net_rr": g.get("net_rr"), "sl_pct": g.get("sl_pct"), "tp_pct": g.get("tp_pct"), **(extra_info or {})},
    )
    return f"{rr_reason} · {only_note}" + (" · کاغذی ثبت شد" if papered else "")
_pending_range_source: dict[str, str] = {}   # V.2.11.0: engine (range_engine) | relabel (سیگنال روند با برچسب رنج در pause)

# ─────────────────────────────────────────────────────────────
# V.2.11.0 — مسیر ۱ دقیقه‌ای هر معامله + ارزیابی «اگر» قواعد خروج (بدون اثر روی معاملهٔ زنده)
# بازبینی: «تغییر خروج برای سود باید با مسیر قیمت معاملات آزمایش شود» و «نمونه‌برداری ۴۵ثانیه‌ای کافی نیست».
# بعد از هر بستن، وقتی پنجرهٔ کامل معامله (تا time-stop) گذشت، کندل‌های ۱m (یا ۵m اگر ۱m نبود) از صرافی
# گرفته و ذخیره می‌شود؛ سپس چند قاعدهٔ خروج روی همان مسیر واقعی شبیه‌سازی و در گزارش وضعیت نشان داده می‌شود.
# ─────────────────────────────────────────────────────────────
WHATIF_COST_PCT = 0.10          # کارمزد ۰٫۰۸ + لغزش ۰٫۰۲ (رفت‌وبرگشت)
PATH_CAPTURE_DELAY_SEC = 120.0  # بعد از پایان پنجره
_path_capture_queue: dict[str, dict] = {}   # trade_id → {symbol, direction, opened_at, until, ...}


def _queue_path_capture(meta: dict) -> None:
    """بعد از بستن: ثبت در صف تا وقتی پنجرهٔ کامل گذشت، مسیر ۱m گرفته شود."""
    try:
        tid = str(meta.get("trade_id") or "")
        if not tid or (meta.get("path_1m") and meta.get("path_mark_1m")):
            return
        opened = float(meta.get("opened_at") or 0)
        if opened <= 0:
            return
        horizon = float(RANGE_TIME_STOP_SEC) if str(meta.get("strategy_id") or "") == "range_scalp" else float(MAX_HOLD_SECONDS)
        _path_capture_queue[tid] = {
            "trade_id": tid, "symbol": _norm_symbol(str(meta.get("symbol") or "")),
            "direction": meta.get("direction"), "opened_at": opened,
            "until": opened + horizon, "due": opened + horizon + PATH_CAPTURE_DELAY_SEC,
            "row": meta,  # V.2.11.1: ردیف حافظه یا Supabase (بعد از ری‌استارت هم کار کند)
        }
    except Exception:
        pass


_path_capture_log: list[dict] = []   # V.2.11.2 — عیب‌یابی گرفتن مسیر (در گزارش وضعیت)


def _bars_in_window(df: Any, sec: int, start_ts: float, end_ts: float) -> list[list[float]]:
    out: list[list[float]] = []
    if df is None or len(df) == 0:
        return out
    for row in df.itertuples(index=False):
        ts = float(getattr(row, "timestamp", 0) or 0)
        ts = ts / 1000.0 if ts > 1e12 else ts
        if ts + sec <= start_ts or ts > end_ts:
            continue
        out.append([int(ts - start_ts), float(row.open), float(row.high), float(row.low), float(row.close)])
    return out


async def _fetch_minute_path(symbol: str, start_ts: float, end_ts: float, mark: bool = False) -> tuple[str, list[list[float]]]:
    """کندل‌های بستهٔ بازهٔ معامله: [t_offset_sec, open, high, low, close].
    V.2.11.2: اگر startTime نتیجه نداد (رفتار API نامعلوم)، بدون startTime با limit کافی تا «الان» گرفته و فیلتر می‌شود.
    """
    now = time.time()
    tries: list[str] = []
    tiers = [("1m", 60, 1000), ("5m", 300, 300)]
    if mark:
        # V.2.11.14 — startTime روی توبیت نادیده گرفته می‌شود؛ برای معاملات قدیمی‌تر از ~۱ روز فقط کندل ۱۵m
        # (۱۰۰۰ کندل ≈ ۱۰ روز) در دسترس است — به‌عنوان «وتوی SL» استفاده می‌شود
        tiers.append(("15m", 900, 1000))
    for itv, sec, cap in tiers:
        for mode in ("start", "recent"):
            try:
                if mode == "start":
                    n = int((end_ts - start_ts) / sec) + 3
                    df = await (toobit_market.get_mark_klines if mark else toobit_market.get_klines)(symbol, itv, limit=max(5, min(n, 200)),
                                                        start_time_ms=int((start_ts - sec) * 1000))
                else:
                    n = int((now - start_ts) / sec) + 5
                    if n > cap:
                        tries.append(f"{itv}/{mode}:skip(n={n})")
                        continue
                    df = await (toobit_market.get_mark_klines if mark else toobit_market.get_klines)(symbol, itv, limit=max(5, n))
                bars = _bars_in_window(df, sec, start_ts, end_ts)
                tries.append(f"{itv}/{mode}:{len(df) if df is not None else 0}->{len(bars)}")
                if bars:
                    _path_capture_log.insert(0, {"symbol": symbol, "mark": mark, "ok": True, "interval": itv, "mode": mode,
                                                 "bars": len(bars), "tries": tries, "t": round(now, 1)})
                    del _path_capture_log[12:]
                    return itv, bars
            except Exception as e:
                tries.append(f"{itv}/{mode}:err {str(e)[:60]}")
    _path_capture_log.insert(0, {"symbol": symbol, "mark": mark, "ok": False, "tries": tries, "t": round(now, 1)})
    del _path_capture_log[12:]
    return "", []


def _truth_of(h: dict) -> dict:
    """از معاملهٔ واقعی: چند ثانیه زنده بود و آیا با همان SL اصلی بسته شد."""
    try:
        o = float(h.get("opened_at") or 0)
        c = float(h.get("exchange_closed_at") or h.get("closed_at") or 0)
        close_t = c - o if (o > 0 and c > o) else 0.0
    except (TypeError, ValueError):
        close_t = 0.0
    r = str(h.get("exit_reason") or "").lower()
    orig_sl = ("stop_loss" in r or r == "sl") and not any(x in r for x in ("breakeven", "floor", "regime_tightened"))
    return {"close_t": close_t, "orig_sl_hit": orig_sl}


def _itv_sec(itv: Any) -> int:
    return {"1m": 60, "5m": 300, "15m": 900}.get(str(itv or "1m"), 60)


def _mark_sl_checker(mark_bars: list | None, mark_sec: int | None, bar_sec: int | None, sign: float):
    """V.2.11.14 — تابع (t, adv_last, sl) ⇒ آیا SL صرافی (MARK_PRICE) خورده؟
    - مارک هم‌بازه با مسیر: برخورد = کف/سقف مارک همان کندل.
    - مارک درشت‌تر (مثلاً ۱۵m): «وتو» — برخورد فقط اگر قیمت آخر رسیده باشد و مارک در همان بازهٔ ۱۵ دقیقه هم رسیده باشد.
    - بدون مارک: قیمت آخر (رفتار قبلی)."""
    mk = [b for b in (mark_bars or []) if isinstance(b, (list, tuple)) and len(b) >= 5]
    msec = int(mark_sec or 60)
    bsec = int(bar_sec or 60)
    if not mk:
        def chk(t, adv, sl):
            return (sign > 0 and adv <= sl) or (sign < 0 and adv >= sl)
        return chk, "last"
    if msec <= bsec:
        exact = {int(b[0]): b for b in mk}

        def chk(t, adv, sl):
            mb = exact.get(int(t))
            a = (float(mb[3]) if sign > 0 else float(mb[2])) if mb is not None else adv
            return (sign > 0 and a <= sl) or (sign < 0 and a >= sl)
        return chk, "mark"
    starts = sorted(int(b[0]) for b in mk)
    by_start = {int(b[0]): b for b in mk}

    def chk(t, adv, sl):
        hit_last = (sign > 0 and adv <= sl) or (sign < 0 and adv >= sl)
        if not hit_last:
            return False
        import bisect
        i = bisect.bisect_right(starts, int(t)) - 1
        if i < 0:
            return True
        mb = by_start[starts[i]]
        if int(t) >= starts[i] + msec:
            return True  # خارج از پوشش مارک ⇒ قیمت آخر
        a = float(mb[3]) if sign > 0 else float(mb[2])
        return (sign > 0 and a <= sl) or (sign < 0 and a >= sl)
    return chk, "mark_veto"


SMALL_TP_LEVELS = (0.40, 0.50)   # V.2.11.9 — درصد حرکت مطلوب (≈ +0.10$ و +0.125$ روی notional ۲۵$)
# V.2.11.12 — نامزدهای خروج رنج (همه روی مسیر ۱m با «قواعد زندهٔ فعلی» مقایسه می‌شوند)
#   tp*   : بستن در سطح سود (کل یا نصف)
#   lock* : وقتی بیشترین سود به trigger رسید، SL روی ورود+lock (کف سود؛ TP دست نمی‌خورد ⇒ بردهای بزرگ قطع نمی‌شوند)
#   trail*: وقتی بیشترین سود به trigger رسید، SL = ورود + کسری از بیشترین سود (دنبال‌کننده)
EXIT_CANDIDATES: dict[str, dict] = {
    "tp40_full": {"kind": "tp", "level": 0.40, "live": True},
    "tp50_full": {"kind": "tp", "level": 0.50, "live": True},
    "tp40_half": {"kind": "tp_half", "level": 0.40, "live": False},
    "tp50_half": {"kind": "tp_half", "level": 0.50, "live": False},
    "lock25_at50": {"kind": "lock", "trigger": 0.50, "lock": 0.25, "live": True},
    "lock30_at60": {"kind": "lock", "trigger": 0.60, "lock": 0.30, "live": True},
    "lock40_at80": {"kind": "lock", "trigger": 0.80, "lock": 0.40, "live": True},
    "trail50_at60": {"kind": "trail", "trigger": 0.60, "frac": 0.50, "live": True},
    # V.2.11.13 — بر پایهٔ «پیشرفت به سمت TP» (DOT ۵ اکتبر: ۸۴٪ مسیر TP، برگشت تا سربه‌سر)
    "prog72_close": {"kind": "prog_close", "progress": 0.72, "min_pnl": 0.55, "live": True},   # قفل سود قدیمی رنج
    "prog70_floor50": {"kind": "prog_floor", "progress": 0.70, "floor_frac": 0.50, "live": True},
}


def _whatif_live_variants(direction: str, e: float, sl0: float, tp: float, bars: list[list[float]],
                          range_low: float | None = None, range_high: float | None = None,
                          mark_bars: list[list[float]] | None = None,
                          mark_sec: int | None = None, bar_sec: int | None = None,
                          truth: dict | None = None) -> dict:
    """V.2.11.9 — شبیه‌سازی «قواعد زندهٔ فعلی رنج» (2.11.8) و همان به‌اضافهٔ «گرفتن سود کوچک».

    live         — SL/TP صرافی + سربه‌سر در max(0.30٪, 0.8R) → ورود±اصطکاک + بستن ورود ناموفق + ابطال رنج + پایان پنجره
    tpXX_full    — live + بستن کامل وقتی حرکت مطلوب به XX٪ رسید
    tpXX_half    — live + بستن نصف در XX٪، نصف دیگر با همان live ادامه
    ترتیب در هر کندل (محافظه‌کار): اول سمت ضرر (SL/ابطال/ورود ناموفق) بعد سمت سود (سود کوچک/TP).
    """
    sign = 1.0 if str(direction).lower() != "short" else -1.0
    r_pct = abs(e - sl0) / e * 100.0
    cost = float(WHATIF_COST_PCT)
    fr = abs(float(ROUND_TRIP_FRICTION_PCT))
    be_need = max(float(BREAKEVEN_TRIGGER_PCT), float(BREAKEVEN_MIN_R) * r_pct)
    tp_pct_abs = abs(tp - e) / e * 100.0
    rl = float(range_low) if range_low else None
    rh = float(range_high) if range_high else None
    # V.2.11.13/14 — SL صرافی با قیمت مارک فعال می‌شود؛ سایهٔ قیمت آخر که مارک به آن نرسید SL نیست
    _sl_hit0, _sl_basis = _mark_sl_checker(mark_bars, mark_sec, bar_sec, sign)
    # V.2.11.15 — «حقیقت»: معاملهٔ واقعی تا لحظهٔ بستن زنده بود و SL اصلی‌اش نخورد ⇒ تا آن لحظه SL اصلی قطعاً فعال نشده
    _tr_close = float((truth or {}).get("close_t") or 0)
    _tr_sl_hit = bool((truth or {}).get("orig_sl_hit"))

    def _sl_hit(t, adv, sl):
        if _tr_close > 0 and not _tr_sl_hit and float(t) < _tr_close and abs(sl - sl0) <= abs(sl0) * 1e-9:
            return False
        return _sl_hit0(t, adv, sl)

    def mv(px: float) -> float:
        return sign * (px / e - 1.0) * 100.0

    def sim(cand: dict | None) -> float:
        kind = (cand or {}).get("kind")
        sl = sl0
        mfe = 0.0
        be_set = False
        realized = 0.0      # درصد خالص بخش بسته‌شده (وزن‌دار)
        weight = 1.0        # سهم باقی‌مانده
        taken = False
        for t, _o, h, l, c in bars:
            fav, adv = (h, l) if sign > 0 else (l, h)
            if _sl_hit(t, adv, sl):
                return realized + weight * (mv(sl) - cost)
            if rl and rh:
                if (sign > 0 and c < rl * (1 - 0.0015)) or (sign < 0 and c > rh * (1 + 0.0015)):
                    return realized + weight * (mv(c) - cost)
            # V.2.11.12: مثل مدیر زنده روی قیمت لحظه‌ای (≈ بسته شدن کندل)، نه کف/سقف کندل
            if (not be_set and RANGE_FAIL_EXIT and t >= float(RANGE_FAIL_EXIT_MIN_SEC)
                    and mfe < float(RANGE_FAIL_EXIT_MFE_MAX_PCT)
                    and mv(c) <= -float(RANGE_FAIL_EXIT_ADVERSE_R) * r_pct):
                return realized + weight * (mv(c) - cost)
            if kind in ("tp", "tp_half") and not taken and mv(fav) >= float(cand["level"]):
                lv = float(cand["level"])
                if kind == "tp_half":
                    realized += 0.5 * (lv - cost)
                    weight = 0.5
                    taken = True
                else:
                    return lv - cost
            if kind == "prog_close":
                _lvl = max(float(cand["progress"]) * tp_pct_abs, float(cand["min_pnl"]))
                if mv(fav) >= _lvl and not ((sign > 0 and fav >= tp) or (sign < 0 and fav <= tp)):
                    return _lvl - cost
            if (sign > 0 and fav >= tp) or (sign < 0 and fav <= tp):
                return realized + weight * (mv(tp) - cost)
            mfe = max(mfe, mv(fav))
            if kind == "prog_floor" and mfe >= float(cand["progress"]) * tp_pct_abs:
                fl = e * (1.0 + sign * float(cand["floor_frac"]) * tp_pct_abs / 100.0)
                sl = max(sl, fl) if sign > 0 else min(sl, fl)
            if not be_set and mfe >= be_need:
                be = e * (1.0 + sign * fr / 100.0)
                sl = max(sl, be) if sign > 0 else min(sl, be)
                be_set = True
            if kind in ("lock", "trail") and mfe >= float(cand["trigger"]):
                lk = float(cand["lock"]) if kind == "lock" else float(cand["frac"]) * mfe
                fl = e * (1.0 + sign * lk / 100.0)
                sl = max(sl, fl) if sign > 0 else min(sl, fl)
        return realized + weight * (mv(bars[-1][4]) - cost)

    out = {"live": round(sim(None), 4)}
    for k, cand in EXIT_CANDIDATES.items():
        out[k] = round(sim(cand), 4)
    return out


def _whatif_exits(direction: str, entry: float, stop_loss: float, target: float, bars: list[list[float]],
                  range_low: float | None = None, range_high: float | None = None,
                  mark_bars: list[list[float]] | None = None,
                  mark_sec: int | None = None, bar_sec: int | None = None,
                  truth: dict | None = None) -> dict:
    """شبیه‌سازی محافظه‌کارانه روی کندل‌ها (در هر کندل اول سمت ضرر، بعد سود). خروجی: درصد خالص هر قاعده.

    base     — فقط SL/TP اولیه و پایان پنجره
    be_net   — وقتی سود ناخالص ≥ هزینه+۰٫۱۵٪ شد، SL → ورود+هزینه (سربه‌سرِ خالص)
    ratchet  — وقتی سود ناخالص ≥ ۰٫۵R شد، کف = نصف بیشترین سود (عقب نمی‌رود)
    fail10   — اگر ۱۰ دقیقه گذشت و بیشترین سود < ۰٫۱۵٪ و قیمت ≥ ۰٫۳R خلاف رفت → خروج
    """
    try:
        e, sl0, tp = float(entry), float(stop_loss), float(target)
    except (TypeError, ValueError):
        return {}
    if e <= 0 or not bars:
        return {}
    sign = 1.0 if str(direction).lower() != "short" else -1.0
    r_pct = abs(e - sl0) / e * 100.0
    cost = float(WHATIF_COST_PCT)

    def mv(px: float) -> float:
        return sign * (px / e - 1.0) * 100.0

    _sl_hit00, _basis0 = _mark_sl_checker(mark_bars, mark_sec, bar_sec,
                                          1.0 if str(direction).lower() != "short" else -1.0)
    _tc0 = float((truth or {}).get("close_t") or 0)
    _ts0 = bool((truth or {}).get("orig_sl_hit"))

    def _sl_hit0(t, adv, sl):
        if _tc0 > 0 and not _ts0 and float(t) < _tc0 and abs(sl - float(stop_loss)) <= abs(float(stop_loss)) * 1e-9:
            return False
        return _sl_hit00(t, adv, sl)

    def run(rule: str) -> float:
        sl = sl0
        mfe = 0.0
        for t, _o, h, l, c in bars:
            fav, adv = (h, l) if sign > 0 else (l, h)
            # ۱) سمت ضرر اول (محافظه‌کار)
            if _sl_hit0(t, adv, sl):
                return mv(sl) - cost
            if rule == "fail10" and t >= 600 and mfe < 0.15 and mv(adv) <= -0.3 * r_pct:
                return mv(c) - cost
            # ۲) سمت سود
            if (sign > 0 and fav >= tp) or (sign < 0 and fav <= tp):
                return mv(tp) - cost
            mfe = max(mfe, mv(fav))
            if rule == "be_net" and mfe >= cost + 0.15:
                be = e * (1.0 + sign * cost / 100.0)
                sl = max(sl, be) if sign > 0 else min(sl, be)
            elif rule == "ratchet" and mfe >= 0.5 * r_pct:
                floor_px = e * (1.0 + sign * (mfe * 0.5) / 100.0)
                sl = max(sl, floor_px) if sign > 0 else min(sl, floor_px)
        return mv(bars[-1][4]) - cost

    out = {r: round(run(r), 4) for r in ("base", "be_net", "ratchet", "fail10")}
    try:
        out.update(_whatif_live_variants(direction, e, sl0, tp, bars, range_low, range_high, mark_bars,
                                         mark_sec, bar_sec, truth))
        out["sl_basis"] = _basis0
    except Exception:
        pass
    out["mfe_pct"] = round(max((mv(b[2] if sign > 0 else b[3]) for b in bars), default=0.0), 4)
    out["mae_pct"] = round(min((mv(b[3] if sign > 0 else b[2]) for b in bars), default=0.0), 4)
    out["r_pct"] = round(r_pct, 4)
    return out


async def _process_path_captures(max_items: int = 3) -> int:
    """صف مسیر: هر دور مدیر حداکثر چند مورد (کم‌هزینه برای API)."""
    done = 0
    now = time.time()
    for tid, q in list(_path_capture_queue.items()):
        if done >= max_items:
            break
        if now < float(q.get("due") or 0):
            continue
        h = q.get("row") or next((x for x in _history if str(x.get("trade_id") or "") == tid), None)
        if h is not None and h.get("path_1m"):
            itv, bars = h.get("path_interval") or "1m", h.get("path_1m")
        else:
            itv, bars = await _fetch_minute_path(q["symbol"], float(q["opened_at"]), float(q["until"]))
        # V.2.11.13 — کندل قیمت مارک (SL صرافی با MARK_PRICE فعال می‌شود)
        mitv, mbars = "", []
        if h is not None and not h.get("path_mark_1m"):
            try:
                mitv, mbars = await _fetch_minute_path(q["symbol"], float(q["opened_at"]), float(q["until"]), mark=True)
            except Exception:
                mitv, mbars = "", []
        _path_capture_queue.pop(tid, None)
        _path_capture_done[tid] = time.time()
        done += 1
        if h is None or not bars:
            continue
        h["path_interval"] = itv
        h["path_1m"] = bars
        if mbars:
            h["path_mark_1m"] = mbars
            h["path_mark_interval"] = mitv
        try:
            h["exit_whatif"] = _whatif_exits(
                h.get("direction"), float(h.get("fill_entry") or h.get("entry")),
                float(h.get("initial_sl") or h.get("original_stop_loss") or h.get("stop_loss")),
                float(h.get("target")), bars, h.get("range_low"), h.get("range_high"),
                mark_bars=h.get("path_mark_1m"),
                mark_sec=_itv_sec(h.get("path_mark_interval")), bar_sec=_itv_sec(itv),
                truth=_truth_of(h),
            )
        except Exception as e:
            h["exit_whatif"] = {"error": str(e)[:100]}
        await _persist_close_to_db(h)
    return done


_path_capture_done: dict[str, float] = {}   # trade_id → زمان آخرین تلاش (جلوگیری از تکرار)

# ─────────────────────────────────────────────────────────────
# V.2.11.2 — اندازه‌گیری اثر واقعی هر خبر روی BTC (برای بازبینی پله‌های خبر با داده)
# برای هر خبر امروز (همهٔ پله‌ها، حتی C که توقف ندارد) بعد از +۳۵ دقیقه: حرکت و دامنهٔ BTC در ۳۰ دقیقهٔ بعد از خبر
# در برابر میانهٔ دامنهٔ ۳۰ دقیقه‌ای ۲۴ ساعت اخیر (نسبت > ۲ ≈ خبر واقعاً بازار را تکان داده).
# ─────────────────────────────────────────────────────────────
_NEWS_IMPACT: dict[str, dict] = {}
_NEWS_IMPACT_LAST_RUN = 0.0
_MANAGER_HEARTBEAT: dict[str, Any] = {"ts": 0.0, "actions": 0, "cycles": 0}


async def _measure_news_impact() -> int:
    global _NEWS_IMPACT_LAST_RUN
    now = time.time()
    if now - _NEWS_IMPACT_LAST_RUN < 300:
        return 0
    _NEWS_IMPACT_LAST_RUN = now
    try:
        import news_blackout as _nb
        events = _nb.today_events_list()
    except Exception:
        return 0
    pending = [e for e in events if now >= float(e.get("ts") or 0) + 35 * 60
               and f"{int(float(e.get('ts') or 0))}:{e.get('title')}" not in _NEWS_IMPACT]
    if not pending:
        return 0
    try:
        df = await toobit_market.get_klines("BTC", "5m", limit=300)
    except Exception:
        return 0
    if df is None or len(df) < 40:
        return 0
    ts_arr = [float(x) / (1000.0 if float(x) > 1e12 else 1.0) for x in list(df["timestamp"])]
    hi, lo, cl = list(df["high"]), list(df["low"]), list(df["close"])
    ranges = []
    for i in range(6, len(cl)):
        seg_h, seg_l = max(hi[i - 5:i + 1]), min(lo[i - 5:i + 1])
        if cl[i - 6] > 0:
            ranges.append((seg_h - seg_l) / cl[i - 6] * 100.0)
    ranges.sort()
    base_range = ranges[len(ranges) // 2] if ranges else None
    n = 0
    for e in pending:
        t0 = float(e.get("ts") or 0)
        idx = [i for i, t in enumerate(ts_arr) if t0 <= t < t0 + 30 * 60]
        prev = [i for i, t in enumerate(ts_arr) if t < t0]
        if not idx or not prev:
            continue
        ref = cl[prev[-1]]
        h30, l30, c30 = max(hi[i] for i in idx), min(lo[i] for i in idx), cl[idx[-1]]
        rng = (h30 - l30) / ref * 100.0
        _NEWS_IMPACT[f"{int(t0)}:{e.get('title')}"] = {
            "title": e.get("title"), "tier": e.get("tier"), "time_tehran": e.get("time_tehran"),
            "ts": int(t0), "date_utc": time.strftime("%Y-%m-%d", time.gmtime(t0)),
            "btc_move_30m_pct": round((c30 / ref - 1.0) * 100.0, 3),
            "btc_range_30m_pct": round(rng, 3),
            "btc_typical_range_30m_pct": round(base_range, 3) if base_range else None,
            "range_ratio": round(rng / base_range, 2) if base_range else None,
        }
        n += 1
    if n:
        # V.2.11.5 — تاریخچهٔ ماندگار (حداکثر ۳۰۰ خبر اخیر) برای بازبینی پله‌ها با داده
        items = dict(sorted(_NEWS_IMPACT.items(), key=lambda kv: float(kv[1].get("ts") or 0))[-300:])
        _kv_save_async("news_impact", {"items": items, "saved_at": time.time()})
    return n


def _news_impact_summary() -> list[dict]:
    rows = sorted(_NEWS_IMPACT.values(), key=lambda r: (float(r.get("ts") or 0), str(r.get("time_tehran") or "")))
    return rows[-12:]


def _news_impact_by_title() -> list[dict]:
    """V.2.11.5 — میانگین اثر هر نوع خبر روی BTC در همهٔ روزهای ثبت‌شده (برای جابه‌جایی پله‌ها)."""
    agg: dict[str, dict] = {}
    for r in _NEWS_IMPACT.values():
        t = str(r.get("title") or "")
        ratio = r.get("range_ratio")
        if not t or ratio is None:
            continue
        a = agg.setdefault(t, {"title": t, "tier": r.get("tier"), "n": 0, "sum_ratio": 0.0, "max_ratio": 0.0})
        a["n"] += 1
        a["sum_ratio"] += float(ratio)
        a["max_ratio"] = max(a["max_ratio"], float(ratio))
    out = []
    for a in agg.values():
        out.append({"title": a["title"], "tier": a["tier"], "n": a["n"],
                    "avg_range_ratio": round(a["sum_ratio"] / a["n"], 2), "max_range_ratio": round(a["max_ratio"], 2)})
    return sorted(out, key=lambda x: -x["avg_range_ratio"])
PATH_BACKFILL_MAX_AGE_SEC = 24 * 3600
PATH_RETRY_AFTER_SEC = 6 * 3600


async def _queue_recent_path_captures() -> int:
    """V.2.11.1 — معاملات بستهٔ ۲۴ ساعت اخیر (حافظه + Supabase) که مسیر ۱m ندارند → صف.
    در .11.0 فقط حافظهٔ سشن دیده می‌شد؛ بعد از هر دیپلوی، معاملات قبلی (مثل OP/ADA) هرگز ارزیابی نمی‌شدند."""
    n = 0
    now = time.time()
    for h in await _memory_context():
        try:
            if str(h.get("status") or "") not in ("closed", "closed_external"):
                continue
            tid = str(h.get("trade_id") or "")
            if not tid or tid in _path_capture_queue or (h.get("path_1m") and h.get("path_mark_1m")):
                continue
            if now - float(_path_capture_done.get(tid) or 0) < PATH_RETRY_AFTER_SEC:
                continue
            opened = float(h.get("opened_at") or 0)
            # V.2.11.13: فقط کندل مارک کم است ⇒ تا ۷ روز عقب (اگر startTime روی این endpoint کار کند)
            _max_age = 7 * 86400 if h.get("path_1m") else PATH_BACKFILL_MAX_AGE_SEC
            if opened <= 0 or now - opened > _max_age:
                continue
            if h.get("target") in (None, "", 0) or not (h.get("initial_sl") or h.get("original_stop_loss") or h.get("stop_loss")):
                continue
            _queue_path_capture(h)
            n += 1
        except Exception:
            continue
    return n


# ─────────────────────────────────────────────────────────────
# V.2.11.9 — «گرفتن سود کوچک» رنج: سنجش خودکار + روشن شدن خودکار با داده + خاموش دستی
# ─────────────────────────────────────────────────────────────
RANGE_SMALL_TP_AUTO = True          # false = هرگز خودکار روشن نشود (خاموش دستی)
RANGE_SMALL_TP_MIN_N = 20           # حداقل معاملهٔ رنج با مسیر ۱m
RANGE_SMALL_TP_MIN_DELTA_PP = 0.50  # حداقل برتری جمع خالص نسبت به قواعد زندهٔ فعلی (واحد: درصد)
RANGE_SMALL_TP_EVAL_SEC = 300
_SMALL_TP_STATE: dict[str, Any] = {"enabled_rule": None, "since": None, "evaluated_at": 0.0,
                                   "evaluation": {}, "decision": "هنوز ارزیابی نشده", "history": []}
_SMALL_TP_LIVE_RULES = tuple(k for k, v in EXIT_CANDIDATES.items() if v.get("live"))  # «نصف» فقط سنجش


def _small_tp_level(rule: str | None, tp_pct: float | None = None) -> float | None:
    """سطح «بستن کامل» برای قواعد tp و prog_close؛ برای lock/trail/prog_floor ⇒ None (آن‌ها SL را جابه‌جا می‌کنند)."""
    c = EXIT_CANDIDATES.get(str(rule or ""))
    if not c:
        return None
    if c.get("kind") == "tp":
        return float(c["level"])
    if c.get("kind") == "prog_close" and tp_pct:
        return max(float(c["progress"]) * float(tp_pct), float(c["min_pnl"]))
    return None


def _small_tp_evaluate(rows: list[dict]) -> dict:
    """روی معاملات رنج که مسیر ۱m دارند: قواعد را از مسیر ذخیره‌شده (با قواعد زندهٔ فعلی) دوباره حساب کن."""
    keys = ["live"] + list(EXIT_CANDIDATES.keys())
    sums = {k: 0.0 for k in keys}
    better = {k: 0 for k in keys}
    worse = {k: 0 for k in keys}
    per_trade: list[dict] = []
    n = 0
    n_mark = 0
    n_mark_coarse = 0
    n_truth_fixed = 0
    for h in rows:
        try:
            _sid_h = h.get("strategy_id") or ((h.get("settings_snapshot") or {}) if isinstance(h.get("settings_snapshot"), dict) else {}).get("strategy_id")
            if str(_sid_h or "") != "range_scalp":
                continue
            bars = h.get("path_1m")
            if not isinstance(bars, list) or len(bars) < 3:
                continue
            e = float(h.get("fill_entry") or h.get("entry") or 0)
            sl0 = float(h.get("initial_sl") or h.get("original_stop_loss") or h.get("stop_loss") or 0)
            tp = float(h.get("target") or 0)
            if e <= 0 or sl0 <= 0 or tp <= 0:
                continue
            _tr = _truth_of(h)
            w = _whatif_live_variants(h.get("direction"), e, sl0, tp, bars, h.get("range_low"), h.get("range_high"),
                                      h.get("path_mark_1m"), _itv_sec(h.get("path_mark_interval")),
                                      _itv_sec(h.get("path_interval")), _tr)
            if _tr.get("close_t") and not _tr.get("orig_sl_hit"):
                w_nt = _whatif_live_variants(h.get("direction"), e, sl0, tp, bars, h.get("range_low"),
                                             h.get("range_high"), h.get("path_mark_1m"),
                                             _itv_sec(h.get("path_mark_interval")), _itv_sec(h.get("path_interval")))
                n_truth_fixed += 1 if abs(float(w_nt.get("live") or 0) - float(w.get("live") or 0)) > 1e-9 else 0
            n_mark += 1 if h.get("path_mark_1m") else 0
            n_mark_coarse += 1 if (h.get("path_mark_1m") and _itv_sec(h.get("path_mark_interval")) > _itv_sec(h.get("path_interval"))) else 0
        except Exception:
            continue
        n += 1
        for k in keys:
            sums[k] += float(w.get(k) or 0)
            if k != "live":
                d = float(w.get(k) or 0) - float(w.get("live") or 0)
                better[k] += 1 if d > 1e-9 else 0
                worse[k] += 1 if d < -1e-9 else 0
        per_trade.append({"symbol": h.get("symbol"), "direction": h.get("direction"),
                          "opened_at": h.get("opened_at"), **{k: w.get(k) for k in keys}})
    cands = {}
    for k in keys:
        if k == "live":
            continue
        cands[k] = {"sum_net_pct": round(sums[k], 4), "delta_vs_live_pp": round(sums[k] - sums["live"], 4),
                    "better_trades": better[k], "worse_trades": worse[k],
                    "live_capable": k in _SMALL_TP_LIVE_RULES}
    per_trade.sort(key=lambda r: float(r.get("opened_at") or 0), reverse=True)
    return {"n": n, "n_with_mark_path": n_mark, "n_mark_coarse_veto": n_mark_coarse,
            "n_truth_fixed": n_truth_fixed,
            "live_sum_net_pct": round(sums["live"], 4),
            "candidates": cands, "per_trade": per_trade[:25]}


def _small_tp_decide(ev: dict) -> tuple[str | None, str]:
    """روشن کردن خودکار با داده (فقط قواعد قابل اجرای زنده)، خاموش شدن خودکار اگر برتری از بین رفت."""
    cur = _SMALL_TP_STATE.get("enabled_rule")
    if not RANGE_SMALL_TP_AUTO:
        return None, "خاموش دستی (range_small_tp_auto=false)"
    n = int(ev.get("n") or 0)
    if n < int(RANGE_SMALL_TP_MIN_N):
        return None, f"نمونه کم: {n} < {int(RANGE_SMALL_TP_MIN_N)} معاملهٔ رنج با مسیر ۱m"
    cands = {k: v for k, v in (ev.get("candidates") or {}).items() if v.get("live_capable")}
    if not cands:
        return None, "قاعدهٔ قابل اجرا نیست"
    best_k, best_v = max(cands.items(), key=lambda kv: float(kv[1]["delta_vs_live_pp"]))
    best_d = float(best_v["delta_vs_live_pp"])
    if cur:
        cur_d = float((cands.get(cur) or {}).get("delta_vs_live_pp") or -999)
        if cur_d <= 0:
            return None, f"خاموش شد: {cur} دیگر بهتر نیست (Δ={cur_d:+.2f}pp، n={n})"
        if best_k != cur and best_d >= cur_d + float(RANGE_SMALL_TP_MIN_DELTA_PP):
            return best_k, f"تعویض به {best_k}: Δ={best_d:+.2f}pp در برابر {cur} {cur_d:+.2f}pp (n={n})"
        return cur, f"روشن می‌ماند: {cur} Δ={cur_d:+.2f}pp (n={n})"
    if best_d >= float(RANGE_SMALL_TP_MIN_DELTA_PP) and best_v["better_trades"] > best_v["worse_trades"]:
        return best_k, (f"روشن شد: {best_k} Δ={best_d:+.2f}pp نسبت به قواعد فعلی، "
                        f"{best_v['better_trades']} بهتر / {best_v['worse_trades']} بدتر (n={n})")
    return None, (f"خاموش می‌ماند: بهترین {best_k} Δ={best_d:+.2f}pp < +{float(RANGE_SMALL_TP_MIN_DELTA_PP):.2f}pp "
                  f"یا بهتر≤بدتر ({best_v['better_trades']}/{best_v['worse_trades']}، n={n})")


async def _small_tp_refresh(force: bool = False) -> dict:
    now = time.time()
    if not force and now - float(_SMALL_TP_STATE.get("evaluated_at") or 0) < RANGE_SMALL_TP_EVAL_SEC:
        return _SMALL_TP_STATE
    try:
        ev = _small_tp_evaluate(await _memory_context())
    except Exception as e:
        ev = {"error": str(e)[:120]}
    rule, why = _small_tp_decide(ev) if "error" not in ev else (_SMALL_TP_STATE.get("enabled_rule"), "خطای ارزیابی")
    prev = _SMALL_TP_STATE.get("enabled_rule")
    if rule != prev:
        _SMALL_TP_STATE["since"] = now if rule else None
        _SMALL_TP_STATE.setdefault("history", []).insert(0, {"t": round(now, 1), "from": prev, "to": rule, "why": why})
        del _SMALL_TP_STATE["history"][10:]
        _kv_save_async("range_small_tp_state", {"enabled_rule": rule, "since": _SMALL_TP_STATE["since"],
                                                "history": _SMALL_TP_STATE["history"]})
    _SMALL_TP_STATE.update({"enabled_rule": rule, "decision": why, "evaluation": ev, "evaluated_at": now})
    return _SMALL_TP_STATE


def _small_tp_report() -> dict:
    st = _SMALL_TP_STATE
    ev = st.get("evaluation") or {}
    return {
        "mode": "auto" if RANGE_SMALL_TP_AUTO else "off",
        "enabled_rule": st.get("enabled_rule"),
        "enabled_level_pct": _small_tp_level(st.get("enabled_rule")),
        "since": st.get("since"),
        "decision": st.get("decision"),
        "thresholds": {"min_n": RANGE_SMALL_TP_MIN_N, "min_delta_pp": RANGE_SMALL_TP_MIN_DELTA_PP,
                       "candidates_def": EXIT_CANDIDATES, "live_capable": list(_SMALL_TP_LIVE_RULES)},
        "n": ev.get("n"),
        "n_with_mark_path": ev.get("n_with_mark_path"),
        "n_mark_coarse_veto": ev.get("n_mark_coarse_veto"),
        "n_truth_fixed": ev.get("n_truth_fixed"),
        "live_sum_net_pct": ev.get("live_sum_net_pct"),
        "candidates": ev.get("candidates"),
        "per_trade_recent": (ev.get("per_trade") or [])[:12],
        "history": (st.get("history") or [])[:10],
        "enabled_def": EXIT_CANDIDATES.get(str(st.get("enabled_rule") or "")),
        "note": ("مقایسه با «قواعد زندهٔ فعلی رنج» روی مسیر ۱m همان معاملات؛ ×۰٫۲۵ ≈ دلار با notional ۲۵$. "
                 "tp=بستن در سطح سود، lock=کف سود بعد از trigger، trail=کف دنبال‌کننده؛ «نصف» فقط سنجش."),
    }


# ─────────────────────────────────────────────────────────────
# V.2.12.0 — بک‌تست خودکار استراتژی رنج (روی Space؛ نتیجه در گزارش وضعیت)
# ─────────────────────────────────────────────────────────────
BACKTEST_ENABLED = True
BACKTEST_DAYS = 30
BACKTEST_EVERY_HOURS = 24
BACKTEST_FEE_RT_PCT = 0.083      # کارمزد رفت‌وبرگشت اندازه‌گیری‌شده (۴۰ معامله: ۰٫۸۳$ روی ~۲۵$)
BACKTEST_STOP_SLIP_PCT = 0.10    # لغزش اندازه‌گیری‌شدهٔ خروج‌های استاپ
_BACKTEST_STATE: dict[str, Any] = {"state": "idle", "started_at": None, "finished_at": None, "progress": {},
                                   "result": None, "recommend": None, "sources": {}, "fetch_log": {}, "error": None}
_BACKTEST_TASK: Any = None


def _backtest_params() -> dict:
    return {
        "range_max_sl": float(RANGE_MAX_SL_DISTANCE_PCT), "drift_guard": bool(BTC_DRIFT_GUARD_RANGE),
        "drift_min_ret": float(BTC_DRIFT_MIN_RET_PCT), "drift_strong": float(BTC_DRIFT_STRONG_RET_PCT),
        "drift_strong_1h": float(BTC_DRIFT_STRONG_RET_1H_PCT),
        "be_trigger": float(BREAKEVEN_TRIGGER_PCT), "be_min_r": float(BREAKEVEN_MIN_R),
        "be_offset": abs(float(ROUND_TRIP_FRICTION_PCT)),
        "fail_exit": bool(RANGE_FAIL_EXIT), "fail_sec": int(RANGE_FAIL_EXIT_MIN_SEC),
        "fail_mfe": float(RANGE_FAIL_EXIT_MFE_MAX_PCT), "fail_r": float(RANGE_FAIL_EXIT_ADVERSE_R),
        "max_bars": max(1, int(RANGE_TIME_STOP_SEC // 300)), "max_open": 3, "max_same_dir": int(MAX_SAME_DIRECTION_POSITIONS),
        "fee_main": float(BACKTEST_FEE_RT_PCT), "stop_slip": float(BACKTEST_STOP_SLIP_PCT),
        "rs_max_hold_h": float(INTRADAY_MAX_HOLD_HOURS),   # V.2.18.3 — سقف نگه‌داری rel_strength / rs_intraday_50
    }


BACKTEST_TREND_ENABLED = True
BACKTEST_DAILY_ENABLED = True     # V.2.17.0
BACKTEST_INTRADAY_ENABLED = True  # V.2.18.0
BACKTEST_UNIVERSE_N = 50
BACKTEST_DAILY_DAYS = 730
BACKTEST_SUBPROCESS_TIMEOUT_SEC = 3 * 3600   # V.2.14.0: ۹۰ روز + استراتژی‌های جدید


def _trend_backtest_params() -> dict:
    return {
        "min_confluence": int(MIN_CONFLUENCE_REAL), "weak_min_confluence": int(min(MIN_CONFLUENCE_REAL, WEAK_TREND_MIN_CONFLUENCE)),
        "ci_noise_max": float(CI_NOISE_MAX), "er_noise_max": float(ER_NOISE_MAX),
        "min_adx": float(MIN_ADX_1H_FOR_ENTRY), "weak_min_adx": float(WEAK_TREND_MIN_ADX),
        "min_sl": float(MIN_SL_DISTANCE_PCT), "max_sl": float(MAX_SL_DISTANCE_PCT), "min_tp": float(MIN_TP_DISTANCE_PCT),
        "min_rr": float(MIN_RR_REAL), "friction": abs(float(ROUND_TRIP_FRICTION_PCT)),
        "pause_on_btc": bool(AUTO_PAUSE_ENTRIES_ON_BTC_REGIME), "resume_min_conf": float(AUTO_RESUME_MIN_BTC_CONF),
        "pause_bear_stack": bool(AUTO_PAUSE_ON_BTC_BEAR_STACK), "drift_follow": bool(BTC_DRIFT_TREND_FOLLOW),
        "drift_follow_min_conf": float(BTC_DRIFT_FOLLOW_MIN_SYMBOL_CONF),
        "lock_progress": float(PROFIT_LOCK_TRIGGER_RATIO), "lock_min_profit": float(MIN_PROFIT_PCT_TO_LOCK),
        "max_hold_bars": max(1, int(MAX_HOLD_SECONDS // 300)),
        "be_trigger": float(BREAKEVEN_TRIGGER_PCT), "be_min_r": float(BREAKEVEN_MIN_R),
        "be_offset": abs(float(ROUND_TRIP_FRICTION_PCT)),
        "drift_min_ret": float(BTC_DRIFT_MIN_RET_PCT), "drift_strong": float(BTC_DRIFT_STRONG_RET_PCT),
        "drift_strong_1h": float(BTC_DRIFT_STRONG_RET_1H_PCT),
        "max_same_dir": int(MAX_SAME_DIRECTION_POSITIONS), "weak_btc_same_dir_cap": int(WEAK_BTC_MAX_SAME_DIRECTION),
        "fee_main": float(BACKTEST_FEE_RT_PCT), "stop_slip": float(BACKTEST_STOP_SLIP_PCT),
    }


async def _backtest_job() -> None:
    """V.2.12.1: داده (async) ⇒ pickle ⇒ پردازهٔ جدا (رنج + ۸ نسخه + روند) ⇒ نتیجه."""
    import backtest_range as _bt
    import pickle
    import sys as _sys
    import tempfile
    try:
        from watchlist import WATCHLIST as _WL
    except Exception:
        _WL = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "DOT"]
    st = _BACKTEST_STATE
    run_trend = bool(BACKTEST_TREND_ENABLED)
    tfs = ("5m", "15m", "30m", "1h", "4h") if run_trend else ("5m", "15m")
    st.update({"state": "fetching", "started_at": time.time(), "error": None, "sources": {}, "fetch_log": {},
               "progress": {"symbols_done": 0, "symbols_total": len(_WL), "phase": "fetch"}})
    try:
        days = max(7, min(120, int(BACKTEST_DAYS)))
        end_ms = int(time.time() // 300 * 300 * 1000) - 300_000
        start_ms = end_ms - days * 86_400_000
        warm = {"5m": 14 * 3_600_000, "15m": 14 * 3_600_000, "30m": 3 * 86_400_000,
                "1h": 5 * 86_400_000, "4h": 18 * 86_400_000}
        data: dict = {}
        for sym in _WL:
            d = {}
            for itv in tfs:
                w = warm[itv] if not (sym == "BTC" and itv == "15m") else 9 * 86_400_000
                src, rows, log = await _bt.fetch_history(sym, itv, start_ms - w, end_ms)
                d[itv] = rows
                st["sources"][f"{sym}:{itv}"] = src
                st["fetch_log"][f"{sym}:{itv}"] = log[-3:]
            data[sym] = d
            st["progress"]["symbols_done"] += 1
        # V.2.17.0 — کندل روزانهٔ ۲ ساله (ارزان: ~۷۶۰ کندل برای هر نماد)
        daily: dict = {}
        if BACKTEST_DAILY_ENABLED:
            d_end = int(time.time() // 86400 * 86400 * 1000) - 1
            d_start = d_end - (BACKTEST_DAILY_DAYS + 40) * 86_400_000
            st["progress"]["phase"] = "fetch_daily"
            try:   # V.2.20.0 — ۲۰ نماد پرنقدینگی (فهرست ثابت) هم برای tsmom_daily_ext / trend_atr_daily
                import backtest_daily as _bdx
                _d_syms = list(dict.fromkeys(list(_WL) + list(_bdx.EXT_SYMBOLS)))
            except Exception:
                _d_syms = list(_WL)
            for sym in _d_syms:
                try:
                    src_d, rows_d, log_d = await _bt.fetch_history(sym, "1d", d_start, d_end)
                    daily[sym] = rows_d
                    st["sources"][f"{sym}:1d"] = src_d
                    st["fetch_log"][f"{sym}:1d"] = log_d[-3:]
                except Exception as _de:
                    st["fetch_log"][f"{sym}:1d"] = [f"err {str(_de)[:60]}"]
        # V.2.18.0 — ۵۰ نماد اول توبیت (+ طلا) برای پژوهش کوتاه‌مدت (۱۵m، ۱h، ۱d)
        universe_data: dict = {}
        if BACKTEST_INTRADAY_ENABLED:
            import backtest_intraday as _bi
            st["progress"]["phase"] = "fetch_universe"
            try:
                uni, usrc = await _bi.top_symbols(int(BACKTEST_UNIVERSE_N))
            except Exception as _ue:
                uni, usrc = list(_bi.FALLBACK_UNIVERSE[:int(BACKTEST_UNIVERSE_N)]), f"fallback ({str(_ue)[:60]})"
            st["universe"] = {"source": usrc, "symbols": uni}
            st["progress"]["universe_total"] = len(uni)
            st["progress"]["universe_done"] = 0
            d1_end = int(time.time() // 86400 * 86400 * 1000) - 1
            for sym in uni:
                u: dict = {}
                for itv in ("15m", "1h"):
                    if sym in data and data[sym].get(itv):
                        u[itv] = data[sym][itv]
                        continue
                    try:
                        src_u, rows_u, log_u = await _bt.fetch_history(sym, itv, start_ms - 3 * 86_400_000, end_ms)
                        u[itv] = rows_u
                        st["sources"][f"{sym}:{itv}"] = src_u
                    except Exception:
                        u[itv] = []
                if daily.get(sym):
                    u["1d"] = daily[sym]
                else:
                    try:
                        src_u, rows_u, _l = await _bt.fetch_history(sym, "1d", start_ms - 45 * 86_400_000, d1_end)
                        u["1d"] = rows_u
                        st["sources"][f"{sym}:1d"] = src_u
                    except Exception:
                        u["1d"] = []
                universe_data[sym] = u
                st["progress"]["universe_done"] += 1
        # V.2.40.0 — نمادهای اضافهٔ GH با قانون ثابت (پیش از دیدن نتیجه): پرحجم‌ترین‌های توبیت، بدون واچ‌لیست/طلا/میم/استیبل،
        # حجم ۲۴h ≥ ۲۰M$، ≥۱۵۰۰ کندل ۱h از خود توبیت؛ ۴h واقعی توبیت از ۳۵ روز قبل (گرم شدن SMA200)
        gh_ext: dict = {}
        if run_trend and universe_data:
            try:
                import backtest_intraday as _bi2
                _vols = dict(getattr(_bi2, "LAST_VOLS", {}) or {})
                _skip = set(data) | set(_bi2.GOLD_NAMES) | set(_bi2.MEME_NAMES) | set(_bi2.STABLE) | {"MATIC", "POL"}
                _cands = [x for x in universe_data if x not in _skip and x in GH_EXT_CRYPTO_ALLOW
                          and float(_vols.get(x) or 0) >= GH_EXT_MIN_VOL_USDT
                          and len(universe_data[x].get("1h") or []) >= GH_EXT_MIN_1H_BARS
                          and str(st["sources"].get(f"{x}:1h") or "").startswith("toobit")]
                _cands.sort(key=lambda x: -float(_vols.get(x) or 0))
                for x in _cands:
                    if len(gh_ext) >= GH_EXT_MAX:
                        break
                    try:
                        src4, rows4, _l4 = await _bt.fetch_history(x, "4h", start_ms - 35 * 86_400_000, end_ms, order=["toobit"])
                    except Exception:
                        continue
                    if str(src4) == "toobit" and len(rows4) >= 300:
                        gh_ext[x] = {"1h": universe_data[x]["1h"], "4h": rows4}
                    await asyncio.sleep(0.3)
            except Exception as _gxe:
                logger.debug("gh ext select failed: %s", _gxe)
            st["gh_ext"] = sorted(gh_ext)
        # V.2.42.0 — کنترل ۳۶۵ روزه: ۱h حدود ۴۰۰ روزهٔ واچ‌لیست (۴h از همان ساخته می‌شود)؛ خطا ⇒ آن نماد خالی
        long_data: dict = {}
        if run_trend:
            st["progress"]["phase"] = "fetch_long"
            _ld = int(getattr(_bg_reg, "LONG_DAYS", 365)) + int(getattr(_bg_reg, "LONG_WARM_DAYS", 35))
            for sym in dict.fromkeys(list(_WL) + ["BTC"]):
                try:
                    _sl, rows_l, _ll = await _bt.fetch_history(sym, "1h", end_ms - _ld * 86_400_000, end_ms)
                    if rows_l:
                        long_data[sym] = {"1h": rows_l}
                except Exception as _le:
                    st["fetch_log"][f"{sym}:1h_long"] = [f"err {str(_le)[:60]}"]
            st["long_data_n"] = {k: len(v["1h"]) for k, v in long_data.items()}
        btc = data.get("BTC") or {}
        payload = {
            "universe_data": universe_data,
            "daily_data": daily,
            "range_data": {k: {"5m": v.get("5m") or [], "15m": v.get("15m") or []} for k, v in data.items()},
            "btc5": btc.get("5m") or [], "btc15": btc.get("15m") or [],
            "range_params": _backtest_params(),
            "run_trend": run_trend,
            "trend_data": data if run_trend else {},
            "btc_frames": {k: btc.get(k) or [] for k in ("4h", "1h", "15m", "5m")},
            "trend_params": _trend_backtest_params(),
            "gh_ext": gh_ext,   # V.2.40.0
            "long_data": long_data,   # V.2.42.0
        }
        tmpd = tempfile.mkdtemp(prefix="sd_bt_")
        inp, outp, progp = (os.path.join(tmpd, "in.pkl"), os.path.join(tmpd, "out.json"),
                            os.path.join(tmpd, "progress.json"))
        with open(inp, "wb") as f:
            pickle.dump(payload, f)
        del payload
        st["state"] = "running"
        st["progress"]["phase"] = "compute"
        here = os.path.dirname(os.path.abspath(__file__))
        cmd = [_sys.executable, os.path.join(here, "backtest_worker.py"), inp, outp, progp]
        try:
            proc = await asyncio.create_subprocess_exec("nice", "-n", "10", *cmd, cwd=here,
                                                        stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError:
            proc = await asyncio.create_subprocess_exec(*cmd, cwd=here, stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.PIPE)
        t_start = time.time()
        while True:
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
                break
            except asyncio.TimeoutError:
                try:
                    with open(progp, "r", encoding="utf-8") as fp:
                        st["progress"].update(json.load(fp))
                except Exception:
                    pass
                if time.time() - t_start > BACKTEST_SUBPROCESS_TIMEOUT_SEC:
                    proc.kill()
                    raise RuntimeError("backtest subprocess timeout")
        err = b""
        try:
            err = await proc.stderr.read() if proc.stderr else b""
        except Exception:
            pass
        if proc.returncode != 0 or not os.path.isfile(outp):
            raise RuntimeError(f"worker rc={proc.returncode} {err.decode('utf-8', 'ignore')[-300:]}")
        with open(outp, "r", encoding="utf-8") as f:
            out = json.load(f)
        st["result"] = out.get("range")
        st["recommend"] = out.get("recommend")
        st["variants"] = out.get("variants")
        st["trend"] = out.get("trend")
        st["walk_forward"] = out.get("walk_forward")        # V.2.14.0
        st["new_strategies"] = out.get("new_strategies")
        st["rs_robustness"] = out.get("rs_robustness")      # V.2.16.0
        st["daily_research"] = out.get("daily_research")    # V.2.17.0
        st["intraday_research"] = out.get("intraday_research")   # V.2.18.0
        _gh_new = _gh_compact(out.get("github_research"))   # V.2.22.0
        try:   # V.2.42.0 — دادهٔ ۳۶۵ روزه این بار نیامد ⇒ نتیجهٔ قبلی (حداکثر ۱۴ روز) نگه داشته می‌شود؛ بعد از آن «کاغذی»
            _gh_long_carry(_gh_new, st.get("github_research"))
        except Exception as _ce:
            logger.debug("gh long carry failed: %s", _ce)
        st["github_research"] = _gh_new
        st["worker_errors"] = {k: out.get(k) for k in ("range_error", "trend_error", "new_strategies_error", "v216_error",
                                                       "v216_part_errors", "daily_error", "intraday_error", "github_error")
                                                       if out.get(k)} or None
        st["state"] = "done"
        st["finished_at"] = time.time()
        st["app_version"] = APP_VERSION
        st["days"] = int(BACKTEST_DAYS)
        st["rs_max_hold_h"] = float(INTRADAY_MAX_HOLD_HOURS)   # V.2.18.3
        try:
            _matrix_apply_backtest()   # V.2.13.0
        except Exception as _me:
            logger.warning("matrix build failed: %s", _me)
        _kv_save_async("backtest_last", {
            "app_version": APP_VERSION, "days": int(BACKTEST_DAYS),
            "result": _backtest_compact(st["result"], keep_trades=True), "recommend": st["recommend"],
            "variants": st.get("variants"), "trend": _backtest_compact(st.get("trend"), keep_trades=True),
            "walk_forward": st.get("walk_forward"),
            "new_strategies": {k: _backtest_compact(v) for k, v in (st.get("new_strategies") or {}).items()},
            "rs_robustness": st.get("rs_robustness"),
            "daily_research": {k: _backtest_compact(v) for k, v in (st.get("daily_research") or {}).items()},
            "intraday_research": ({**{k: v for k, v in (st.get("intraday_research") or {}).items() if k != "strategies"},
                                   "strategies": {k: _backtest_compact(v) for k, v in
                                                  ((st.get("intraday_research") or {}).get("strategies") or {}).items()}}
                                  if st.get("intraday_research") else None),
            "universe": st.get("universe"),
            "github_research": st.get("github_research"),   # V.2.22.0
            "sources": st["sources"], "finished_at": st["finished_at"], "started_at": st["started_at"],
        })
        try:
            for fn in (inp, outp, progp):
                if os.path.isfile(fn):
                    os.remove(fn)
            os.rmdir(tmpd)
        except Exception:
            pass
    except Exception as e:
        st.update({"state": "error", "error": str(e)[:300], "finished_at": time.time()})
        logger.warning("backtest job failed: %s", e)


def _backtest_compact(res: dict | None, keep_trades: bool = False) -> dict | None:
    if not res:
        return None
    out = {k: v for k, v in res.items() if k != "trades_recent"}
    out["by_symbol"] = {k: {kk: v.get(kk) for kk in ("n", "net_avg_pct", "train", "valid", "win_rate", "profit_factor", "net_total_usdt")}
                        for k, v in (res.get("by_symbol") or {}).items()}
    if keep_trades:
        out["trades_recent"] = (res.get("trades_recent") or [])[-20:]
    return out


def _backtest_maybe_start(force: bool = False) -> bool:
    global _BACKTEST_TASK
    st = _BACKTEST_STATE
    if st.get("state") in ("fetching", "running"):
        return False
    if not force:
        if not BACKTEST_ENABLED:
            return False
        if time.time() - float(_SESSION_START_TS) < 120:
            return False
        last = float(st.get("finished_at") or 0)
        # V.2.12.2 — نتیجهٔ بازگردانده از نسخهٔ قبلی (بدون نسخه‌های رنج/روند) منتظر ۲۴ ساعت نمی‌ماند
        stale_version = (st.get("app_version") != APP_VERSION) or st.get("variants") is None or \
            (BACKTEST_TREND_ENABLED and st.get("trend") is None) or \
            (st.get("days") is not None and int(st.get("days")) != int(BACKTEST_DAYS)) or \
            (st.get("rs_max_hold_h") is not None and float(st.get("rs_max_hold_h")) != float(INTRADAY_MAX_HOLD_HOURS))  # V.2.18.3
        if st.get("state") == "error" and last and time.time() - last < 1800:
            return False
        if last and not stale_version and time.time() - last < float(BACKTEST_EVERY_HOURS) * 3600:
            return False
    try:
        _BACKTEST_TASK = asyncio.get_running_loop().create_task(_backtest_job())
        return True
    except RuntimeError:
        return False


def _intraday_report(ir: dict | None, wf: dict | None) -> dict | None:
    """V.2.18.0 — خلاصهٔ پژوهش کوتاه‌مدت؛ passes = آموزش و اعتبارسنجی > ۰ و n_valid ≥ ۳۰."""
    if not ir:
        return None
    out = {"n_universe": ir.get("n_universe"), "memes": ir.get("memes"), "gold": ir.get("gold"), "strategies": {}}
    for name, r in (ir.get("strategies") or {}).items():
        tr, va, a = r.get("train") or {}, r.get("valid") or {}, r.get("all") or {}
        bysym = sorted((r.get("by_symbol") or {}).items(), key=lambda kv: -(kv[1].get("net_avg_pct") or -99))
        w = (wf or {}).get("intraday:" + name) or {}
        out["strategies"][name] = {
            "passes": bool((tr.get("net_avg_pct") or -1) > 0 and (va.get("net_avg_pct") or -1) > 0 and (va.get("n") or 0) >= 30),
            "trades_per_day": r.get("trades_per_day"), "signals": r.get("signals"), "all": a,
            "train": {k: tr.get(k) for k in ("n", "net_avg_pct", "profit_factor")},
            "valid": {k: va.get(k) for k in ("n", "net_avg_pct", "profit_factor", "net_avg_pct_ci95")},
            "exit_mix": r.get("exit_mix"),
            "by_direction": {k: {kk: v.get(kk) for kk in ("n", "net_avg_pct", "train", "valid")} for k, v in (r.get("by_direction") or {}).items()},
            "best_symbols": [(k, v.get("n"), v.get("net_avg_pct")) for k, v in bysym[:6]],
            "worst_symbols": [(k, v.get("n"), v.get("net_avg_pct")) for k, v in bysym[-4:]],
            "walk_forward": {k: w.get(k) for k in ("passes", "oos_n_selected", "oos_net_selected", "oos_net_all", "current_symbols")} if w else None,
        }
    return out


def _new_strategies_report(ns: dict | None) -> dict:
    out = {}
    for name, r in (ns or {}).items():
        if not isinstance(r, dict):
            continue
        tr, va, a = r.get("train") or {}, r.get("valid") or {}, r.get("all") or {}
        out[name] = {
            "passes": bool((tr.get("net_avg_pct") or -1) > 0 and (va.get("net_avg_pct") or -1) > 0 and (va.get("n") or 0) >= 30),
            "holding": r.get("holding_note"), "fee_model": r.get("fee_model"),
            "signals": r.get("signals"), "trades_per_day": r.get("trades_per_day"),
            "all": a, "train": {k: tr.get(k) for k in ("n", "net_avg_pct", "profit_factor")},
            "valid": {k: va.get(k) for k in ("n", "net_avg_pct", "profit_factor", "net_avg_pct_ci95")},
            "exit_mix": r.get("exit_mix"),
            "by_direction": {k: {kk: v.get(kk) for kk in ("n", "net_avg_pct", "train", "valid")} for k, v in (r.get("by_direction") or {}).items()},
            "by_symbol": {k: {kk: v.get(kk) for kk in ("n", "net_avg_pct", "train", "valid")} for k, v in (r.get("by_symbol") or {}).items()},
        }
    return out


def _backtest_report() -> dict:
    st = _BACKTEST_STATE
    src_counts: dict[str, int] = {}
    for v in (st.get("sources") or {}).values():
        src_counts[str(v or "none")] = src_counts.get(str(v or "none"), 0) + 1
    return {
        "enabled": BACKTEST_ENABLED, "state": st.get("state"), "started_at": st.get("started_at"),
        "result_app_version": st.get("app_version"), "restored": bool(st.get("restored")),
        "result_days": st.get("days"),
        "finished_at": st.get("finished_at"), "progress": st.get("progress"), "error": st.get("error"),
        "data_sources": src_counts,
        "fetch_problems": {k: v for k, v in (st.get("fetch_log") or {}).items()
                           if not (st.get("sources") or {}).get(k)} or None,
        "recommend": st.get("recommend"),
        "result": _backtest_compact(st.get("result")),
        # V.2.12.1
        "range_variants": st.get("variants"),
        "range_variants_passing": [k for k, v in (st.get("variants") or {}).items() if v.get("passes")],
        "trend": _backtest_compact(st.get("trend")),
        "worker_errors": st.get("worker_errors"),
        # V.2.14.0
        "walk_forward": {k: ({kk: v.get(kk) for kk in ("passes", "oos_n_selected", "oos_net_selected", "oos_ci95_selected",
                                                      "oos_n_all", "oos_net_all", "current_symbols", "periods", "rule", "error")}
                             if isinstance(v, dict) else v) for k, v in (st.get("walk_forward") or {}).items()},
        "new_strategies": _new_strategies_report(st.get("new_strategies")),
        "universe": st.get("universe"),
        "intraday_research": _intraday_report(st.get("intraday_research"), st.get("walk_forward")),
        "daily_research": {k: {"passes": v.get("passes"), "n": (v.get("all") or {}).get("n"),
                               "trades_per_day": v.get("trades_per_day"), "all": v.get("all"),
                               "train": {kk: (v.get("train") or {}).get(kk) for kk in ("n", "net_avg_pct", "profit_factor")},
                               "valid": {kk: (v.get("valid") or {}).get(kk) for kk in ("n", "net_avg_pct", "profit_factor")},
                               "old_oos": {kk: (v.get("old_oos") or {}).get(kk) for kk in ("n", "net_avg_pct", "profit_factor")},
                               "recent_90d": {kk: (v.get("recent_90d") or {}).get(kk) for kk in ("n", "net_avg_pct")},
                               "by_direction": {d_: {kk: x.get(kk) for kk in ("n", "net_avg_pct", "train", "valid")}
                                                for d_, x in (v.get("by_direction") or {}).items()},
                               "by_symbol": {s_: {kk: x.get(kk) for kk in ("n", "net_avg_pct")}
                                             for s_, x in (v.get("by_symbol") or {}).items()},
                               "period_days": (v.get("period") or {}).get("days"),
                               "robust": v.get("robust"),   # V.2.20.1
                               "extra_symbols_stats": {kk: (v.get("extra_symbols_stats") or {}).get(kk)
                                                       for kk in ("n", "net_avg_pct", "profit_factor")}
                               if v.get("extra_symbols_stats") else None}
                           for k, v in (st.get("daily_research") or {}).items() if isinstance(v, dict)},
        "rs_robustness": ({k: v for k, v in (st.get("rs_robustness") or {}).items() if k != "variants"}
                          | {"variants_positive_both": [f"L{r['lookback_h']}/H{r['hold_h']}/N{r['top_n']}"
                                                        for r in (st.get("rs_robustness") or {}).get("variants") or []
                                                        if r.get("both_positive")]}) if st.get("rs_robustness") else None,
        "note": ("بک‌تست استراتژی رنج با همان موتور/گیت‌ها/خروج زنده روی داده‌های گذشته؛ «valid» بخش آخر زمان است که در "
                 "تنظیم چیزی دیده نشده. ×۰٫۲۵ ≈ دلار با notional ۲۵$. خبرها و قیمت مارک شبیه‌سازی نمی‌شوند."),
    }


# ─────────────────────────────────────────────────────────────
# V.2.13.0 — جدول تصمیم خودکار: استراتژی × جهت × وضعیت بازار
#   on    : n ≥ MATRIX_MIN_N_ON و خالص در آموزش و اعتبارسنجی هر دو > ۰  ⇒ معاملهٔ عادی
#   probe : خالص کل > ۰ و n ≥ MATRIX_MIN_N_PROBE (یا نمونهٔ کم ولی خانواده/جهت در کل مثبت) ⇒ معامله با سقف هم‌زمان
#   off   : زیان‌ده (n کافی و خالص < ۰) ⇒ فقط کاغذی
#   تضمین «صفر نشدن»: اگر هیچ خانه‌ای on/probe نشد، بهترین خانهٔ غیرزیان‌دهِ قطعی probe می‌شود.
# ─────────────────────────────────────────────────────────────
AUTO_MATRIX = True
MATRIX_MIN_N_ON = 20
MATRIX_MIN_N_PROBE = 8
MATRIX_PROBE_MAX_OPEN = 1
MATRIX_DEMOTE_MIN_N = 10
MATRIX_DEMOTE_AVG_PCT = -0.10
MATRIX_LIVE_WINDOW_SEC = 14 * 86400
MATRIX_FAMILIES = ("trend", "range", "rel_strength", "tsmom_daily", "rs_intraday_50", "trend_atr_daily")   # V.2.20.0
LIVE_NEW_FAMILIES = ("rel_strength", "tsmom_daily", "rs_intraday_50", "trend_atr_daily")
INTRADAY_LIVE_FAMILIES = ("rs_intraday_50",)   # خانه‌ها از backtest.intraday_research
DAILY_FAMILIES = ("tsmom_daily", "trend_atr_daily")   # خانه‌ها بدون وضعیت بازار ۱۵m: market = "any"
MATRIX_DIRS = ("long", "short")
MATRIX_MARKETS = ("bull", "bear", "neutral")
_MATRIX: dict[str, Any] = {"policy": {}, "built_at": None, "source_finished_at": None, "demoted": {},
                           "live_checked_at": 0.0, "liveness_pick": None}
_pending_matrix: dict[str, dict] = {}


def _matrix_family(strategy_id: str | None) -> str:
    s_ = str(strategy_id or "")
    if s_ == "range_scalp":
        return "range"
    if s_ in LIVE_NEW_FAMILIES or s_ in GH_LIVE_STRATEGIES:   # V.2.22.1
        return s_
    return "trend"


def _cell_market(family: str) -> str:
    return "any" if family in DAILY_FAMILIES else _market_state_now()


def _market_state_now() -> str:
    import backtest_range as _bt
    st = (_BTC_DRIFT_CACHE.get("state") or {})
    return _bt.market_state(str(st.get("dir") or "none"), st.get("h1"), st.get("ret_pct"))


def _build_matrix_policy(cells: dict) -> dict:
    """از آمار خانه‌های بک‌تست ⇒ وضعیت هر خانه + دلیل (متن فارسی)."""
    pol: dict[str, dict] = {}
    fam_dir: dict[str, list] = {}
    for k, c in (cells or {}).items():
        fam, d, _m = k.split("|")
        fam_dir.setdefault(f"{fam}|{d}", []).append(c)

    def agg(lst):
        n = sum(int(c.get("n") or 0) for c in lst)
        if not n:
            return 0, None
        return n, sum(float(c.get("net_avg_pct") or 0) * int(c.get("n") or 0) for c in lst) / n

    for fam in MATRIX_FAMILIES:
        for d in MATRIX_DIRS:
            fn, favg = agg(fam_dir.get(f"{fam}|{d}") or [])
            for m in (("any",) if fam in DAILY_FAMILIES else MATRIX_MARKETS):
                k = f"{fam}|{d}|{m}"
                c = (cells or {}).get(k) or {}
                n = int(c.get("n") or 0)
                net = c.get("net_avg_pct")
                trn, val = c.get("train_net"), c.get("valid_net")
                ci = c.get("ci95") or [None, None]
                row = {"n": n, "net_avg_pct": net, "train_net": trn, "valid_net": val, "ci95": ci,
                       "family_dir_n": fn, "family_dir_net": round(favg, 4) if favg is not None else None}
                ext = c.get("net_ex_top")
                row.update(top_symbol=c.get("top_symbol"), net_ex_top=ext)
                if n >= MATRIX_MIN_N_ON and (trn or -1) > 0 and (val or -1) > 0 and ext is not None and ext < 0:
                    row.update(status="probe", why=(f"آموزش {trn:+.3f}٪ و اعتبارسنجی {val:+.3f}٪ مثبت، ولی بدون "
                                                    f"{c.get('top_symbol')} منفی ({ext:+.3f}٪) ⇒ با احتیاط (تمرکز سود)"))
                elif n >= MATRIX_MIN_N_ON and (trn or -1) > 0 and (val or -1) > 0:
                    row.update(status="on", why=f"اثبات‌شده: n={n}، آموزش {trn:+.3f}٪، اعتبارسنجی {val:+.3f}٪")
                elif n >= MATRIX_MIN_N_PROBE and (net or -1) > 0 and (val is None or val > 0):
                    row.update(status="probe", why=f"امیدوارکننده: n={n}، خالص {net:+.3f}٪ (هنوز اثبات‌نشده)")
                elif n >= MATRIX_MIN_N_PROBE and (net or -1) > 0:   # V.2.18.9 — مثبت کل ولی اعتبارسنجی منفی ⇒ نویز
                    row.update(status="off", why=f"خالص {net:+.3f}٪ ولی اعتبارسنجی {val:+.3f}٪ منفی (n={n}) ⇒ خاموش")
                elif n < MATRIX_MIN_N_PROBE and favg is not None and favg > 0 and fn >= MATRIX_MIN_N_PROBE:
                    row.update(status="probe", why=f"نمونهٔ کم (n={n})؛ {fam}/{d} در کل مثبت ({favg:+.3f}٪، n={fn})")
                elif n >= MATRIX_MIN_N_PROBE and (net or 0) < 0:
                    row.update(status="off", why=f"زیان‌ده: n={n}، خالص {net:+.3f}٪")
                else:
                    row.update(status="off", why=f"داده کافی/مثبت نیست (n={n})")
                pol[k] = row
    # تضمین صفر نشدن: اگر هیچ on/probe نیست ⇒ بهترین خانه‌ای که قطعاً زیان‌ده نیست (کران بالای ۹۵٪ ≥ ۰)
    pick = None
    if not any(v["status"] in ("on", "probe") for v in pol.values()):
        cands = [(k, v) for k, v in pol.items() if v["n"] >= MATRIX_MIN_N_PROBE and v.get("net_avg_pct") is not None
                 and (v["ci95"] or [None, None])[1] is not None and v["ci95"][1] >= 0]
        if cands:
            k, v = max(cands, key=lambda kv: float(kv[1]["net_avg_pct"]))
            v.update(status="probe", why=f"بهترین گزینهٔ موجود (برای صفر نشدن ورود): خالص {v['net_avg_pct']:+.3f}٪، n={v['n']}")
            pick = k
    _MATRIX["liveness_pick"] = pick
    return pol


# V.2.18.2 — شرط BTC هر استراتژی قدرت نسبی با داده انتخاب می‌شود (نه دستی):
#   strict = بازدهٔ BTC هم‌جهت + بایاس ۱h هم‌جهت؛ ret = فقط بازدهٔ BTC هم‌جهت.
#   انتخاب: از نسخه‌هایی که در آموزش و اعتبارسنجی مثبت‌اند (n_valid ≥ ۳۰)، آن‌که «جمع سود اعتبارسنجی» (n × میانگین) بیشتری دارد؛
#   هیچ‌کدام قبول نشد ⇒ strict (و خانه‌های جدول خودشان on/probe/off را تعیین می‌کنند).
GATE_VARIANTS: dict[tuple[str, str], dict[str, tuple[str, str]]] = {
    ("rs_intraday_50", "long"): {"strict": ("intraday", "rs_intraday_50"), "ret": ("intraday", "rs_intraday_50_ret")},
    ("rs_intraday_50", "short"): {"strict": ("intraday", "rs_intraday_50_short"), "ret": ("intraday", "rs_intraday_50_short_ret")},
    ("rel_strength", "long"): {"strict": ("new", "rel_strength"), "ret": ("new", "rel_strength_ret")},
}
GATED_FAMILIES = ("rs_intraday_50", "rel_strength")
GATE_MIN_VALID_N = 30


def _variant_result(src: str, name: str) -> dict:
    st = _BACKTEST_STATE
    if src == "intraday":
        return (((st.get("intraday_research") or {}).get("strategies") or {}).get(name)) or {}
    return ((st.get("new_strategies") or {}).get(name)) or {}


def _variant_wf(src: str, name: str) -> dict:
    wf = _BACKTEST_STATE.get("walk_forward") or {}
    return wf.get(("intraday:" if src == "intraday" else "") + name) or {}


def _gate_choice(fam: str, d: str) -> dict:
    opts = GATE_VARIANTS.get((fam, d)) or {}
    rows: dict[str, dict] = {}
    for mode, (src, name) in opts.items():
        r = _variant_result(src, name)
        if not r or not (r.get("all") or {}).get("n"):
            continue
        tr, va = r.get("train") or {}, r.get("valid") or {}
        trn, van, vn = tr.get("net_avg_pct"), va.get("net_avg_pct"), int(va.get("n") or 0)
        rows[mode] = {"variant": name, "n": (r.get("all") or {}).get("n"), "net_avg_pct": (r.get("all") or {}).get("net_avg_pct"),
                      "train_net": trn, "valid_net": van, "valid_n": vn, "trades_per_day": r.get("trades_per_day"),
                      "valid_sum_pct": round(vn * float(van or 0), 3),
                      "passes": bool((trn or -1) > 0 and (van or -1) > 0 and vn >= GATE_MIN_VALID_N)}
    passing = {m: v for m, v in rows.items() if v["passes"]}
    if passing:
        mode = max(passing, key=lambda m: (passing[m]["valid_sum_pct"], m == "strict"))
        why = (f"{mode}: بیشترین سود اعتبارسنجی بین نسخه‌های قبول‌شده "
               f"(Σ {passing[mode]['valid_sum_pct']:+.2f}٪، n={passing[mode]['valid_n']})")
    elif rows:
        mode = "strict" if "strict" in rows else next(iter(rows))
        why = "هیچ نسخه‌ای در آموزش و اعتبارسنجی قبول نشد ⇒ strict (خانه‌های جدول تصمیم می‌گیرند)"
    else:
        mode, why = "strict", "نتیجهٔ بک‌تست این نسخه‌ها نیست ⇒ strict"
    return {"mode": mode, "variant": (opts.get(mode) or ("", ""))[1], "why": why, "compare": rows}


def _gate_mode(fam: str, d: str) -> str:
    g = ((_MATRIX.get("gate_mode") or {}).get(f"{fam}:{d}") or {})
    return str(g.get("mode") or "strict")


def _exit_mode(fam: str, d: str) -> str:
    """V.2.18.6 — نوع خروج انتخاب‌شده برای خانواده/جهت (پیش‌فرض base = TP ۲R، بدون جابه‌جایی SL)."""
    import backtest_exits as _bx
    m = str(((_MATRIX.get("exit_mode") or {}).get(f"{fam}:{d}") or {}).get("mode") or "base")
    return m if m in _bx.EXIT_MODES else "base"


def _exit_tp_r(fam: str, d: str) -> float:
    import backtest_exits as _bx
    return float(_bx.EXIT_MODES[_exit_mode(fam, d)].get("tp_r", 2.0))


def _symbol_filter_for(family: str, direction: str) -> list | None:
    sf = _MATRIX.get("symbol_filter") or {}
    k = f"{family}:{direction}"
    if k in sf:
        return sf.get(k)
    if family in GATED_FAMILIES and direction != "long":
        return None
    return sf.get(family)


def _matrix_enforce_rules() -> int:
    """V.2.18.10 — قواعد 2.18.9 روی جدول فعلی (هم بعد از ساخت، هم بعد از بازیابی از KV بعد از دیپلوی):
    ۱) خانهٔ «آزمایشی» با n ≥ ۸ و اعتبارسنجی منفی ⇒ خاموش (به‌جز انتخاب «صفر نشدن ورود»)
    ۲) خانواده/جهتی که هیچ نسخه‌اش در آموزش و اعتبارسنجی قبول نشد ⇒ همهٔ خانه‌ها خاموش. خروجی: تعداد خانه‌های خاموش‌شده."""
    pol = _MATRIX.get("policy") or {}
    n_off = 0
    pick = _MATRIX.get("liveness_pick")
    for k, v in pol.items():
        val = v.get("valid_net")
        if (v.get("status") == "probe" and k != pick and int(v.get("n") or 0) >= MATRIX_MIN_N_PROBE
                and val is not None and float(val) < 0):
            v.update(status="off", why=f"خالص {float(v.get('net_avg_pct') or 0):+.3f}٪ ولی اعتبارسنجی {float(val):+.3f}٪ منفی "
                                      f"(n={v.get('n')}) ⇒ خاموش")
            n_off += 1
    for _fd, _gc in (_MATRIX.get("gate_mode") or {}).items():
        _rows = (_gc or {}).get("compare") or {}
        if _rows and not any(r.get("passes") for r in _rows.values()):
            _fam, _d = _fd.split(":")
            for k, v in pol.items():
                if k.startswith(f"{_fam}|{_d}|") and v.get("status") != "off":
                    v.update(status="off", why=f"{_fam}/{_d} در بک‌تست (آموزش و اعتبارسنجی) قبول نشد ⇒ خاموش")
                    n_off += 1
    return n_off


def _matrix_apply_backtest() -> bool:
    """بعد از هر بک‌تست (یا بازیابی): جدول را از خانه‌های رنج + روند بساز."""
    st = _BACKTEST_STATE
    cells: dict = {}
    for res in (st.get("result"), st.get("trend")):
        for k, v in ((res or {}).get("cells") or {}).items():
            cells[k] = v
    for fam in INTRADAY_LIVE_FAMILIES:   # V.2.18.1
        for k, v in ((((st.get("intraday_research") or {}).get("strategies") or {}).get(fam) or {}).get("cells") or {}).items():
            cells[k] = v
    for fam in LIVE_NEW_FAMILIES:   # V.2.15.0
        if fam in DAILY_FAMILIES or fam in INTRADAY_LIVE_FAMILIES:
            continue
        for k, v in (((st.get("new_strategies") or {}).get(fam) or {}).get("cells") or {}).items():
            cells[k] = v
    _daily_pass: dict[str, bool] = {}
    for fam in DAILY_FAMILIES:   # V.2.17.0 — از پژوهش ۲ ساله
        dr = (st.get("daily_research") or {}).get(fam) or {}
        _daily_pass[fam] = bool(dr.get("passes"))
        for k, v in (dr.get("cells") or {}).items():
            cells[k] = v
    # V.2.18.2 — خانواده‌های قدرت نسبی: هر جهت از نسخهٔ انتخاب‌شدهٔ شرط BTC (+ انتخاب نماد همان نسخه)
    sym_filter: dict[str, list] = {}
    gate_mode: dict[str, dict] = {}
    exit_mode: dict[str, dict] = {}
    for (fam, d), opts in GATE_VARIANTS.items():
        ch = _gate_choice(fam, d)
        gate_mode[f"{fam}:{d}"] = ch
        src, name = opts.get(ch["mode"]) or opts["strict"]
        r = _variant_result(src, name)
        if not r:
            continue
        pre = f"{fam}|{d}|"
        # V.2.18.6 — نوع خروج با داده (روی همان ورودهای نسخهٔ انتخاب‌شده)؛ خانه‌ها و انتخاب نماد از همان خروج
        import backtest_exits as _bx
        ech = _bx.choose(r.get("exit_modes"))
        exit_mode[f"{fam}:{d}"] = ech
        r_used = (r.get("exit_modes") or {}).get(ech["mode"]) if ech["mode"] != "base" else None
        for k in [k for k in cells if k.startswith(pre)]:
            del cells[k]
        cells.update({k: v for k, v in ((r_used or r).get("cells") or {}).items() if k.startswith(pre)})
        wf = (r_used.get("walk_forward") or {}) if r_used else _variant_wf(src, name)
        if wf.get("passes") and wf.get("current_symbols"):
            sym_filter[f"{fam}:{d}"] = list(wf["current_symbols"])
            for k in [k for k in cells if k.startswith(pre)]:
                del cells[k]
            cells.update({k: v for k, v in (wf.get("cells_selected") or {}).items() if k.startswith(pre)})
    _MATRIX["gate_mode"] = gate_mode
    _MATRIX["exit_mode"] = exit_mode
    if not cells:
        return False
    # V.2.14.0 — انتخاب نماد: فقط اگر روش انتخاب در آزمون خارج از نمونه (walk-forward) جواب داده
    for fam in MATRIX_FAMILIES:
        if fam in GATED_FAMILIES:
            continue
        wf = ((st.get("walk_forward") or {}).get(fam) or (st.get("walk_forward") or {}).get("intraday:" + fam) or {})
        if wf.get("passes") and wf.get("current_symbols"):
            sym_filter[fam] = list(wf["current_symbols"])
            for k in [k for k in cells if k.startswith(fam + "|")]:
                del cells[k]
            cells.update(wf.get("cells_selected") or {})
    _MATRIX["symbol_filter"] = sym_filter
    _MATRIX["policy"] = _build_matrix_policy(cells)
    _matrix_enforce_rules()   # V.2.18.9/2.18.10
    # V.2.17.0 — استراتژی روزانه فقط اگر آزمون ۲ ساله (شامل بخش قدیمی خارج از نمونه) قبول شده
    for fam, ok_ in _daily_pass.items():
        if not ok_:
            for k, v in (_MATRIX["policy"] or {}).items():
                if k.startswith(fam + "|") and v.get("status") != "off":
                    v.update(status="off", why="آزمون ۲ ساله قبول نشد")
    # V.2.16.0 — rel_strength «روشن» فقط اگر نسخه‌های همسایه هم مثبت باشند (پایداری)؛ وگرنه حداکثر آزمایشی
    _rob = st.get("rs_robustness") or {}
    if _rob and not _rob.get("robust"):
        for k, v in (_MATRIX["policy"] or {}).items():
            if k.startswith("rel_strength|") and v.get("status") == "on":
                v.update(status="probe", why=(v.get("why") or "") + f" · نسخه‌های همسایه پایدار نیستند "
                                                                    f"({_rob.get('share_both_positive')})")
    _MATRIX["built_at"] = time.time()
    _MATRIX["source_finished_at"] = st.get("finished_at")
    _MATRIX["source_days"] = st.get("days")
    _MATRIX["demoted"] = {}
    _kv_save_async("strategy_matrix", {k: v for k, v in _MATRIX.items() if k != "live_checked_at"})
    return True


def _matrix_status(cell: str) -> str | None:
    if not (AUTO_MATRIX and _MATRIX.get("policy")):
        return None
    if cell in (_MATRIX.get("demoted") or {}):
        return "off"
    return ((_MATRIX.get("policy") or {}).get(cell) or {}).get("status") or "off"


def range_signal_only_effective() -> bool:
    """وقتی جدول خودکار فعال است، تصمیم رنج با جدول است (نه کلید دستی)."""
    if AUTO_MATRIX and _MATRIX.get("policy"):
        return False
    return bool(RANGE_SIGNAL_ONLY)


async def _matrix_live_check(force: bool = False) -> None:
    """تنزل خودکار: اگر نتیجهٔ زندهٔ یک خانهٔ روشن در ۱۴ روز اخیر بد شد ⇒ off تا بک‌تست بعدی."""
    if not (AUTO_MATRIX and _MATRIX.get("policy")):
        return
    now = time.time()
    if not force and now - float(_MATRIX.get("live_checked_at") or 0) < 300:
        return
    _MATRIX["live_checked_at"] = now
    agg: dict[str, list] = {}
    try:
        rows = await _memory_context()
    except Exception:
        rows = []
    built = float(_MATRIX.get("built_at") or 0)
    for h in rows:
        cell = h.get("matrix_cell")
        if not cell or str(h.get("status") or "") == "open":
            continue
        if float(h.get("closed_at") or 0) < max(built - MATRIX_LIVE_WINDOW_SEC, now - MATRIX_LIVE_WINDOW_SEC):
            continue
        try:
            n_usd = float(h.get("notional_actual") or 25.0)
            _pv = next((h.get(k) for k in ("exchange_pnl", "realized_pnl", "pnl_usdt", "pnl") if h.get(k) is not None), None)
            if _pv is None:
                continue
            pnl = float(_pv)
            agg.setdefault(cell, []).append(pnl / n_usd * 100.0)
        except (TypeError, ValueError):
            continue
    dem = dict(_MATRIX.get("demoted") or {})
    for cell, vals in agg.items():
        if cell in dem or _matrix_status(cell) not in ("on", "probe"):
            continue
        if len(vals) >= MATRIX_DEMOTE_MIN_N:
            avg = sum(vals) / len(vals)
            if avg < MATRIX_DEMOTE_AVG_PCT:
                dem[cell] = {"ts": now, "n": len(vals), "avg_pct": round(avg, 4),
                             "why": f"نتیجهٔ زنده {avg:+.3f}٪ در {len(vals)} معامله < {MATRIX_DEMOTE_AVG_PCT}٪"}
    _MATRIX["demoted"] = dem
    _MATRIX["live"] = {k: {"n": len(v), "avg_pct": round(sum(v) / len(v), 4)} for k, v in agg.items() if v}


# V.2.16.0 — بزرگ شدن خودکار حجم فقط بعد از اثبات زنده
SIZE_UP_ENABLED = True
SIZE_UP_MULT = 2.0
SIZE_UP_MIN_LIVE_N = 30
SIZE_MAX_LOSS_PCT_EQUITY = 1.0


def _matrix_size_mult(cell: str | None, sl_pct: float, equity: float, base_notional: float) -> tuple[float, str]:
    """۱× پیش‌فرض. تا SIZE_UP_MULT فقط اگر: خانه «on» (نه probe)، ≥ ۳۰ معاملهٔ زندهٔ همین خانه، میانگین زنده > ۰ و
    ≥ نصف بک‌تست؛ و ضرر تا SL ≤ ۱٪ موجودی."""
    if not (SIZE_UP_ENABLED and cell and AUTO_MATRIX):
        return 1.0, "base"
    if _matrix_status(cell) != "on":
        return 1.0, "base: خانه on نیست"
    live = (_MATRIX.get("live") or {}).get(cell) or {}
    bt = ((_MATRIX.get("policy") or {}).get(cell) or {}).get("net_avg_pct")
    n, avg = int(live.get("n") or 0), live.get("avg_pct")
    if n < SIZE_UP_MIN_LIVE_N or avg is None or avg <= 0 or (bt is not None and avg < 0.5 * float(bt)):
        return 1.0, f"base: اثبات زنده کافی نیست (n={n}، میانگین {avg})"
    mult = float(SIZE_UP_MULT)
    if equity > 0 and sl_pct > 0 and base_notional > 0:
        cap = (equity * SIZE_MAX_LOSS_PCT_EQUITY / 100.0) / (base_notional * sl_pct / 100.0)
        mult = max(1.0, min(mult, cap))
    return round(mult, 3), f"اثبات‌شده زنده (n={n}، {avg:+.3f}٪) ⇒ ×{mult:.2f}"


def _matrix_report() -> dict:
    pol = _MATRIX.get("policy") or {}
    mkt = _market_state_now() if pol else None
    return {
        "enabled": AUTO_MATRIX, "built_at": _MATRIX.get("built_at"), "source_days": _MATRIX.get("source_days"),
        "market_now": mkt,
        "allowed_now": sorted(k for k in pol if (k.endswith(f"|{mkt}") or k.endswith("|any"))
                              and _matrix_status(k) in ("on", "probe")) if mkt else [],
        "policy": pol, "demoted": _MATRIX.get("demoted"), "live": _MATRIX.get("live"),
        "liveness_pick": _MATRIX.get("liveness_pick"),
        "symbol_filter": _MATRIX.get("symbol_filter") or {},
        "exit_mode": {k: {kk: v.get(kk) for kk in ("mode", "why", "compare")}
                      for k, v in (_MATRIX.get("exit_mode") or {}).items()},   # V.2.18.6
        "gate_mode": {k: {kk: v.get(kk) for kk in ("mode", "variant", "why", "compare")}
                      for k, v in (_MATRIX.get("gate_mode") or {}).items()},
        "size_rules": {"enabled": SIZE_UP_ENABLED, "max_mult": SIZE_UP_MULT, "min_live_n": SIZE_UP_MIN_LIVE_N,
                       "max_loss_pct_equity": SIZE_MAX_LOSS_PCT_EQUITY},
        "rules": {"on_min_n": MATRIX_MIN_N_ON, "probe_min_n": MATRIX_MIN_N_PROBE, "probe_max_open": MATRIX_PROBE_MAX_OPEN,
                  "demote_min_n": MATRIX_DEMOTE_MIN_N, "demote_avg_pct": MATRIX_DEMOTE_AVG_PCT},
        "note": ("هر سیگنال: وضعیت بازار (bull/bear/neutral از BTC) ⇒ خانهٔ استراتژی×جهت×بازار ⇒ on: معامله، "
                 "probe: معامله با سقف هم‌زمان، off: فقط کاغذی. جدول هر بار بعد از بک‌تست خودکار ساخته می‌شود."),
    }


# ─────────────────────────────────────────────────────────────
# V.2.15.0 — rel_strength زنده (همان تعریف بک‌تست، backtest_strategies.py)
# ─────────────────────────────────────────────────────────────
RS_ENABLED = False   # V.2.35.0 — موتور قدیمی؛ فقط GH و روزانه (پیشنهاد ایجنت منتقد)
RS_TOP_N = 2
RS_MIN_RS_PCT = 1.0
RS_SL_ATR = 2.0
RS_SL_MIN_PCT, RS_SL_MAX_PCT = 0.8, 4.0
RS_TP_R = 2.0
RS_MAX_HOLD_SEC = 24 * 3600
_RS_STATE: dict[str, Any] = {"last_slot": None, "last_scan": None, "last_result": None}


# ─────────────────────────────────────────────────────────────
# V.2.19.0 — «آزمون رو به جلو»: پول واقعی فقط بعد از اثبات روی داده‌ای که در هیچ انتخابی دیده نشده
# ۱۰–۱۲ اکتبر: بک‌تست rel_strength +۰٫۴۶٪ و rs_intraday_50 +۰٫۹۴٪، ولی ۱۱ معاملهٔ زنده ≈ −۰٫۸٪ میانگین (−۲٫۳$).
# علت: انتخاب‌های پیاپی روی همان ۹۰ روز (شرط BTC، خروج، نماد، سقف زمان) ⇒ بک‌تست خوش‌بینانه.
# قاعده: هر خانواده/جهت یا «کاغذی رو به جلو» است یا «زنده».
#   کاغذی ⇒ زنده: ≥ ۳۰ معاملهٔ کاغذی جدید با همان قواعد (خروج، مهلت، کارمزد + لغزش استاپ) و میانگین خالص ≥ +۰٫۱۰٪
#   زنده ⇒ کاغذی: ≥ ۸ معاملهٔ زندهٔ بعد از زنده شدن با میانگین < ۰
# ─────────────────────────────────────────────────────────────
FORWARD_FAMILIES = ("rel_strength", "rs_intraday_50", "trend", "range")   # V.2.19.1 — ترند/رنج هم (لبهٔ بک‌تست ≈ ۰)
FWD_PROMOTE_MIN_N = 30
FWD_PROMOTE_MIN_AVG_PCT = 0.10
FWD_DEMOTE_MIN_N = 8
FWD_DEMOTE_MAX_AVG_PCT = 0.0
# V.2.20.0 — «زندهٔ کوچک» زودتر: n ≥ ۱۵ کاغذی با میانگین خالص > ۰ ⇒ زنده با حداقل حجم و فقط ۱ پوزیشن هم‌زمان
# برای همان خانواده/جهت. تنزل همان قبلی (≥ ۸ زنده با میانگین < ۰) + توقف زود: ≥ ۴ زنده با میانگین ≤ −۱٪.
# زندهٔ کوچک ⇒ زندهٔ کامل: ≥ ۱۵ زنده با میانگین ≥ +۰٫۱۰٪.
FWD_MICRO_MIN_N = 15
FWD_MICRO_MIN_AVG_PCT = 0.0
FWD_MICRO_MAX_OPEN = 1
FWD_MICRO_FAST_STOP_N = 4
FWD_MICRO_FAST_STOP_AVG_PCT = -1.0
FWD_MICRO_FULL_N = 15
_FWD: dict[str, dict] = {}
_FWD_CHECKED: dict[str, float] = {"ts": 0.0}


def _fwd_get(fam: str, d: str) -> dict:
    k = f"{fam}:{d}"
    if k not in _FWD:
        _FWD[k] = {"mode": "paper", "since": time.time(), "why": "V.2.19.0 — شروع آزمون کاغذی رو به جلو",
                   "paper": {"n": 0, "sum_net_pct": 0.0, "wins": 0}, "history": []}
    st = _FWD[k]
    st.setdefault("paper", {"n": 0, "sum_net_pct": 0.0, "wins": 0})
    st.setdefault("history", [])
    return st


def _fwd_save() -> None:
    try:
        _kv_save_async("forward_state", {k: v for k, v in _FWD.items()})
    except Exception:
        pass


def _fwd_set_mode(fam: str, d: str, mode: str, why: str, tier: str | None = None) -> None:
    st = _fwd_get(fam, d)
    st["history"] = (st.get("history") or [])[-9:] + [{"ts": time.time(), "from": st.get("mode"), "to": mode,
                                                       "tier": tier, "why": why}]
    st.update(mode=mode, since=time.time(), why=why, tier=(tier if mode == "live" else None))
    if mode == "paper":
        st["paper"] = {"n": 0, "sum_net_pct": 0.0, "wins": 0}
    _fwd_save()


def _fwd_record_paper(rec: dict) -> None:
    """هر معاملهٔ کاغذی رو به جلوی بسته‌شده ⇒ آمار همان خانواده/جهت (فقط بعد از شروع همین دورهٔ کاغذی)."""
    fam, d = str(rec.get("fwd_family") or _matrix_family(rec.get("strategy_id"))), str(rec.get("direction") or "")
    if fam not in FORWARD_FAMILIES:
        return
    st = _fwd_get(fam, d)
    if st.get("mode") != "paper" or float(rec.get("opened_at") or 0) < float(st.get("since") or 0):
        return
    p = st["paper"]
    net = float(rec.get("net_pct") or 0)
    p["n"] = int(p.get("n") or 0) + 1
    p["sum_net_pct"] = round(float(p.get("sum_net_pct") or 0) + net, 4)
    p["wins"] = int(p.get("wins") or 0) + (1 if net > 0 else 0)
    _fwd_save()


LEGACY_LIVE_ENABLED = False   # V.2.35.0 — موتورهای قدیمی (trend/range/weak_trend/rel_strength/rs_intraday) خودکار زنده نشوند


async def _fwd_check(force: bool = False) -> None:
    """هر ۵ دقیقه: ارتقا (کاغذی ⇒ زنده) یا تنزل (زنده ⇒ کاغذی)."""
    now = time.time()
    if not force and now - float(_FWD_CHECKED.get("ts") or 0) < 300:
        return
    _FWD_CHECKED["ts"] = now
    rows = None
    for fam in FORWARD_FAMILIES:
        for d in ("long", "short"):
            st = _fwd_get(fam, d)
            if st["mode"] == "paper":
                if not LEGACY_LIVE_ENABLED:
                    continue   # V.2.35.0 — آمار کاغذی جمع می‌شود ولی ارتقا به زنده نه
                p = st["paper"]
                n = int(p.get("n") or 0)
                avg = float(p.get("sum_net_pct") or 0) / n if n else None
                if n >= FWD_PROMOTE_MIN_N and avg is not None and avg >= FWD_PROMOTE_MIN_AVG_PCT:
                    _fwd_set_mode(fam, d, "live", f"کاغذی رو به جلو: n={n}، میانگین {avg:+.3f}٪ ≥ {FWD_PROMOTE_MIN_AVG_PCT}٪ ⇒ زنده",
                                  tier="full")
                elif n >= FWD_MICRO_MIN_N and avg is not None and avg > FWD_MICRO_MIN_AVG_PCT:   # V.2.20.0
                    _fwd_set_mode(fam, d, "live", f"کاغذی رو به جلو: n={n}، میانگین {avg:+.3f}٪ > ۰ ⇒ زندهٔ کوچک "
                                                  f"(حداقل حجم، {FWD_MICRO_MAX_OPEN} پوزیشن)", tier="micro")
                continue
            if rows is None:
                try:
                    rows = await _memory_context()
                except Exception:
                    rows = []
            vals = []
            for h in rows or []:
                if _matrix_family(h.get("strategy_id")) != fam or str(h.get("direction") or "") != d:
                    continue
                if str(h.get("status") or "") == "open" or float(h.get("closed_at") or 0) < float(st.get("since") or 0):
                    continue
                try:
                    pv = next((h.get(k) for k in ("exchange_pnl", "realized_pnl", "pnl_usdt", "pnl") if h.get(k) is not None), None)
                    if pv is None:
                        continue
                    vals.append(float(pv) / float(h.get("notional_actual") or 25.0) * 100.0)
                except (TypeError, ValueError):
                    continue
            st["live"] = {"n": len(vals), "avg_pct": round(sum(vals) / len(vals), 4) if vals else None}
            _lavg = sum(vals) / len(vals) if vals else 0.0
            if len(vals) >= FWD_DEMOTE_MIN_N and _lavg < FWD_DEMOTE_MAX_AVG_PCT:
                _fwd_set_mode(fam, d, "paper", f"زنده: n={len(vals)}، میانگین {_lavg:+.3f}٪ < ۰ ⇒ کاغذی رو به جلو")
            elif st.get("tier") == "micro" and len(vals) >= FWD_MICRO_FAST_STOP_N and _lavg <= FWD_MICRO_FAST_STOP_AVG_PCT:
                _fwd_set_mode(fam, d, "paper", f"زندهٔ کوچک: n={len(vals)}، میانگین {_lavg:+.3f}٪ ≤ {FWD_MICRO_FAST_STOP_AVG_PCT}٪ "
                                               f"⇒ توقف زود، کاغذی رو به جلو")
            elif st.get("tier") == "micro" and len(vals) >= FWD_MICRO_FULL_N and _lavg >= FWD_PROMOTE_MIN_AVG_PCT:
                st["tier"] = "full"
                st["history"] = (st.get("history") or [])[-9:] + [{"ts": time.time(), "from": "live", "to": "live", "tier": "full",
                                                                   "why": f"زندهٔ کوچک: n={len(vals)}، میانگین {_lavg:+.3f}٪ ⇒ کامل"}]
                _fwd_save()


def _fwd_report() -> dict:
    out = {}
    for k, st in sorted(_FWD.items()):
        p = st.get("paper") or {}
        n = int(p.get("n") or 0)
        out[k] = {"mode": st.get("mode"), "tier": st.get("tier"), "since": st.get("since"), "why": st.get("why"),
                  "paper": {"n": n, "avg_net_pct": round(float(p.get("sum_net_pct") or 0) / n, 4) if n else None,
                            "wins": p.get("wins"), "need_n": FWD_PROMOTE_MIN_N, "need_n_micro": FWD_MICRO_MIN_N},
                  "live": st.get("live"), "history": (st.get("history") or [])[-5:]}
    return {"rules": {"promote": f"کاغذی ⇒ زنده: n ≥ {FWD_PROMOTE_MIN_N} و میانگین خالص ≥ +{FWD_PROMOTE_MIN_AVG_PCT}٪",
                      "promote_micro": f"کاغذی ⇒ زندهٔ کوچک: n ≥ {FWD_MICRO_MIN_N} و میانگین خالص > ۰ "
                                       f"(حداقل حجم، {FWD_MICRO_MAX_OPEN} پوزیشن هم‌زمان)",
                      "micro_fast_stop": f"زندهٔ کوچک ⇒ کاغذی: n ≥ {FWD_MICRO_FAST_STOP_N} و میانگین ≤ {FWD_MICRO_FAST_STOP_AVG_PCT}٪",
                      "demote": f"زنده ⇒ کاغذی: n ≥ {FWD_DEMOTE_MIN_N} و میانگین < {FWD_DEMOTE_MAX_AVG_PCT}٪",
                      "paper_costs": "کارمزد ۰٫۰۸٪ + لغزش استاپ روی SL"},
            "families": out}


def _fwd_micro_busy(family: str, direction: str, fst: dict | None = None) -> str | None:
    """V.2.20.0 — زندهٔ کوچک: حداکثر FWD_MICRO_MAX_OPEN پوزیشن باز برای همان خانواده/جهت."""
    fst = fst if fst is not None else _fwd_get(family, direction)
    if fst.get("mode") != "live" or fst.get("tier") != "micro":
        return None
    n_ = sum(1 for m in _tracked.values()
             if isinstance(m, dict) and m.get("status") == "open" and _matrix_family(m.get("strategy_id")) == family
             and m.get("direction") == direction)
    if n_ >= FWD_MICRO_MAX_OPEN:
        return f"forward_micro_busy: {family}/{direction} زندهٔ کوچک ({n_}/{FWD_MICRO_MAX_OPEN})"
    return None


async def _can_open_rel_strength(symbol: str, direction: str, entry: float, stop_loss: float, target: float,
                                 score: Any, diagnostics: dict | None, _probe: bool = False,
                                 family: str = "rel_strength") -> tuple[bool, str]:
    """گیت‌های حساب (کلید، ضرر روزانه، قفل‌ها، کول‌داون، سقف پوزیشن) + هندسهٔ rel_strength + جدول خودکار.
    گیت‌های مخصوص روند (امتیاز، CI/ER/ADX، تریگر ۵m، تعقیب، SL ≤ ۱٫۵۵٪) اعمال نمی‌شوند — همان‌طور که بک‌تست شد."""
    key = _norm_symbol(symbol)
    if not toobit_private.keys_configured():
        return False, "کلید Toobit تنظیم نشده"
    if daily_loss_breached():
        return False, "سقف ضرر روزانه پر شده"
    meta = _tracked.get(key)
    if meta and meta.get("status") == "open":
        return False, "پوزیشن ریل همین نماد باز است"
    if family in ("rel_strength", "trend_atr_daily") and direction != "long":   # V.2.18.2 — rs_intraday_50 شورت هم دارد
        return False, f"{family} فقط لانگ"
    for fn, label in ((_global_sl_remaining, "قفل سراسری پس از چند SL"),):
        left = fn()
        if left > 0:
            return False, f"{label} ({left}s باقی)"
    for fn, label in ((_low_profit_remaining, "قفل کم‌سود نماد"), (_symbol_sl_lock_remaining, "قفل نماد پس از چند SL"),
                      (_post_close_remaining, "کول‌داون پس از بستن")):
        left = fn(key)
        if left > 0:
            return False, f"{label} ({left}s باقی)"
    try:
        e, sl, tp = float(entry), float(stop_loss), float(target)
    except (TypeError, ValueError):
        return False, "قیمت نامعتبر"
    sgn = 1.0 if direction == "long" else -1.0
    sl_pct = sgn * (e - sl) / e * 100.0
    if family == "tsmom_daily":   # V.2.17.0 — SL روزانه ۳٪ تا سقف زنده
        lo_, hi_, rr_ = 3.0, float(TSMOM_LIVE_SL_CAP_PCT), 1.0
    elif family == "trend_atr_daily":   # V.2.20.0 — SL ۲٫۵×ATR روزانه (۳٪ تا سقف)
        lo_, hi_, rr_ = 3.0, float(TREND_ATR_SL_CAP_PCT), 1.0
    else:
        lo_, hi_, rr_ = RS_SL_MIN_PCT, RS_SL_MAX_PCT, 0.95   # V.2.18.6 — خروج tp1r (TP = ۱R) مجاز
    ordered = (sl < e < tp) if direction == "long" else (tp < e < sl)
    if not ordered or not (lo_ - 1e-9 <= sl_pct <= hi_ + 1e-9) or abs(tp - e) < rr_ * abs(e - sl):
        return False, f"هندسهٔ {family} نامعتبر (SL {sl_pct:.2f}٪)"
    bal_preview = await _equity_balance()
    max_pos = _effective_max_positions(bal_preview)
    n_open, rows = await _open_positions_count()
    if rows is None:
        n_open, rows = 99, []
    if n_open >= max_pos:
        return False, f"حداکثر {max_pos} پوزیشن باز مجاز است (الان {n_open})"
    _cr = _committed_risk_block(_estimate_adverse_usdt(_effective_min_notional(float(bal_preview or 0)), e, sl))
    if family in ("tsmom_daily", "trend_atr_daily") and _cr:   # V.2.36.2
        return False, f"{family}: {_cr}"
    if family in ("tsmom_daily", "trend_atr_daily"):   # V.2.35.0 — روزانه‌ها هم قانون اسلات GH را رعایت کنند
        _top_free = [n for n in _gh_rank_order()[:GH_RESERVE_TOP_N] if _gh_open_count(n) < _gh_max_open(n)]
        if n_open >= max_pos - 1 and max_pos > 1 and _top_free:
            return False, f"{family}: آخرین اسلات برای {GH_RESERVE_TOP_N} استراتژی برتر GH نگه داشته می‌شود"
        _nd = sum(1 for m in _tracked.values() if isinstance(m, dict) and m.get("status") == "open"
                  and str(m.get("strategy_id") or "") in ("tsmom_daily", "trend_atr_daily"))
        if _nd >= 1:
            return False, f"{family}: سقف ۱ پوزیشن روزانهٔ هم‌زمان"
    for r in rows:
        if isinstance(r, dict) and _norm_symbol(str(r.get("symbol") or "")) == key and toobit_private.parse_position_qty(r) > 0:
            return False, "روی صرافی برای این نماد پوزیشن باز است"
    same_dir = sum(1 for m in _tracked.values() if isinstance(m, dict) and m.get("status") == "open" and m.get("direction") == direction)
    if same_dir >= int(MAX_SAME_DIRECTION_POSITIONS):
        return False, f"سقف پوزیشن هم‌جهت ({same_dir}/{MAX_SAME_DIRECTION_POSITIONS})"
    if family in DAILY_FAMILIES:   # سقف پوزیشن هم‌زمان برای خانوادهٔ روزانه (SL بزرگ)
        _cap_d = _daily_max_open(family)
        _n_d = sum(1 for m in _tracked.values()
                   if isinstance(m, dict) and m.get("status") == "open" and m.get("strategy_id") == family)
        if _n_d >= _cap_d:
            return False, f"{family}: سقف {_cap_d} پوزیشن هم‌زمان"
    mkt = _cell_market(family)
    cell = f"{family}|{direction}|{mkt}"
    cstat = _matrix_status(cell) if AUTO_MATRIX else "probe"
    _sf = _symbol_filter_for(family, direction)
    if _sf is not None and key not in set(_sf) and cstat != "off":
        _paper_open(symbol, direction, e, sl, tp, family, "matrix_symbol_off", score=score,
                    drift=dict(_BTC_DRIFT_CACHE.get("state") or {}), time_stop_sec=float(_family_max_hold(family)),
                    extra={"matrix_cell": cell, "market_state": mkt})
        return False, f"matrix_symbol_off: {key} در فهرست نمادهای سازگار {family} نیست · کاغذی ثبت شد"
    if cstat is None:
        cstat = "off"   # بدون جدول ⇒ فقط بعد از بک‌تست
    if cstat == "off":
        _paper_open(symbol, direction, e, sl, tp, family, "matrix_off", score=score,
                    drift=dict(_BTC_DRIFT_CACHE.get("state") or {}),
                    time_stop_sec=float(_family_max_hold(family)),
                    extra={"matrix_cell": cell, "market_state": mkt})
        why = (((_MATRIX.get("policy") or {}).get(cell) or {}).get("why") or "جدول هنوز ساخته نشده/داده نیست")
        return False, f"matrix_off: {cell} — {why} · کاغذی ثبت شد"
    if cstat == "probe":
        n_probe = sum(1 for m in _tracked.values()
                      if isinstance(m, dict) and m.get("status") == "open" and m.get("matrix_status") == "probe")
        if n_probe >= MATRIX_PROBE_MAX_OPEN:
            return False, f"matrix_probe_busy: {cell} ({n_probe}/{MATRIX_PROBE_MAX_OPEN})"
    if family in FORWARD_FAMILIES:   # V.2.19.0 — پول واقعی فقط برای خانواده/جهت ثابت‌شده در آزمون رو به جلو
        _fst = _fwd_get(family, direction)
        if _fst.get("mode") != "live":
            _em = _exit_mode(family, direction) if family in GATED_FAMILIES else "base"
            ok_p = _paper_open(symbol, direction, e, sl, tp, family, "forward_test", score=score,
                               drift=dict(_BTC_DRIFT_CACHE.get("state") or {}), time_stop_sec=float(_family_max_hold(family)),
                               extra={"matrix_cell": cell, "market_state": mkt, "exit_mode": _em, "sl_pct0": round(sl_pct, 4),
                                      "fwd_family": family})
            _pn = int((_fst.get("paper") or {}).get("n") or 0)
            return False, (f"forward_test: {family}/{direction} در آزمون کاغذی رو به جلو "
                           f"({_pn}/{FWD_MICRO_MIN_N} کوچک، {FWD_PROMOTE_MIN_N} کامل) · "
                           f"{'کاغذی ثبت شد' if ok_p else 'کاغذی ثبت نشد (نماد در کاغذی باز است)'}")
        _micro_busy = _fwd_micro_busy(family, direction, _fst)
        if _micro_busy:
            return False, _micro_busy
    _pending_strategy[key] = family
    _pending_matrix[key] = {"matrix_cell": cell, "market_state": mkt, "matrix_status": cstat}
    if family in ("rel_strength", "rs_intraday_50"):   # V.2.18.6 — خروج همین پوزیشن ثابت می‌ماند
        _pending_matrix[key]["exit_mode"] = _exit_mode(family, direction)
    return True, "ok"


# ─────────────────────────────────────────────────────────────
# V.2.17.0 — tsmom_daily زنده (همان تعریف backtest_daily.py)؛ فقط اگر آزمون ۲ ساله قبول و خانهٔ جدول اجازه دهد
# ─────────────────────────────────────────────────────────────
TSMOM_ENABLED = True
TSMOM_SYMBOLS = ("BTC", "ETH", "SOL", "BNB")
TSMOM_LIVE_SL_CAP_PCT = 6.0      # ضرر تا SL با حداقل notional ۲۵$ ≈ ۱٫۵$ (~۳٪ موجودی ۴۵$)
TSMOM_MAX_HOLD_SEC = 14 * 86400
_TSMOM_STATE: dict[str, Any] = {"last_day": None, "last_result": None}

# V.2.20.0 — گسترش tsmom به ۲۰ نماد پرنقدینگی (فهرست ثابت backtest_daily.EXT_SYMBOLS) فقط اگر آزمون ۲ ساله
# tsmom_daily_ext قبول شود (شامل بخش قدیمی خارج از نمونه + سودِ جداگانهٔ نمادهای غیر از ۴ نماد اصلی).
TSMOM_EXT_MAX_OPEN = 2

# V.2.20.0 — trend_atr_daily (از پژوهش روندگیری حرفه‌ای کریپتو): شکست سقف ۲۰ روزه + EMA50 + BTC بالای EMA50؛
# فقط لانگ؛ SL اولیه ۲٫۵×ATR؛ خروج: بسته شدن روزانه زیر استاپ متحرک شاندلیه (بیشترین بسته شدن − ۲٫۵×ATR) یا ۳۰ روز.
# زنده فقط اگر آزمون ۲ ساله قبول و خانهٔ جدول اجازه دهد.
TREND_ATR_ENABLED = True
TREND_ATR_SL_CAP_PCT = 10.0      # حجم حداقل (~۲۵$) ⇒ ضرر SL ≤ ۲٫۵$
TREND_ATR_MAX_HOLD_SEC = 30 * 86400
TREND_ATR_MAX_OPEN = 1
_TATR_STATE: dict[str, Any] = {"last_day": None, "last_result": None}


def _daily_research(name: str) -> dict:
    return ((_BACKTEST_STATE.get("daily_research") or {}).get(name) or {})


def _tsmom_ext_on() -> bool:
    return bool(_daily_research("tsmom_daily_ext").get("passes"))


def _tsmom_symbols() -> list[str]:
    syms = list(TSMOM_SYMBOLS)
    if _tsmom_ext_on():
        try:
            import backtest_daily as _bdx
            syms = list(dict.fromkeys(syms + list(_bdx.EXT_SYMBOLS)))
        except Exception:
            pass
    return syms


def _trend_atr_symbols() -> list[str]:
    try:
        import backtest_daily as _bdx
        return list(_bdx.EXT_SYMBOLS)
    except Exception:
        return list(TSMOM_SYMBOLS)


def _daily_max_open(family: str) -> int:
    if family == "trend_atr_daily":
        return int(TREND_ATR_MAX_OPEN)
    return int(TSMOM_EXT_MAX_OPEN) if _tsmom_ext_on() else 1


async def _daily_closed(symbol: str, limit: int = 60):
    df = await toobit_market.get_klines(symbol, "1d", limit=limit)
    if df is None or len(df) < 30:
        return None
    try:
        if float(df["timestamp"].iloc[-1]) + 86_400_000 > time.time() * 1000:   # کندل در حال تشکیل
            df = df.iloc[:-1]
    except Exception:
        pass
    return df


def _tsmom_why(c: float, pc: float, e20: float, e20p: float, pe: float) -> dict:
    """V.2.18.2 — چرا امروز سیگنال tsmom نیست (عدد هر شرط)."""
    slope = "up" if e20 > e20p else ("down" if e20 < e20p else "flat")
    if c > e20 and pc > pe:
        why = "قیمت از قبل بالای EMA20 بود — کراس تازه نیست (ورود فقط روز کراس)"
    elif c < e20 and pc < pe:
        why = "قیمت از قبل زیر EMA20 بود — کراس تازه نیست (ورود فقط روز کراس)"
    elif c > e20 and slope != "up":
        why = "کراس به بالا، ولی شیب EMA20 (۵ روز) صعودی نیست"
    elif c < e20 and slope != "down":
        why = "کراس به پایین، ولی شیب EMA20 (۵ روز) نزولی نیست"
    else:
        why = "شرط کراس + شیب برقرار نیست"
    return {"close": round(c, 6), "ema20": round(e20, 6), "ema20_5d_ago": round(e20p, 6),
            "prev_close": round(pc, 6), "prev_ema20": round(pe, 6), "ema_slope_5d": slope,
            "dist_to_ema20_pct": round((c / e20 - 1.0) * 100.0, 3), "why": why}


# V.2.18.5 — پنجرهٔ اسکن: فقط ابتدای هر بازه (همان زمانی که بک‌تست وارد می‌شود)؛ هر بازه یک بار (ذخیره در KV).
# قبلاً هر دیپلوی وسط بازه اسکن را دوباره اجرا می‌کرد و (مثلاً NEAR ۱۰ اکتبر) نمادی که دستی بسته شده بود دوباره باز می‌شد.
SCAN_WINDOW_SEC = 20 * 60
TSMOM_SCAN_WINDOW_SEC = 6 * 3600
_SCAN_SLOTS: dict[str, int] = {}
_SCAN_NOTES: dict[str, str] = {}


def _scan_gate(name: str, slot: int, since_start: float, min_offset: float, window: float = SCAN_WINDOW_SEC) -> bool:
    if since_start < min_offset:
        return False
    if _SCAN_SLOTS.get(name) == slot:
        return False
    if not (_REMOTE_STATE_LOADED.get("scan_slots") or time.time() - float(_SESSION_START_TS) > 300):
        return False
    if since_start > window:
        _SCAN_NOTES[name] = (f"اسکن این بازه انجام نشد: {int(since_start // 60)} دقیقه از شروع بازه گذشته بود "
                             f"(پنجره {int(window // 60)} دقیقه) — منتظر بازهٔ بعد")
        return False
    return True


def _save_scan_last() -> None:
    """V.2.18.9 — آخرین نتیجهٔ اسکن‌ها در KV تا بعد از دیپلوی هم در گزارش بماند."""
    try:
        _kv_save_async("scan_last", {"rs_intraday_50": _RSI_STATE.get("last_result"),
                                     "rel_strength": _RS_STATE.get("last_result"),
                                     "tsmom_daily": _TSMOM_STATE.get("last_result"),
                                     "trend_atr_daily": _TATR_STATE.get("last_result")})
    except Exception:
        pass


def _scan_mark(name: str, slot: int) -> None:
    _SCAN_SLOTS[name] = int(slot)
    _SCAN_NOTES.pop(name, None)
    _kv_save_async("scan_slots", dict(_SCAN_SLOTS))


async def _symbols_closed_since(ts0: float) -> set[str]:
    """V.2.18.5 — نمادهایی که از ts0 به بعد بسته شده‌اند (صرافی + حافظه؛ شامل بستن دستی) ⇒ در همین بازه دوباره باز نشوند."""
    out: set[str] = set()
    try:
        rows = await _exchange_recent_closed(20)
    except Exception:
        rows = []
    for r in rows or []:
        try:
            if float(r.get("closed_at") or 0) >= ts0:
                out.add(_norm_symbol(str(r.get("symbol") or "")))
        except (TypeError, ValueError):
            continue
    for h in list(_history)[:40]:   # جدیدترین‌ها اول هستند
        try:
            if float(h.get("closed_at") or 0) >= ts0:
                out.add(_norm_symbol(str(h.get("symbol") or "")))
        except (TypeError, ValueError, AttributeError):
            continue
    return out


async def _tsmom_scan(force: bool = False) -> dict:
    """روزی یک بار (≥ ۰۰:۰۵ UTC): کراس بسته شدن روزانه با EMA20 روزانه + شیب ⇒ ورود (لانگ یا شورت طبق جدول)."""
    now = time.time()
    day = int(now // 86400)
    if not TSMOM_ENABLED:
        return {}
    if not force and (_TSMOM_STATE.get("last_day") == day
                      or not _scan_gate("tsmom_daily", day, now - day * 86400, 300, TSMOM_SCAN_WINDOW_SEC)):
        return {}
    _TSMOM_STATE["last_day"] = day
    _scan_mark("tsmom_daily", day)
    res: dict[str, Any] = {"ts": now, "day_utc": time.strftime("%Y-%m-%d", time.gmtime(day * 86400)), "checks": [], "opened": []}
    _TSMOM_STATE["last_result"] = res
    try:
        import backtest_strategies as _bs
        for s_ in _tsmom_symbols():
            df = await _daily_closed(s_)
            if df is None:
                res["checks"].append({"symbol": s_, "reason": "کندل روزانه نیست"})
                continue
            rows = list(zip(df["timestamp"].tolist(), df["open"].tolist(), df["high"].tolist(),
                            df["low"].tolist(), df["close"].tolist()))
            closes = [float(r[4]) for r in rows]
            ema = _bs._ema(closes, 20)
            atr = _bs._atr([tuple(float(v) for v in r) for r in rows])
            k = len(rows) - 1
            e20, e20p, pe, a = ema[k], ema[k - 5], ema[k - 1], atr[k]
            if None in (e20, e20p, pe, a):
                res["checks"].append({"symbol": s_, "reason": "داده کافی نیست"})
                continue
            c, pc = closes[k], closes[k - 1]
            d = "long" if (c > e20 > e20p and pc <= pe) else ("short" if (c < e20 < e20p and pc >= pe) else None)
            if not d:
                res["checks"].append({"symbol": s_, "signal": None, **_tsmom_why(c, pc, e20, e20p, pe)})
                continue
            sl_pct = max(3.0, 2 * float(a) / c * 100)
            if sl_pct > TSMOM_LIVE_SL_CAP_PCT:
                res["checks"].append({"symbol": s_, "signal": d, "skipped": f"SL {sl_pct:.2f}٪ > سقف {TSMOM_LIVE_SL_CAP_PCT}٪"})
                continue
            lp = await toobit_market.get_live_price(s_)
            px = float((lp or {}).get("price") or c)
            sgn = 1 if d == "long" else -1
            sl = px * (1 - sgn * sl_pct / 100)
            tp = px * (1 + sgn * 4 * sl_pct / 100)   # TP دور (سقف ایمنی)؛ خروج اصلی کراس EMA20 روزانه است
            out = await open_real_trade(s_, d, px, sl, tp, 95,
                                        diagnostics={"strategy_id": "tsmom_daily", "ema20_daily": e20, "atr_daily": a})
            res["opened"].append({"symbol": s_, "direction": d, "ok": bool((out or {}).get("ok")),
                                  "reason": str((out or {}).get("reason") or (out or {}).get("error") or "")[:160]})
    except Exception as e:
        res["error"] = str(e)[:200]
    return res


async def _tsmom_exit_check(meta: dict, key: str) -> str | None:
    """روزی یک بار برای هر پوزیشن: بسته شدن روزانه آن‌طرف EMA20 ⇒ خروج روند؛ ۱۴ روز ⇒ پایان مهلت."""
    now = time.time()
    if now - float(meta.get("opened_at") or now) >= TSMOM_MAX_HOLD_SEC:
        return "tsmom_time_stop"
    day = int(now // 86400)
    if meta.get("tsmom_checked_day") == day or now - day * 86400 < 300:
        return None
    meta["tsmom_checked_day"] = day
    try:
        import backtest_strategies as _bs
        df = await _daily_closed(key)
        if df is None:
            return None
        if float(df["timestamp"].iloc[-1]) / 1000 + 86400 <= float(meta.get("opened_at") or 0):
            return None   # هنوز کندل روزانهٔ بعد از ورود بسته نشده
        closes = [float(x) for x in df["close"].tolist()]
        e20 = _bs._ema(closes, 20)[-1]
        if e20 is None:
            return None
        c = closes[-1]
        if (meta.get("direction") == "long" and c < e20) or (meta.get("direction") == "short" and c > e20):
            return "tsmom_trend_exit"
    except Exception:
        return None
    return None


# ─────────────────────────────────────────────────────────────
# V.2.22.0 — استراتژی‌های متن‌باز گیت‌هاب (freqtrade-strategies): بک‌تست ۹۰ روزه در worker +
# کاغذی رو به جلو هر ساعت (همان simulate روی کندل‌های تازهٔ ۲۰ نماد). فقط کاغذی؛ هیچ مسیری به open_real_trade.
# ─────────────────────────────────────────────────────────────
GH_PAPER_ENABLED = True
GH_FORWARD_EVERY_SEC = 3600
_GH_TASK = None

# V.2.22.1 — زنده (به خواست کاربر بدون انتظار ۱۵ کاغذی): فقط استراتژی‌هایی که بک‌تست ۹۰ روزه را قبول کرده‌اند،
# با حداقل حجم، ۱ پوزیشن هم‌زمان برای هر استراتژی. محافظت: ≥ ۴ زنده با میانگین ≤ −۱٪ یا ≥ ۸ زنده با میانگین < ۰
# ⇒ خودکار به کاغذی (کاغذی رو به جلو ادامه دارد؛ برگشت به زنده فقط با کاغذی n ≥ ۱۵ و میانگین > ۰).
# V.2.24.0 — ردشده‌ها (fadx/freinforced/fsample/fsupertrend/trendfollow/الگوی V) حذف؛ ۵ نامزد جدید ۱h/۴h.
# هر کدام فقط اگر بک‌تست ۹۰ روزه قبول شود زنده می‌شود (_gh_live_mode).
import backtest_github as _bg_reg   # V.2.31.0 — فهرست از خود بک‌تست (پاک‌سازی: ردشده‌ها حذف شدند)
GH_LIVE_STRATEGIES = tuple(_bg_reg.STRATEGIES)
GH_GOLD_STRATEGIES = tuple(n for n in GH_LIVE_STRATEGIES if n.startswith("gx_"))
# V.2.24.1 — gh_awesomemacd رد شد (valid −۰٫۷۹٪) ⇒ حذف
# V.2.24.5 — فقط کاغذی (لبهٔ خیلی باریک ‎+۰٫۰۵٪ با SL ۱۰٪ و TP ۱٪؛ اسلات استراتژی‌های قوی‌تر را می‌گرفت)
GH_PAPER_ONLY = tuple(_bg_reg.family("pb_utbot_4h"))
# V.2.38.0 — پایه‌های تازه اول فقط کاغذی؛ زنده وقتی نسخهٔ قبول‌شده ≥۱۰ معاملهٔ کاغذی رو به جلو با میانگین خالص > ۰ داشته باشد
GH_PAPER_FIRST = tuple(n for _b in getattr(_bg_reg, "NEW_BASES_V2380", ()) for n in _bg_reg.family(_b))
GH_PAPER_FIRST_MIN_N = 10   # V.2.31.0 — UT Bot ۴h با حاشیهٔ خیلی کم قبول شد (va +0.01) ⇒ فقط کاغذی
# V.2.31.0 — اولویت با سودده‌ترین (امتیاز بک‌تست = سود کل ÷ بیشترین افت):
GH_RANK_SIZE_MULT = (1.5, 1.25)   # رتبهٔ ۱ و ۲ حجم بیشتر؛ بقیه ۱×
GH_RANK_MAX_LOSS_PCT = 4.0   # V.2.36.2 توضیح: فقط بزرگ‌کردن حجم رتبه را محدود می‌کند (حجم زیر ۲۵$ نمی‌رود)؛ سقف کل ریسک = _committed_risk_block        # سقف ضرر تخمینی هر پوزیشن (در حد ضرر) = ۸٪ موجودی
GH_RESERVE_TOP_N = 2              # آخرین اسلات خالی فقط برای دو استراتژی برتر
GH_MAX_TRADE_LOSS_USDT = 1.45   # V.2.38.2 — سقف ضرر تخمینی هر ورود GH (≈ نصف سقف روزانهٔ ۳$) ⇒ حجم کوچک‌تر برای SL پهن
GH_SIZE_FLOOR_USDT = 21.0   # V.2.39.1 — کف notional ورود GH (قبلاً ۱۵$ = دقیقاً کف مارجین ۳$؛ صرافی حجم را رو به پایین گرد کرد
#                              ⇒ BNB/ETH با مارجین ۲٫۸$ باز و فوراً بسته شدند). ۲۱$ = ۳$×۵×۱٫۴ تا بعد از گرد شدن هم ≥ ۳$ بماند
GH_MAX_TRADE_LOSS_HARD_USDT = 2.6   # V.2.39.1 — سقف مطلق ضرر تخمینی هر ورود GH بعد از گردکردن (منتقد)
GH_SIZEUP_FWD_N, GH_SIZEUP_FWD_AVG = 20, 0.0     # بزرگ‌کردن حجم رتبه فقط با کاغذی رو به جلو n ≥ ۲۰ و میانگین > ۰
GH_VETO_CHECK_SEC = 300
GH_RANK_MIN_N = 100               # V.2.32.1 — رتبهٔ ۱ و ۲ فقط با حداقل ۱۰۰ معامله در بک‌تست
GH_STRATEGY_SHORT = {n: True for n in GH_GOLD_STRATEGIES}   # بقیه فقط لانگ (مثل اصلشان)
GH_SL_CAP_PCT = 10.0
GH_LIVE_ENABLED = True
GH_LIVE_MAX_OPEN = 1
GH_TOP1_MAX_OPEN = 2   # V.2.31.2 — رتبهٔ ۱ می‌تواند هر دو اسلات را بگیرد (بک‌تست هم پوزیشن هم‌زمان روی نمادهای مختلف دارد)
GH_LIVE_TP_FAR_PCT = 30.0          # بدون ROI (volsystem) ⇒ TP دور فقط برای سفارش صرافی
GH_DEMOTE_FAST_N, GH_DEMOTE_FAST_AVG = 4, -1.0
GH_DEMOTE_N, GH_DEMOTE_AVG = 8, 0.0
_GH_LIVE: dict = {}
_GH_LIVE_STATE: dict = {"last_slot": None, "last_result": None}


def _gh_long_carry(new: dict | None, prev: dict | None, now: float | None = None) -> int:
    """V.2.42.0 — long.status == unavailable ⇒ نتیجهٔ ok/fail قبلی همان استراتژی اگر ≤ LONG_CARRY_DAYS روز عمر دارد."""
    now = float(now or time.time())
    ps = ((prev or {}).get("strategies") or {})
    n = 0
    for name, r in ((new or {}).get("strategies") or {}).items():
        lg = (r or {}).get("long") or {}
        old = ((ps.get(name) or {}).get("long") or {}) if isinstance(ps.get(name), dict) else {}
        if lg.get("status") == "unavailable" and old.get("status") in ("ok", "fail") and old.get("ts") \
                and now - float(old["ts"]) <= float(_bg_reg.LONG_CARRY_DAYS) * 86400:
            r["long"] = dict(old, carried=True)
            n += 1
    return n


def _gh_compact(res: dict | None) -> dict | None:
    if not isinstance(res, dict):
        return None
    keep = ("passes", "all", "train", "valid", "trades_per_day", "exit_mix", "robust", "by_dir", "source", "timeframe",
            "error", "max_dd_pct", "worst_trade_pct", "capped", "mc", "wf", "ext", "one", "long")   # V.2.36.0 mc/wf — V.2.26.1 — بدون این‌ها انتخاب خانواده فقط با سود کل بود
    return {**{k: v for k, v in res.items() if k != "strategies"},
            "strategies": {n: {k: v.get(k) for k in keep} for n, v in (res.get("strategies") or {}).items()
                           if isinstance(v, dict)}}


_GH_BTC_REG: dict = {"ts": 0.0, "reg": None}


async def _gh_btc_regime(max_age: float = 600.0):
    """V.2.26.0 — رژیم BTC (۴h، بسته شدن بالای EMA50) با کش ۱۰ دقیقه؛ خطا ⇒ آخرین مقدار."""
    import backtest_github as _bg
    if not (_GH_BTC_REG["reg"] is not None and time.time() - _GH_BTC_REG["ts"] < max_age):
        try:
            rows = await _gh_closed_rows("BTC", "4h", 200)
            if len(rows) >= 60:
                _GH_BTC_REG.update(ts=time.time(), reg=_bg.btc_regime(rows))
        except Exception:
            pass
    # V.2.39.3 — دادهٔ کهنه (دریافت ناموفق > ۸ ساعت یا آخرین کندل قدیمی) ⇒ None: ورود _btc/bear بسته، خروج BTC رد
    _r = _GH_BTC_REG["reg"]
    if _r is None or time.time() - float(_GH_BTC_REG["ts"] or 0) > 8 * 3600:
        return None
    try:
        if _r[0] and float(_r[0][-1]) < (time.time() - 8 * 3600) * 1000:
            return None
    except Exception:
        return None
    return _r


def _gh_symbols() -> list:
    """V.2.25.0 — واچ‌لیست + نماد طلای بک‌تست (XAU، وگرنه PAXG/XAUT)."""
    try:
        from watchlist import WATCHLIST as _WLg
    except Exception:
        _WLg = list(TSMOM_SYMBOLS)
    g = str((_BACKTEST_STATE.get("github_research") or {}).get("gold_symbol") or "XAU")
    return list(dict.fromkeys(list(_WLg) + [g] + _gh_ext_symbols()))   # V.2.40.0 — + نمادهای اضافهٔ سنجیده‌شده


GH_EXT_LIVE = True            # V.2.40.0 — ورود زنده روی نمادهای اضافه (فقط استراتژی‌های ext_ok و بدون وتوی کاغذی اضافه)
GH_EXT_MAX = 15
GH_EXT_MIN_VOL_USDT = 20_000_000.0
GH_EXT_MIN_1H_BARS = 1500
# V.2.40.1 — فقط کریپتو: V.2.40.0 با قانون «فقط حجم» ۱۳ از ۱۵ نماد را سهام/شاخص/کالای توکنیزه انتخاب کرد (NVDA، MSTR،
# QQQ، نفت، نقره…) — بازار پایه شب/آخرهفته بسته، گپ از حد ضرر. حالا نماد اضافه باید در این فهرست ثابت کریپتو باشد.
GH_EXT_CRYPTO_ALLOW = frozenset({
    "HYPE", "HOT", "WLD", "APT", "INJ", "FIL", "ETC", "BCH", "AAVE", "UNI", "SEI", "TIA", "RENDER", "RNDR", "ONDO", "ENA",
    "TAO", "HBAR", "ICP", "KAS", "JUP", "PYTH", "STX", "IMX", "GRT", "ALGO", "VET", "FET", "CRV", "LDO", "MKR", "RUNE",
    "EIGEN", "ZRO", "STRK", "XMR", "ZEC", "DASH", "EOS", "NEO", "IOTA", "THETA", "SAND", "MANA", "AXS", "GALA", "APE",
    "CHZ", "ENS", "DYDX", "GMX", "PENDLE", "JTO", "ETHFI", "ZK", "BLUR", "VIRTUAL", "KAITO", "BERA", "QNT", "EGLD",
    "FLOW", "KSM", "COMP", "SNX", "1INCH", "CAKE", "MINA", "ROSE", "ZIL", "ONE", "CFX", "MOVE", "ME", "TON",
    "SUI", "NEAR", "XLM", "LTC", "BNB"})
GH_MAX_NOTIONAL_ABS_USDT = 35.0   # V.2.40.0 — منتقد: سقف notional هر ورود GH (min_qty بزرگ یک آلت ⇒ بیش از حد)


def _gh_ext_symbols() -> list:
    """نمادهای اضافهٔ آخرین بک‌تست (منهای واچ‌لیست)."""
    try:
        from watchlist import WATCHLIST as _WLx
    except Exception:
        _WLx = []
    xs = ((_BACKTEST_STATE.get("github_research") or {}).get("ext_symbols") or [])
    return [str(x) for x in xs if x not in _WLx and str(x) in GH_EXT_CRYPTO_ALLOW][:GH_EXT_MAX]   # V.2.40.1


def _gh_ext_allowed(name: str, sym: str) -> bool:
    """روی نماد اضافه: فقط اگر استراتژی روی نمادهای اضافه هم لبه داشته و کاغذی اضافه‌اش منفی نشده."""
    if sym not in set(_gh_ext_symbols()):
        return True
    if not GH_EXT_LIVE:
        return False
    r = (((_BACKTEST_STATE.get("github_research") or {}).get("strategies") or {}).get(name) or {})
    try:
        return bool((r.get("ext") or {}).get("ext_ok")) and not _bg_reg.ext_vetoed(name)
    except Exception:
        return False


async def _gh_closed_rows(sym: str, tf: str, limit: int) -> list:
    """V.2.24.3 — کندل‌های «بسته‌شده» (کندل در حال تشکیل با timestamp حذف می‌شود؛ فیلتر close_time توبیت کافی نیست)."""
    import backtest_github as _bg
    df = await toobit_market.get_klines(sym, tf, limit=limit)
    rows = [(float(a), float(b), float(c), float(d), float(e), float(v)) for a, b, c, d, e, v in
            zip(df["timestamp"].tolist(), df["open"].tolist(), df["high"].tolist(), df["low"].tolist(),
                df["close"].tolist(), df["volume"].tolist())]
    now_ms = time.time() * 1000
    while rows and rows[-1][0] + _bg.TF_MS[tf] > now_ms + 5000:
        rows.pop()
    return rows


async def _gh_forward_cycle() -> dict:
    import backtest_github as _bg
    now = time.time()
    if not _bg.FWD.get("start"):
        _bg.FWD["start"] = now
    _bg.FWD["last_run"] = now
    _bg.FWD.setdefault("pp_start", {}).setdefault("rf4h_c2", now)   # V.2.39.2 — شروع رسمی آزمون RF-4h-C2 (یک بار)
    try:
        from watchlist import WATCHLIST as _WLg
    except Exception:
        _WLg = list(TSMOM_SYMBOLS)
    added = 0
    _ext_set = set(_gh_ext_symbols())   # V.2.40.0
    _reg = await _gh_btc_regime(0)
    for sym in _gh_symbols():
        _app = [n for n in _bg.STRATEGIES if _bg.applies(n, sym)]
        for tf, lim in sorted({(_bg.STRATEGIES[n]["tf"], {"4h": 300, "1h": 500}.get(_bg.STRATEGIES[n]["tf"], 500)) for n in _app}):
            names = [n for n in _app if _bg.STRATEGIES[n]["tf"] == tf]
            try:
                rows = await _gh_closed_rows(sym, tf, lim)
            except Exception as e:
                _bg.FWD["errors"] = (_bg.FWD.get("errors") or [])[-9:] + [f"{sym} {tf}: {type(e).__name__}"]
                continue
            for n in names:
                if _reg is None and (_bg.STRATEGIES[n].get("btc_filter") or _bg.STRATEGIES[n].get("bear")):
                    continue   # V.2.39.3 — رژیم BTC نامعلوم ⇒ این دور ثبت نشود (وگرنه سیگنال‌ها گم و معاملهٔ شبح ثبت می‌شد)
                try:
                    added += _bg.forward_add(n, sym, rows, btc=_reg, ext=sym in _ext_set)
                except Exception as e:
                    _bg.FWD["errors"] = (_bg.FWD.get("errors") or [])[-9:] + [f"{n} {sym}: {str(e)[:60]}"]
            await asyncio.sleep(0.2)
    _kv_save_async("gh_paper", {k: _bg.FWD.get(k) for k in ("start", "trades", "keys", "last_run",
                                                               "pp_start", "pp_trades", "pp_keys",
                                                               "ext_start", "ext_trades", "ext_keys")})
    return {"added": added}


def _gh_fam_get(name: str) -> dict:
    """V.2.36.1 — وضعیت زنده/کاغذی و آمار زنده برای کل خانواده (کلید = base). قبلاً با عوض شدن نسخهٔ انتخابی
    (gh_bbandrsi ⇒ gh_bbandrsi_tr) سابقهٔ زنده صفر می‌شد. مهاجرت یک‌باره از ورودی‌های قدیمی هر نسخه:
    کاغذی فقط اگر کاغذی‌شدن آن نسخه بعد از آخرین ارتقای خانواده باشد (منتقد)؛ وگرنه auto با کمترین since."""
    b = _bg_reg.base_of(name)
    st = _gh_live_get(b)
    if st.get("fam_v") == 1:
        return st
    vs = [n for n in _bg_reg.family(b) if isinstance(_GH_LIVE.get(n), dict)]
    last_auto = max([float(h.get("ts") or 0) for n in vs for h in (_GH_LIVE[n].get("history") or [])
                     if isinstance(h, dict) and h.get("to") == "auto"] + [0.0])
    paper = [n for n in vs if _GH_LIVE[n].get("mode") == "paper" and float(_GH_LIVE[n].get("since") or 0) > last_auto]
    new = dict(st)
    if paper:
        src = max(paper, key=lambda n: float(_GH_LIVE[n].get("since") or 0))
        new.update(mode="paper", since=_GH_LIVE[src].get("since"), why=f"[{src}] {_GH_LIVE[src].get('why')}")
    else:
        _ms = min(float(_GH_LIVE[n].get("since") or time.time()) for n in vs) if vs else time.time()
        new.update(mode="auto", since=max(_ms, last_auto))   # نه قبل‌تر از آخرین ارتقا (ضررهای پیش از آن حساب نشوند)
    if not _REMOTE_STATE_LOADED.get("scan_slots"):
        st.update({k: new[k] for k in ("mode", "since", "why") if k in new})   # قبل از KV: در حافظه، بدون ذخیره/fam_v
        return st
    new["history"] = (st.get("history") or [])[-9:] + [{"ts": time.time(), "from": st.get("mode"), "to": new["mode"],
                                                          "why": "V.2.36.1 — وضعیت خانوادگی (مهاجرت)"}]
    new["fam_v"] = 1
    st.clear()
    st.update(new)
    _kv_save_async("gh_live", dict(_GH_LIVE))
    return st


def _gh_live_get(name: str) -> dict:
    st = _GH_LIVE.get(name)
    if not isinstance(st, dict):
        st = _GH_LIVE[name] = {"mode": "auto", "since": time.time(), "history": [], "why": "V.2.22.1 — شروع"}
        if _REMOTE_STATE_LOADED.get("scan_slots"):   # V.2.24.2 — «since» با دیپلوی صفر نشود (قبلاً فقط با تغییر حالت ذخیره می‌شد)
            _kv_save_async("gh_live", dict(_GH_LIVE))
    return st


def _gh_bt_passes(name: str) -> bool:
    return bool((((_BACKTEST_STATE.get("github_research") or {}).get("strategies") or {}).get(name) or {}).get("passes"))


def _gh_veto_refresh(force: bool = False) -> None:
    """V.2.38.2 — وتوی کاغذی رو به جلو برای هر نسخهٔ قبول‌شده (حالت در _GH_LIVE[خانواده]["fwd_veto"]، ذخیره در KV).
    مجموعهٔ _bg_reg.FWD_VETO هر بار از _GH_LIVE ساخته می‌شود ⇒ choose_family در همهٔ مسیرها یکسان است."""
    now = time.time()
    # قبل از بارگذاری KV (gh_live/gh_paper) تصمیم نگیر و ذخیره نکن (وگرنه حالت ناقص روی KV می‌نشیند)
    if _REMOTE_STATE_LOADED.get("scan_slots") and (
            force or now - float(_GH_LIVE_STATE.get("veto_checked_at") or 0) >= GH_VETO_CHECK_SEC):
        _GH_LIVE_STATE["veto_checked_at"] = now
        changed = False
        for n in GH_LIVE_STRATEGIES:
            try:
                if not _gh_bt_passes(n):
                    continue
                fam = _gh_fam_get(n)
                vmap = fam.get("fwd_veto") if isinstance(fam.get("fwd_veto"), dict) else {}
                prev = (vmap.get(n) or {}).get("ts")
                veto, f = _bg_reg.fwd_veto_decide(n, prev)
                if veto and not prev:
                    vmap[n] = {"ts": now, "n": f.get("n"), "avg": f.get("net_avg_pct")}
                    changed = True
                elif not veto and prev:
                    vmap.pop(n, None)
                    changed = True
                fam["fwd_veto"] = vmap
            except Exception:
                continue
        if changed:
            try:
                _kv_save_async("gh_live", dict(_GH_LIVE))
            except Exception:
                pass
    _bg_reg.FWD_VETO.clear()
    _bg_reg.FWD_VETO.update(n for st in _GH_LIVE.values() if isinstance(st, dict)
                            for n in (st.get("fwd_veto") or {}) if isinstance(st.get("fwd_veto"), dict))


def _gh_live_mode(name: str) -> tuple[bool, str]:
    """زنده؟ (بک‌تست قبول + تنزل‌نشده) یا (تنزل‌شده و کاغذی رو به جلو n ≥ ۱۵ و میانگین > ۰)."""
    if not GH_LIVE_ENABLED or name not in GH_LIVE_STRATEGIES:
        return False, "غیرفعال"
    if name in GH_PAPER_ONLY:
        return False, "فقط کاغذی (حاشیهٔ قبولی خیلی کم)"
    if not _gh_bt_passes(name):
        return False, "بک‌تست ۹۰ روزه قبول نیست"
    _gr = _BACKTEST_STATE.get("github_research") or {}   # V.2.42.0 — کنترل تک‌پوزیشنی + ۳۶۵ روزه (فقط ورود جدید)
    _gw = _bg_reg.gate_block((_gr.get("strategies") or {}).get(name), _gr.get("gate_v"))
    if _gw:
        return False, _gw
    _gh_veto_refresh()   # V.2.38.2
    if name in _bg_reg.FWD_VETO:
        _vf = _bg_reg.fwd_stats(name)
        return False, f"وتوی کاغذی رو به جلو (n={_vf.get('n')}، میانگین {_vf.get('net_avg_pct')}) ⇒ کاغذی"
    try:
        if _bg_reg.mc_high_blocked(name, (((_BACKTEST_STATE.get("github_research") or {}).get("strategies") or {})
                                          .get(name))):
            return False, "مونت‌کارلو high (ریسک بالا) ⇒ کاغذی تا کاغذی رو به جلو n ≥ ۲۰ با میانگین ≥ +۰٫۱۵٪"
    except Exception:
        pass
    if name in GH_PAPER_FIRST:
        try:
            import backtest_github as _bgp
            import backtest_range as _brp
            _fw = [x for x in _bgp.FWD["trades"] if x.get("strategy") == name]
            _fs = _brp._stats(_fw, dict(_brp.DEFAULT_PARAMS)) if _fw else {}
        except Exception:
            _fs = {}
        if (_fs.get("n") or 0) < GH_PAPER_FIRST_MIN_N or (_fs.get("net_avg_pct") or -1) <= 0:
            return False, (f"تازه ⇒ اول کاغذی (n={_fs.get('n') or 0}/{GH_PAPER_FIRST_MIN_N}، "
                           f"میانگین {_fs.get('net_avg_pct')})")
    try:   # V.2.34.1 — حداقل لبه همین الان هم (بدون انتظار برای بک‌تست بعدی)
        _all = ((((_BACKTEST_STATE.get("github_research") or {}).get("strategies") or {}).get(name) or {}).get("all") or {})
        if _all.get("net_avg_pct") is not None and (float(_all["net_avg_pct"]) < _bg_reg.MIN_EDGE_AVG_PCT or
                                                     (_all.get("profit_factor") is not None and float(_all["profit_factor"]) < _bg_reg.MIN_EDGE_PF)):
            return False, f"لبهٔ خیلی کم (avg {_all.get('net_avg_pct')}٪، pf {_all.get('profit_factor')}) ⇒ کاغذی"
    except Exception:
        pass
    try:   # V.2.26.0 — از هر خانواده فقط بهترین نسخهٔ قبول‌شده (سود کل ÷ بیشترین افت)
        import backtest_github as _bgf
        _b = _bgf.base_of(name)
        if _b in _bgf.LIVE_BASES:
            _ch = _bgf.choose_family(_b, _BACKTEST_STATE.get("github_research"))
            if _ch and _ch != name:
                return False, f"نسخهٔ بهتر این خانواده زنده است: {_ch}"
    except Exception:
        pass
    st = _gh_fam_get(name)   # V.2.36.1 — خانوادگی
    if st.get("mode") == "paper":
        try:
            import backtest_github as _bg
            import backtest_range as _br
            fw = [x for x in _bg.FWD["trades"] if x["strategy"] == name and x["t"] / 1000 >= float(st.get("since") or 0)]
            fs = _br._stats(fw, dict(_br.DEFAULT_PARAMS))
            if (fs.get("n") or 0) >= 15 and (fs.get("net_avg_pct") or -1) > 0:
                _gh_set_mode(name, "auto", f"کاغذی بعد از تنزل n={fs.get('n')} میانگین {fs.get('net_avg_pct'):+.3f}٪ ⇒ زنده")
                return True, "ok"
        except Exception:
            pass
        return False, f"تنزل‌شده به کاغذی: {st.get('why')}"
    return True, "ok"


def _gh_set_mode(name: str, mode: str, why: str, since: float | None = None) -> None:
    st = _gh_fam_get(name)   # V.2.36.1 — حالت برای کل خانواده
    st["history"] = (st.get("history") or [])[-9:] + [{"ts": time.time(), "from": st.get("mode"), "to": mode, "why": why}]
    st.update(mode=mode, since=time.time() if since is None else float(since), why=why)
    _kv_save_async("gh_live", dict(_GH_LIVE))


# V.2.39.3 — بستن‌های ناشی از خطای سیستم/کاربر شاهدِ عملکرد استراتژی نیستند ⇒ در آمار تنزل حساب نمی‌شوند
# (gh_bbandrsi_tr با دو بستن undersized_margin باگ V.2.38.2 تنزل خورده بود). sl_breach_no_exchange_sl،
# emergency_loss_cap و bot_close_unspecified ضرر واقعی‌اند و حساب می‌شوند.
GH_LIVE_EXCLUDE_EXITS = frozenset({"gh_invalid_short", "gh_invalid_long", "undersized_margin", "force_close_no_sl",
                                   "no_exchange_sl", "fill_invalidated_trade", "manual_close", "manual_ui"})


def _gh_live_vals(name: str, rows: list, since: float, until: float | None = None,
                  excl=GH_LIVE_EXCLUDE_EXITS, denom: float | None = None) -> tuple[list, dict, int]:
    """(درصدهای خالص معاملات زندهٔ خانواده، شمار هر نسخه، شمار کنارگذاشته)."""
    vals, by_v, n_ex = [], {}, 0
    for h in rows or []:
        _sid = str(h.get("strategy_id") or "")
        if _sid not in GH_LIVE_STRATEGIES or _bg_reg.base_of(_sid) != name or str(h.get("status") or "") == "open":
            continue
        _ct = float(h.get("closed_at") or 0)
        if _ct < float(since or 0) or (until is not None and _ct >= float(until)):
            continue
        if str(h.get("exit_reason") or "") in excl:
            n_ex += 1
            continue
        pv = next((h.get(k) for k in ("exchange_pnl", "realized_pnl", "pnl_usdt", "pnl") if h.get(k) is not None), None)
        try:   # V.2.39.3 — پیش‌فرض مخرج = کف ورود GH (۲۱$، نه ۲۵$)؛ محافظه‌کارانه‌تر
            vals.append(float(pv) / float(h.get("notional_actual") or (denom or GH_SIZE_FLOOR_USDT)) * 100.0)
            by_v[_sid] = by_v.get(_sid, 0) + 1
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return vals, by_v, n_ex


def _gh_demote_rule(vals: list) -> bool:
    avg = sum(vals) / len(vals) if vals else 0.0
    return bool((len(vals) >= GH_DEMOTE_FAST_N and avg <= GH_DEMOTE_FAST_AVG) or (len(vals) >= GH_DEMOTE_N and avg < GH_DEMOTE_AVG))


GH_REEVAL_DENOM = 25.0   # V.2.39.6 — مخرج پیش‌فرض همان زمان تنزل (پیش از V.2.39.3) تا بازسازی با عدد ثبت‌شده بخواند
GH_REEVAL_BEFORE_TS = 1793688360.0   # 2026-11-03 06:46 UTC — فقط تنزل‌های پیش از قانون تازه (V.2.39.3) بازبینی می‌شوند


def _gh_reeval_demotion(name: str, st: dict, rows: list, ledger_ok: bool) -> bool:
    """V.2.39.3/4/5 — یک بار برای هر تنزلِ «نتیجهٔ زنده» پیش از V.2.39.3: اگر فقط به‌خاطر بستن‌های سیستمی بوده، بازگرداندن.
    V.2.39.5 — تشخیص در st["reeval_diag"] (در گزارش دیده می‌شود)؛ اگر دفتر کمتر از n ردیف دارد، از میانگین ثبت‌شدهٔ تنزل
    منهای سهم بستن‌های سیستمیِ پیدا‌شده حساب می‌شود (قبلاً بی‌صدا هر ۵ دقیقه رد می‌شد)."""
    import re as _re
    hist = st.get("history") or []
    diag: dict = {"t": round(time.time())}

    def _done(reason: str, ok: bool = False) -> bool:
        diag["result"] = reason
        if (st.get("reeval_diag") or {}).get("result") != reason:
            st["reeval_diag"] = diag
            _kv_save_async("gh_live", dict(_GH_LIVE))
        else:
            st["reeval_diag"] = diag
        return ok
    if st.get("mode") != "paper" or not hist:
        return False
    if not ledger_ok:
        return _done("ledger_unavailable")
    # آخرین تنزلِ «نتیجهٔ زنده» بدون ارتقای بعدی (ورودی مهاجرت/غیرحالتی بعدش نادیده)
    h, hi = None, None
    for _i in range(len(hist) - 1, -1, -1):
        if hist[_i].get("to") == "auto":
            break
        if hist[_i].get("to") == "paper" and str(hist[_i].get("why") or "").lstrip("[").split("] ", 1)[-1].startswith("زنده n="):
            h, hi = hist[_i], _i
            break
    if h is None:
        return _done("not_live_pnl_demotion")
    why = str(h.get("why") or "").split("] ", 1)[-1]
    # کران پایین: تنزل قبلی (بین تنزل و ارتقای بعدی معاملهٔ زنده‌ای نیست ⇒ ردیف‌های قدیمی‌تر از دورهٔ قبل حساب نشوند)
    lo = max([float(x.get("ts") or 0) for x in hist[:hi] if x.get("to") == "paper"] + [0.0])
    _done_already = h.get("ts") is not None and st.get("reeval3_ts") == h.get("ts")   # V.2.39.6 — علامت تازه (V.2.39.4 با reeval2_ts بی‌صدا رد کرده بود)
    if float(h.get("ts") or 0) >= GH_REEVAL_BEFORE_TS:
        return _done("after_new_rules")
    m = _re.search(r"n=(\d+)", why)
    ma = _re.search(r"میانگین ([+\-]?\d+(?:\.\d+)?)", why)
    if not m:
        return _done("why_unparsed")
    n_dem = int(m.group(1))
    old_excl = frozenset({"gh_invalid_short", "gh_invalid_long"})
    fam = []
    for x in rows or []:
        _sid = str(x.get("strategy_id") or "")
        if _sid not in GH_LIVE_STRATEGIES or _bg_reg.base_of(_sid) != name or str(x.get("status") or "") == "open":
            continue
        _c = float(x.get("closed_at") or 0)
        if _c <= max(0.0, lo) or _c >= float(h.get("ts") or 0) or str(x.get("exit_reason") or "") in old_excl:
            continue
        fam.append(x)
    fam.sort(key=lambda x: float(x.get("closed_at") or 0))
    diag.update(n_logged=n_dem, rows_found=len(fam))
    if len(fam) >= n_dem:
        sel = fam[-n_dem:] if n_dem else []
        v_new, _, n_ex = _gh_live_vals(name, sel, 0, denom=GH_REEVAL_DENOM)
        v_all, _, _ = _gh_live_vals(name, sel, 0, excl=old_excl, denom=GH_REEVAL_DENOM)
        n_new, avg = len(v_new), (sum(v_new) / len(v_new) if v_new else 0.0)
        diag.update(mode="rebuild", n_excluded=n_ex, n_new=n_new, avg_new=round(avg, 4),
                    avg_old=round(sum(v_all) / len(v_all), 4) if v_all else None,
                    first=round(float(sel[0].get("closed_at") or 0)) if sel else None)
    elif ma and fam:
        sel = fam   # دفتر ناقص: سهم بستن‌های سیستمیِ پیدا‌شده از میانگین ثبت‌شده کم می‌شود
        ex_rows = [x for x in fam if str(x.get("exit_reason") or "") in GH_LIVE_EXCLUDE_EXITS]
        v_ex, _, _ = _gh_live_vals(name, ex_rows, 0, excl=old_excl, denom=GH_REEVAL_DENOM)
        n_ex = len(v_ex)
        n_new = n_dem - n_ex
        avg = (float(ma.group(1)) * n_dem - sum(v_ex)) / n_new if n_new > 0 else 0.0
        diag.update(mode="logged_avg", n_excluded=n_ex, n_new=n_new, avg_new=round(avg, 4))
    else:
        return _done("ledger_short")
    if _done_already:
        return _done("done:" + str(st.get("reeval3_res") or "?"))
    st["reeval3_ts"] = h.get("ts")
    trip = (n_new >= GH_DEMOTE_FAST_N and avg <= GH_DEMOTE_FAST_AVG) or (n_new >= GH_DEMOTE_N and avg < GH_DEMOTE_AVG)
    if n_ex < 1:
        st["reeval3_res"] = "no_system_exits"
        return _done("no_system_exits")
    if trip:
        st["reeval3_res"] = "still_negative"
        return _done("still_negative")
    st["reeval3_res"] = "restored"
    since0 = float(sel[0].get("closed_at") or 0) - 1 if sel else float(h.get("ts") or 0)
    _gh_set_mode(name, "auto", f"V.2.39.6 بازبینی: {n_ex} بستن سیستمی کنار ⇒ n={n_new} میانگین {avg:+.3f}٪ ⇒ زنده",
                 since=since0)
    return _done("restored", True)


async def _gh_live_check() -> None:
    """تنزل خودکار با نتیجهٔ زنده (هر ۵ دقیقه)."""
    if time.time() - float(_GH_LIVE_STATE.get("checked_at") or 0) < 300:
        return
    _GH_LIVE_STATE["checked_at"] = time.time()
    _ledger_ok = False
    try:   # V.2.30.1 — دفتر با PnL صرافی (حافظه/Supabase ستون PnL ندارد ⇒ قبلاً live_n همیشه ۰ بود)
        _lg = await real_ledger(limit=300)
        _ledger_ok = bool(_lg.get("exchange_rows_available"))
        rows = [dict(x, status="closed") for x in (_lg.get("items") or [])]
    except Exception:
        rows = []
    if not rows:
        try:
            rows = await _memory_context()
        except Exception:
            rows = []
    for name in sorted({_bg_reg.base_of(n) for n in GH_LIVE_STRATEGIES}):   # V.2.36.1 — هر خانواده یک‌جا
        st = _gh_fam_get(name)
        if st.get("mode") == "paper":
            try:
                _gh_reeval_demotion(name, st, rows, _ledger_ok)   # V.2.39.3
            except Exception as _re_e:
                logger.debug("gh reeval %s: %s", name, _re_e)
            if st.get("mode") == "paper":
                continue
        vals, by_v, _n_ex = _gh_live_vals(name, rows, float(st.get("since") or 0))   # V.2.39.3
        st["live"] = {"n": len(vals), "avg_pct": round(sum(vals) / len(vals), 4) if vals else None,
                      "sum_pct": round(sum(vals), 3) if vals else None, "by_variant": by_v,
                      "excluded": _n_ex}
        avg = sum(vals) / len(vals) if vals else 0.0
        if len(vals) >= GH_DEMOTE_FAST_N and avg <= GH_DEMOTE_FAST_AVG:
            _gh_set_mode(name, "paper", f"زنده n={len(vals)} میانگین {avg:+.3f}٪ ≤ {GH_DEMOTE_FAST_AVG}٪ ⇒ کاغذی")
        elif len(vals) >= GH_DEMOTE_N and avg < GH_DEMOTE_AVG:
            _gh_set_mode(name, "paper", f"زنده n={len(vals)} میانگین {avg:+.3f}٪ < ۰ ⇒ کاغذی")


def _gh_rank_order() -> list:
    """V.2.31.0 — استراتژی‌های زندهٔ همین الان به ترتیب امتیاز بک‌تست."""
    import backtest_github as _bg
    live = [n for n in GH_LIVE_STRATEGIES if _gh_live_mode(n)[0]]
    order = _bg.rank_live(_BACKTEST_STATE.get("github_research"), live, fwd_fn=_bg.fwd_stats)   # V.2.38.2 — + کاغذی و MC
    # V.2.32.1 — رتبهٔ ۱ و ۲ (حجم بیشتر، ۲ پوزیشن، اسلات رزرو) فقط با سابقهٔ کافی در بک‌تست (n ≥ GH_RANK_MIN_N)
    st = ((_BACKTEST_STATE.get("github_research") or {}).get("strategies") or {})
    nn = {n: int(((st.get(n) or {}).get("all") or {}).get("n") or 0) for n in order}
    top = [n for n in order if nn[n] >= GH_RANK_MIN_N][:GH_RESERVE_TOP_N]
    return top + [n for n in order if n not in top]


def _gh_open_count(name: str) -> int:
    """V.2.36.1 — پوزیشن‌های باز کل خانواده (نسخهٔ قبلی هم سقف نسخهٔ تازه را پر می‌کند)."""
    b = _bg_reg.base_of(name)
    return sum(1 for m in _tracked.values() if isinstance(m, dict) and m.get("status") == "open"
               and str(m.get("strategy_id") or "") in GH_LIVE_STRATEGIES and _bg_reg.base_of(str(m.get("strategy_id"))) == b)


def _gh_max_open(name: str) -> int:
    """V.2.31.2 — سودده‌ترین استراتژی (رتبهٔ ۱) تا GH_TOP1_MAX_OPEN پوزیشن هم‌زمان؛ بقیه GH_LIVE_MAX_OPEN."""
    return GH_TOP1_MAX_OPEN if _gh_rank(name) == 0 else GH_LIVE_MAX_OPEN


def _gh_rank(name: str) -> int | None:
    try:
        return _gh_rank_order().index(name)
    except ValueError:
        return None


async def _can_open_gh(symbol: str, direction: str, entry: float, stop_loss: float, target: float,
                       family: str) -> tuple[bool, str]:
    """V.2.22.1 — گیت‌های حساب (مثل rel_strength) + حالت زندهٔ استراتژی گیت‌هاب؛ بدون جدول/آزمون رو به جلو."""
    key = _norm_symbol(symbol)
    if not toobit_private.keys_configured():
        return False, "کلید Toobit تنظیم نشده"
    if daily_loss_breached():
        return False, "سقف ضرر روزانه پر شده"
    ok_m, why_m = _gh_live_mode(family)
    if not ok_m:
        return False, f"{family}: {why_m}"
    meta = _tracked.get(key)
    if meta and meta.get("status") == "open":
        return False, "پوزیشن ریل همین نماد باز است"
    try:   # V.2.30.0 — شورت مجاز طبق مشخصات خود استراتژی (نسخه‌ها از پایه)
        import backtest_github as _bgs
        _sp_s = _bgs.STRATEGIES.get(family) or {}
        _short_ok = bool(GH_STRATEGY_SHORT.get(family) or (_sp_s.get("short") and not _sp_s.get("btc_filter")))
    except Exception:
        _sp_s = {}
        _short_ok = bool(GH_STRATEGY_SHORT.get(family, False))
    if not _short_ok and direction != "long":
        return False, f"{family} فقط لانگ"
    if _sp_s.get("bear") and direction == "long":   # V.2.37.0 — نسخهٔ bear فقط شورت
        return False, f"{family} فقط شورت (بازار نزولی)"
    left = _global_sl_remaining()
    if left > 0:
        return False, f"قفل سراسری پس از چند SL ({left}s باقی)"
    for fn, label in ((_symbol_sl_lock_remaining, "قفل نماد پس از چند SL"), (_post_close_remaining, "کول‌داون پس از بستن")):
        left = fn(key)
        if left > 0:
            return False, f"{label} ({left}s باقی)"
    try:
        e, sl, tp = float(entry), float(stop_loss), float(target)
    except (TypeError, ValueError):
        return False, "قیمت نامعتبر"
    sgn = 1.0 if direction == "long" else -1.0
    sl_pct = sgn * (e - sl) / e * 100.0
    ordered = (sl < e < tp) if direction == "long" else (tp < e < sl)
    _min_sl = 0.05 if family in GH_GOLD_STRATEGIES else 0.5   # V.2.25.0 — طلا: SL پیپی (~۰٫۱۵٪)
    if not ordered or not (_min_sl <= sl_pct <= GH_SL_CAP_PCT + 1e-9):
        return False, f"هندسهٔ {family} نامعتبر (SL {sl_pct:.2f}٪)"
    _cap_each = _gh_max_open(family)   # V.2.31.2 — رتبهٔ ۱ تا ۲ پوزیشن هم‌زمان، بقیه ۱
    if _gh_open_count(family) >= _cap_each:
        return False, f"{family}: سقف {_cap_each} پوزیشن هم‌زمان"
    bal_preview = await _equity_balance()
    max_pos = _effective_max_positions(bal_preview)
    n_open, rows = await _open_positions_count()
    if rows is None:
        n_open, rows = 99, []
    if n_open >= max_pos:
        return False, f"حداکثر {max_pos} پوزیشن باز مجاز است (الان {n_open})"
    try:   # V.2.36.2 — ریسک تعهدشده (SLهای باز + این ورود) در سقف ضرر روزانه
        _est = float((_margin_for_strategy(0.0, family, e, sl, float(bal_preview or 0), float(bal_preview or 0))[2] or {})
                     .get("est_loss") or 0)
    except Exception:
        _est = _estimate_adverse_usdt(_effective_min_notional(float(bal_preview or 0)), e, sl)
    _cr = _committed_risk_block(_est)
    if _cr:
        return False, f"{family}: {_cr}"
    _rk = _gh_rank(family)   # V.2.31.0 — آخرین اسلات خالی فقط برای استراتژی‌های برتر
    # V.2.31.2 — فقط برای برترهایی که هنوز جا دارند (اگر رتبهٔ ۱ به سقفش رسیده و رتبهٔ ۲ جا دارد، برای ۲ نگه می‌داریم؛
    # اگر هیچ برتری جا ندارد، اسلات خالی هدر نمی‌رود)
    _top_free = [n for n in _gh_rank_order()[:GH_RESERVE_TOP_N] if _gh_open_count(n) < _gh_max_open(n)]
    if n_open >= max_pos - 1 and max_pos > 1 and _top_free and (_rk is None or _rk >= GH_RESERVE_TOP_N):
        return False, f"{family}: رتبهٔ {(_rk or 0) + 1} — آخرین اسلات برای {GH_RESERVE_TOP_N} استراتژی برتر نگه داشته می‌شود"
    for r in rows:
        if isinstance(r, dict) and _norm_symbol(str(r.get("symbol") or "")) == key and toobit_private.parse_position_qty(r) > 0:
            return False, "روی صرافی برای این نماد پوزیشن باز است"
    same_dir = sum(1 for m in _tracked.values() if isinstance(m, dict) and m.get("status") == "open" and m.get("direction") == direction)
    if same_dir >= int(MAX_SAME_DIRECTION_POSITIONS):
        return False, f"سقف پوزیشن هم‌جهت ({same_dir}/{MAX_SAME_DIRECTION_POSITIONS})"
    _pending_strategy[key] = family
    return True, "ok"


async def _gh_live_scan(force: bool = False) -> dict:
    """هر ۱۵ دقیقه (۳۰ ثانیه تا ۱۰ دقیقه بعد از بسته شدن کندل): استراتژی‌های ۱۵m هر بار، ۱h فقط سر ساعت.
    همان کد بک‌تست (signals) روی آخرین کندل بسته‌شده ⇒ ورود زنده (۱۵m هر بار، ۱h سر ساعت، ۴h سر هر ۴ ساعت)."""
    import backtest_github as _bg
    now = time.time()
    slot = int(now // 900)
    if not force and (_GH_LIVE_STATE.get("last_slot") == slot
                      or not _scan_gate("gh_live15", slot, now - slot * 900, 30, 600)):
        return {}
    _GH_LIVE_STATE["last_slot"] = slot
    _scan_mark("gh_live15", slot)
    due = {"15m": True, "1h": slot % 4 == 0 or force, "4h": slot % 16 == 0 or force}   # V.2.24.0 — ۴h سر هر ۴ ساعت UTC
    res: dict = {"ts": now, "slot_utc": time.strftime("%H:%M", time.gmtime(slot * 900)), "modes": {}, "signals": [],
                 "opened": []}
    _GH_LIVE_STATE["last_result"] = res
    _hist = _GH_LIVE_STATE.setdefault("history", [])   # V.2.24.1 — تاریخچهٔ اسکن‌ها (برای اثبات اینکه سیگنالی جا نماند)
    _hist.append(res)
    del _hist[:-48]
    res["fetch_ok"], res["fetch_err"] = 0, []
    live = []
    for n in GH_LIVE_STRATEGIES:
        ok_m, why_m = _gh_live_mode(n)
        res["modes"][n] = "live" if ok_m else why_m
        if ok_m and due.get(_bg.STRATEGIES[n]["tf"]):
            live.append(n)
    if not live:
        return res
    closed_slot = await _symbols_closed_since(slot * 900 - 3600)
    cands: list = []
    for sym in _gh_symbols():
        live_s = [n for n in live if _bg.applies(n, sym) and _gh_ext_allowed(n, sym)]   # V.2.25.0 طلا؛ V.2.40.0 نماد اضافه
        tfs = sorted({_bg.STRATEGIES[n]["tf"] for n in live_s})
        frames = {}
        for tf in tfs:
            try:
                rows = await _gh_closed_rows(sym, tf, 300)
            except Exception as _fe:
                if len(res["fetch_err"]) < 5:
                    res["fetch_err"].append(f"{sym} {tf}: {type(_fe).__name__}")
                continue
            # V.2.24.3 — کندل در حال تشکیل حذف شده؛ آخرین کندل بسته باید تازه باشد (همان کندلی که همین الان بسته شد)
            if len(rows) < 120 or rows[-1][0] / 1000 + 2 * _bg.TF_MS[tf] / 1000 < now - 5:
                if len(res["fetch_err"]) < 5:
                    res["fetch_err"].append(f"{sym} {tf}: stale/short n={len(rows)}")
                continue
            if True:
                frames[tf] = rows
                res["fetch_ok"] += 1
                res.setdefault("last_bar_utc", {})[tf] = time.strftime("%H:%M", time.gmtime(rows[-1][0] / 1000))
        for n in live_s:
            spec = _bg.STRATEGIES[n]
            rows = frames.get(spec["tf"])
            if not rows:
                continue
            sg = _bg.signals(n, rows)[-1]
            d = "long" if sg[0] else ("short" if (sg[1] and spec["short"]) else None)
            if spec.get("bear"):   # V.2.37.0 — همان شرط بک‌تست: فقط شورت و فقط وقتی BTC زیر EMA50 (۴h) است
                d = "short" if (sg[1] and _bg.btc_down_at(await _gh_btc_regime(),
                                                          rows[-1][0] + _bg.TF_MS[spec["tf"]])) else None
            if d and spec.get("btc_filter"):   # V.2.26.0 — همان شرط بک‌تست: BTC بالای EMA50 (۴h)
                if d == "short":   # V.2.31.1 — نسخهٔ _btc در بک‌تست هرگز شورت نمی‌گیرد (es=False)؛ زنده هم نه
                    d = None
                elif not _bg.btc_up_at(await _gh_btc_regime(), rows[-1][0] + _bg.TF_MS[spec["tf"]]):
                    d = None
            if not d:
                continue
            res["signals"].append({"strategy": n, "symbol": sym, "direction": d})
            if _norm_symbol(sym) in closed_slot:
                continue
            cands.append((n, sym, d, rows))
    # V.2.31.0 — باز کردن به ترتیب سودده‌ترین استراتژی (اسلات‌ها اول به بهترین‌ها می‌رسند)
    _cs = {c[0] for c in cands}   # V.2.39.3 — همان رتبه‌ای که اسلات رزرو و حجم از آن استفاده می‌کنند (کاغذی + MC)
    order = [n for n in _gh_rank_order() if n in _cs]
    cands.sort(key=lambda c: order.index(c[0]) if c[0] in order else 99)
    res["priority"] = order
    for n, sym, d, rows in cands:
        if True:
            spec = _bg.STRATEGIES[n]
            lp = await toobit_market.get_live_price(sym)
            px = float((lp or {}).get("price") or rows[-1][4])
            s_ = 1 if d == "long" else -1
            sl_pct = min(_bg.SL_CAP_PCT, float(spec["sl"]))
            roi0 = float(spec["roi"].get(0, 100.0))
            tp_pct = roi0 if roi0 < GH_LIVE_TP_FAR_PCT else GH_LIVE_TP_FAR_PCT
            if _bg.uses_levels(spec):   # V.2.25.0/V.2.32.0/V.2.38.0 — SL/TP هر معامله با همان تابع بک‌تست (شامل sl_atr/tp_atr)
                sl_pct, _tpx = _bg.levels(n, rows, len(rows) - 1, px)
                if sl_pct is None:   # V.2.35.0 — قیمت لحظه‌ای از حد ضرر setup گذشته ⇒ ورود نیست (قبلاً SL ۱۰٪/TP ۳۰٪)
                    res["opened"].append({"strategy": n, "symbol": sym, "direction": d, "ok": False,
                                          "reason": "setup در قیمت فعلی نامعتبر (رد شده از حد ضرر)"})
                    continue
                if _tpx is not None:
                    tp_pct = _tpx
            sl, tp = px * (1 - s_ * sl_pct / 100), px * (1 + s_ * tp_pct / 100)
            out = await open_real_trade(sym, d, px, sl, tp, 95, diagnostics={"strategy_id": n, "gh_signal_bar": rows[-1][0]})
            res["opened"].append({"strategy": n, "symbol": sym, "direction": d, "ok": bool((out or {}).get("ok")),
                                  "reason": str((out or {}).get("reason") or (out or {}).get("error") or "")[:160]})
    return res


async def _gh_live_manage(key: str, meta: dict, direction: str, price: float) -> dict | None:
    """V.2.24.0 — همان بک‌تست: (۱) ROI زمانی (جدول minimal_roi بر حسب دقیقه) ⇒ بستن با سود؛
    (۲) تریلینگ خود استراتژی (مثلاً hlhb: از +۱٫۸۶٪، SL = بیشترین قیمت − ۱٫۱۷٪) ⇒ روی صرافی (فقط سفت‌تر)."""
    import backtest_github as _bg
    spec = _bg.STRATEGIES.get(str(meta.get("strategy_id") or "")) or {}
    if not spec:
        return None
    long_ = str(direction).lower() != "short"
    sg = 1.0 if long_ else -1.0
    try:
        e = float(meta.get("fill_entry") or meta.get("entry") or 0)
    except (TypeError, ValueError):
        return None
    if e <= 0 or price <= 0:
        return None
    move = sg * (price / e - 1) * 100
    mins = (time.time() - float(meta.get("opened_at") or time.time())) / 60
    roi = _bg._roi_at(spec["roi"], mins)
    if roi < GH_LIVE_TP_FAR_PCT and move >= roi and move > 0:
        res = await _close_tracked(key, "gh_roi", price)
        return {"action": "gh_roi", "closed": bool((res or {}).get("ok")), "roi_pct": roi, "pnl_pct": round(move, 4)}
    tr = spec.get("trail")
    if not tr:   # V.2.31.3 — پوزیشن باز خانواده‌ای که نسخهٔ انتخابی‌اش قفل سود دارد هم قفل سود می‌گیرد
        try:
            _b = _bg.base_of(str(meta.get("strategy_id") or ""))
            _ch = _bg.choose_family(_b, _BACKTEST_STATE.get("github_research"), gate=False) if _b in _bg.LIVE_BASES else None
            tr = (_bg.STRATEGIES.get(_ch) or {}).get("trail") if _ch else None
        except Exception:
            tr = None
    if not tr:
        return None
    peak = float(meta.get("gh_peak") or e)
    peak = max(peak, price) if long_ else min(peak, price)
    meta["gh_peak"] = peak
    gain = sg * (peak / e - 1) * 100
    if gain < float(tr[1]):
        return None
    tgt = peak * (1 - sg * float(tr[0]) / 100)
    try:
        cur = float(meta.get("stop_loss") or 0)
    except (TypeError, ValueError):
        cur = 0.0
    tighter = (tgt > cur * 1.0005) if long_ else (cur <= 0 or tgt < cur * 0.9995)
    if not tighter:
        return None
    if (long_ and price <= tgt) or ((not long_) and price >= tgt):
        res = await _close_tracked(key, "gh_trail_close", price)
        return {"action": "gh_trail_close", "closed": bool((res or {}).get("ok")), "sl_target": tgt}
    if time.time() - float(meta.get("gh_trail_ts") or 0) < 60:
        return None
    meta["gh_trail_ts"] = time.time()
    r = await toobit_private.attach_tpsl_and_verify(key, direction, str(meta.get("target") or "") or None, str(tgt),
                                                    str(meta.get("quantity") or "") or None)
    if bool((r or {}).get("verified")):
        _log_sl_change(meta, cur, float(r.get("exchange_sl") or tgt), "gh_trail", price=price, verified=True)
        meta["stop_loss"] = float(r.get("exchange_sl") or tgt)
        meta["sl_on_exchange"] = True
        try:
            _save_tracked()
        except Exception:
            pass
        return {"action": "gh_trail_move", "sl": meta["stop_loss"]}
    if (r or {}).get("error") == "refuse_loosen_sl" and r.get("exchange_sl") is not None:
        # V.2.39.3 — SL صرافی از قبل سفت‌تر است ⇒ همگام‌سازی (قبلاً هر ۶۰ ثانیه بی‌پایان دوباره تلاش می‌کرد)
        try:
            _ex = float(r["exchange_sl"])
            if (long_ and _ex > cur) or ((not long_) and (cur <= 0 or _ex < cur)):
                _log_sl_change(meta, cur, _ex, "gh_trail_sync", price=price, verified=True)
                meta["stop_loss"] = _ex
                _save_tracked()
                return {"action": "gh_trail_sync", "sl": _ex}
        except Exception:
            pass
    return None


async def _gh_exit_check(meta: dict, key: str) -> str | None:
    """هر ساعت: سیگنال خروج همان استراتژی روی آخرین کندل بستهٔ ۱h بعد از ورود؛ یا ۷ روز."""
    import backtest_github as _bg
    name = str(meta.get("strategy_id") or "")
    now = time.time()
    _spec = _bg.STRATEGIES.get(name) or {}
    if now - float(meta.get("opened_at") or now) >= float(_spec.get("max_hold_h", _bg.MAX_HOLD_H)) * 3600:
        return "gh_time_stop"
    if _spec.get("bear") and str(meta.get("direction") or "").lower() == "long":
        return "gh_invalid_long"   # V.2.37.0 — لانگی که به‌اشتباه با نسخهٔ bear باز شده
    if _spec.get("btc_filter") and str(meta.get("direction") or "").lower() == "short":
        return "gh_invalid_short"   # V.2.31.1 — شورتی که به‌اشتباه با نسخهٔ _btc باز شده (بک‌تست ندارد) ⇒ بستن
    _per = 900 if _spec.get("tf") == "15m" else 3600   # V.2.25.0 — استراتژی ۱۵m: چک خروج هر ۱۵ دقیقه
    slot = int(now // _per)
    if meta.get("gh_checked_slot") == slot or now - slot * _per < 60:
        return None
    try:
        _tf = _spec.get("tf", "1h")
        _tfs = _bg.TF_MS[_tf] / 1000
        rows = await _gh_closed_rows(key, _tf, 300)   # V.2.24.3 — فقط کندل بسته (مثل بک‌تست)
        # V.2.35.0 — دادهٔ کهنه/ناقص ⇒ این اسلات علامت نمی‌خورد و دور بعد دوباره چک می‌شود (قبلاً اسلات قبل از دریافت
        # علامت می‌خورد و سیگنال خروج آن کندل برای همیشه گم می‌شد)
        if len(rows) < 60 or rows[-1][0] / 1000 + 2 * _tfs < now - 5:
            return None
        meta["gh_checked_slot"] = slot
        _opened = float(meta.get("opened_at") or 0)
        if rows[-1][0] / 1000 + _tfs <= _opened:
            return None   # کندلی که ورود داخلش بود هنوز بسته نشده (بک‌تست هم از همان کندل ورود خروج را چک می‌کند)
        # V.2.35.0 — همهٔ کندل‌های بستهٔ تازه از آخرین بررسی (نه فقط آخری) — مثل simulate که اولین سیگنال خروج را می‌گیرد
        _fi = 2 if str(meta.get("direction") or "").lower() == "long" else 3   # V.2.41.0 — "LONG" هم لانگ است
        _last = float(meta.get("gh_exit_last_ts") or 0)
        _sig = _bg.signals(name, rows)
        _hit = any(_sig[j][_fi] for j in range(len(rows))
                   if rows[j][0] > _last and rows[j][0] / 1000 + _tfs > _opened)
        meta["gh_exit_last_ts"] = rows[-1][0]
        if _hit:
            return "gh_exit_signal"
        # V.2.26.0 — خروج روند BTC: برای نسخهٔ _btc، و برای پوزیشن‌های باز همان خانواده اگر نسخهٔ انتخابی _btc است
        _b = _bg.base_of(name)
        _ch = _bg.choose_family(_b, _BACKTEST_STATE.get("github_research"), gate=False) if _b in _bg.LIVE_BASES else None
        _dir = str(meta.get("direction") or "").lower()
        if _dir == "long" and (_spec.get("btc_filter") or (_ch and _bg.STRATEGIES.get(_ch, {}).get("btc_filter"))):
            _reg = await _gh_btc_regime()   # V.2.37.0 — فقط لانگ (قبلاً شورت خانوادهٔ _btc هم بسته می‌شد)
            if _reg is not None and not _bg.btc_up_at(_reg, now * 1000):
                return "gh_btc_exit"
        if _dir == "short" and _spec.get("bear"):   # V.2.37.0 — BTC بالای EMA50 برگشت ⇒ بستن شورت نزولی
            _reg = await _gh_btc_regime()
            if _reg is not None and _bg.btc_up_at(_reg, now * 1000):
                return "gh_btc_exit"
    except Exception:
        return None
    return None


def _gh_paper_since_live() -> dict:
    """V.2.24.1 — معاملات کاغذی (همان کد) با ورود بعد از زنده شدن هر استراتژی: باید با ورودهای زنده هم‌خوان باشد."""
    try:
        import backtest_github as _bg
        out = {}
        for n in GH_LIVE_STRATEGIES:
            since = float(_gh_fam_get(n).get("since") or 0)
            xs = [x for x in _bg.FWD.get("trades") or [] if x.get("strategy") == n and x["t"] / 1000 >= since]
            out[n] = [{"symbol": x["symbol"], "dir": x["dir"], "entry_utc": time.strftime("%m-%d %H:%M", time.gmtime(x["t"] / 1000)),
                       "exit": x["exit"], "gross_pct": x["gross_pct"]} for x in xs[-6:]]
        return out
    except Exception as e:
        return {"error": str(e)[:120]}


def _gh_report() -> dict:
    try:
        import backtest_github as _bg
        rep = dict(_bg.report(_BACKTEST_STATE.get("github_research")), enabled=GH_PAPER_ENABLED)
        rep["live"] = {"enabled": GH_LIVE_ENABLED, "strategies": list(GH_LIVE_STRATEGIES),
                       "rules": {"entry": "بک‌تست ۹۰ روزه قبول ⇒ زنده با حداقل حجم (بدون انتظار کاغذی، به خواست کاربر)",
                                 "max_open_each": GH_LIVE_MAX_OPEN, "sl_cap_pct": GH_SL_CAP_PCT,
                                 "demote": f"زنده ≥ {GH_DEMOTE_FAST_N} با میانگین ≤ {GH_DEMOTE_FAST_AVG}٪ یا ≥ {GH_DEMOTE_N} با میانگین < ۰ ⇒ کاغذی",
                                 "re_promote": "کاغذی بعد از تنزل n ≥ ۱۵ و میانگین > ۰"},
                       "state": {n: {**{k: v for k, v in _gh_fam_get(n).items() if k != "history"},
                                     "family": _bg_reg.base_of(n),
                                     "live_now": _gh_live_mode(n)[0], "history": (_gh_fam_get(n).get("history") or [])[-3:],
                                     "fwd": _bg.fwd_stats(n).get("n"), "fwd_avg": _bg.fwd_stats(n).get("net_avg_pct"),
                                     "fwd_veto": n in _bg.FWD_VETO,
                                     "rank_score": _bg.score_of((((_BACKTEST_STATE.get("github_research") or {})
                                                                  .get("strategies") or {}).get(n)), _bg.fwd_stats(n), True)}
                                 for n in GH_LIVE_STRATEGIES},
                       "last_scan": _GH_LIVE_STATE.get("last_result"),
                       # V.2.24.1 — اسکن‌های اخیر (خلاصه) + معاملات کاغذی رو به جلو که بعد از زنده شدن رخ داده‌اند
                       "scans_recent": [{"slot_utc": h.get("slot_utc"), "fetch_ok": h.get("fetch_ok"),
                                         "fetch_err": h.get("fetch_err"), "last_bar_utc": h.get("last_bar_utc"),
                                         "signals": len(h.get("signals") or []),
                                         "opened": [(o.get("strategy"), o.get("symbol"), o.get("ok")) for o in h.get("opened") or []]}
                                        for h in (_GH_LIVE_STATE.get("history") or [])[-16:]],
                       "paper_since_live": _gh_paper_since_live()}
        return rep
    except Exception as e:
        return {"error": str(e)[:160]}


async def _trend_atr_scan(force: bool = False) -> dict:
    """V.2.20.0 — روزی یک بار (≥ ۰۰:۰۷ UTC، پنجرهٔ ۶ ساعت): سیگنال trend_atr_daily روی ۲۰ نماد (همان تابع بک‌تست)."""
    now = time.time()
    day = int(now // 86400)
    if not TREND_ATR_ENABLED:
        return {}
    if not force and (_TATR_STATE.get("last_day") == day
                      or not _scan_gate("trend_atr_daily", day, now - day * 86400, 420, TSMOM_SCAN_WINDOW_SEC)):
        return {}
    _TATR_STATE["last_day"] = day
    _scan_mark("trend_atr_daily", day)
    res: dict[str, Any] = {"ts": now, "day_utc": time.strftime("%Y-%m-%d", time.gmtime(day * 86400)), "checks": [],
                           "signals": [], "opened": []}
    _TATR_STATE["last_result"] = res
    dr = _daily_research("trend_atr_daily")
    if not dr.get("passes"):
        res["note"] = "آزمون ۲ ساله trend_atr_daily قبول نشده (یا هنوز اجرا نشده) ⇒ فقط بررسی، بدون ورود"
    try:
        import backtest_strategies as _bs
        import backtest_daily as _bd

        async def _rows(sym_: str):
            df_ = await _daily_closed(sym_, limit=90)
            if df_ is None or len(df_) < 60:
                return None
            return [tuple(float(v) for v in r) for r in zip(df_["timestamp"].tolist(), df_["open"].tolist(),
                                                             df_["high"].tolist(), df_["low"].tolist(),
                                                             df_["close"].tolist())]
        brd = await _rows("BTC")
        if not brd:
            res["error"] = "کندل روزانهٔ BTC نیست"
            return res
        be50 = _bs._ema([r[4] for r in brd], _bd.TREND_ATR_EMA)[-1]
        btc_ok = bool(be50 is not None and brd[-1][4] > be50)
        res["btc_above_ema50"] = btc_ok
        if not btc_ok:
            res["note"] = "BTC زیر EMA50 روزانه ⇒ لانگ روندی ممنوع (فیلتر رژیم)"
            return res
        _closed_day = await _symbols_closed_since(day * 86400)
        cands = []
        for s_ in _trend_atr_symbols():
            rd = brd if s_ == "BTC" else await _rows(s_)
            if not rd:
                res["checks"].append({"symbol": s_, "reason": "داده کافی نیست"})
                continue
            e50 = _bs._ema([r[4] for r in rd], _bd.TREND_ATR_EMA)
            atr = _bs._atr(rd)
            k = len(rd) - 1
            sl_pct = _bd.trend_atr_signal(rd, e50, atr, k, btc_ok)
            if sl_pct is None:
                hi20 = max(z[2] for z in rd[k - _bd.TREND_ATR_DONCHIAN:k])
                res["checks"].append({"symbol": s_, "signal": None, "close": rd[k][4], "high20": hi20,
                                      "ema50": round(e50[k], 6) if e50[k] is not None else None,
                                      "dist_to_high20_pct": round((rd[k][4] / hi20 - 1) * 100, 2)})
                continue
            res["signals"].append({"symbol": s_, "sl_pct": round(sl_pct, 3)})
            if _norm_symbol(s_) in _closed_day:
                continue
            cands.append((sl_pct, s_, rd[k][4], e50[k], atr[k]))
        if not dr.get("passes"):
            return res
        for sl_pct, s_, c, e50k, a in sorted(cands)[:int(TREND_ATR_MAX_OPEN)]:   # کم‌نوسان‌ترین ⇒ ضرر SL کمتر
            lp = await toobit_market.get_live_price(s_)
            px = float((lp or {}).get("price") or c)
            sl = px * (1 - sl_pct / 100)
            tp = px * (1 + 4 * sl_pct / 100)   # TP دور (سقف ایمنی)؛ خروج اصلی استاپ متحرک روزانه
            out = await open_real_trade(s_, "long", px, sl, tp, 95,
                                        diagnostics={"strategy_id": "trend_atr_daily", "ema50_daily": e50k, "atr_daily": a})
            res["opened"].append({"symbol": s_, "direction": "long", "ok": bool((out or {}).get("ok")),
                                  "reason": str((out or {}).get("reason") or (out or {}).get("error") or "")[:160]})
    except Exception as e:
        res["error"] = str(e)[:200]
    return res


async def _trend_atr_exit_check(meta: dict, key: str) -> str | None:
    """V.2.20.0 — روزی یک بار: بسته شدن روزانه زیر استاپ متحرک شاندلیه ⇒ خروج؛ ۳۰ روز ⇒ پایان مهلت."""
    now = time.time()
    opened = float(meta.get("opened_at") or now)
    if now - opened >= TREND_ATR_MAX_HOLD_SEC:
        return "trend_atr_time_stop"
    day = int(now // 86400)
    if meta.get("tatr_checked_day") == day or now - day * 86400 < 300:
        return None
    meta["tatr_checked_day"] = day
    try:
        import backtest_strategies as _bs
        import backtest_daily as _bd
        df = await _daily_closed(key, limit=60)
        if df is None:
            return None
        rows = [tuple(float(v) for v in r) for r in zip(df["timestamp"].tolist(), df["open"].tolist(), df["high"].tolist(),
                                                         df["low"].tolist(), df["close"].tolist())]
        # کندل‌هایی که بعد از ورود شروع شده‌اند (مثل بک‌تست: از روز بعد از کندل سیگنال)
        since = [r[4] for r in rows if r[0] / 1000.0 >= opened - 86400 * 0.5]
        if not since:
            return None
        trail = _bd.trend_atr_trail(since, _bs._atr(rows)[-1])
        meta["trend_atr_trail"] = round(trail, 8) if trail is not None else None
        if trail is not None and rows[-1][4] < trail:
            return "trend_atr_trail_exit"
    except Exception:
        return None
    return None


# ─────────────────────────────────────────────────────────────
# V.2.18.1 — rs_intraday_50 زنده (همان تعریف backtest_intraday.py): درآمد روزانه
# ─────────────────────────────────────────────────────────────
RSI_ENABLED = False   # V.2.35.0 — rs_intraday_50 خاموش (موتور قدیمی)
RSI_TOP_N = 3
RSI_LOOKBACK_H = 12
RSI_MAX_HOLD_SEC = 12 * 3600
RSI_MAX_24H_RANGE_PCT = 25.0     # توکن‌های پامپی (دامنهٔ ۲۴ساعت بیشتر) کنار
_RSI_STATE: dict[str, Any] = {"last_slot": None, "last_result": None}


# V.2.18.3 — هیچ پوزیشن کوتاه‌مدتی (rel_strength / rs_intraday_50) بیشتر از این باز نمی‌ماند (بک‌تست هم با همین سقف)؛
# tsmom_daily (درآمد ماهانه) جداست: خروجش کراس EMA20 روزانه / ۱۴ روز.
INTRADAY_MAX_HOLD_HOURS = 5.0


def _family_max_hold(family: str) -> float:
    base = {"tsmom_daily": TSMOM_MAX_HOLD_SEC, "rs_intraday_50": RSI_MAX_HOLD_SEC,
            "trend_atr_daily": TREND_ATR_MAX_HOLD_SEC}.get(family, RS_MAX_HOLD_SEC)
    if family in ("rel_strength", "rs_intraday_50") and INTRADAY_MAX_HOLD_HOURS > 0:
        return min(float(base), float(INTRADAY_MAX_HOLD_HOURS) * 3600.0)
    return float(base)


def _rsi_universe() -> list[str]:
    u = ((_BACKTEST_STATE.get("universe") or {}).get("symbols") or [])
    if not u:
        try:
            from watchlist import WATCHLIST as _WL
            u = list(_WL)
        except Exception:
            u = []
    import backtest_intraday as _bi
    return [s_ for s_ in u if s_ != "BTC" and s_.upper() not in _bi.GOLD_NAMES]


async def _rs_intraday_scan(force: bool = False) -> dict:
    """هر ۴ ساعت (+۲ دقیقه). V.2.18.2 — دوطرفه:
    بازده ۱۲ساعت BTC > ۰ ⇒ لانگ قوی‌ترین‌ها (rs ≥ +۱٪، بالای EMA50، روند روزانه up)؛
    بازده ۱۲ساعت BTC < ۰ ⇒ شورت ضعیف‌ترین‌ها (rs ≤ −۱٪، زیر EMA50، روند روزانه down).
    شرط بایاس ۱h فقط اگر نسخهٔ انتخاب‌شده (gate_mode) strict باشد. شرط برقرار نیست ⇒ کاندیداها کاغذی (btc_gate).
    دامنهٔ ۲۴ساعت ≤ ۲۵٪، SL ۲×ATR (۰٫۸–۴٪)، TP ۲R، ۱۲ ساعت."""
    now = time.time()
    slot = int(now // (4 * 3600))
    if not RSI_ENABLED:
        return {}
    if not force and (_RSI_STATE.get("last_slot") == slot or not _scan_gate("rs_intraday_50", slot, now - slot * 4 * 3600, 90)):
        return {}
    _RSI_STATE["last_slot"] = slot
    _scan_mark("rs_intraday_50", slot)
    res: dict[str, Any] = {"ts": now, "slot_utc": time.strftime("%H:%M", time.gmtime(slot * 4 * 3600)),
                           "opened": [], "candidates": [], "skipped": [], "papered": []}
    _RSI_STATE["last_result"] = res
    try:
        import backtest_strategies as _bs
        import backtest_intraday as _bi
        import indicators as _ind
        bdf = await toobit_market.get_klines("BTC", "1h", limit=60)
        if bdf is None or len(bdf) < 30:
            res["reason"] = "کندل BTC در دسترس نیست"
            return res
        bret = float(bdf["close"].iloc[-1]) / float(bdf["close"].iloc[-1 - RSI_LOOKBACK_H]) - 1.0
        bias = _ind.trend_bias(bdf)
        res.update(btc_ret12_pct=round(bret * 100, 3), btc_h1=bias)
        side = "long" if bret > 0 else ("short" if bret < 0 else None)
        if side is None:
            res["reason"] = "بازده ۱۲ساعت BTC صفر است"
            return res
        mode = _gate_mode("rs_intraday_50", side)
        gate_ok = _bi.rs_gate_ok(side, mode, bret, bias)
        res.update(side=side, gate_mode=mode, gate_ok=gate_ok)
        sg = 1 if side == "long" else -1
        cands = []
        for s_ in _rsi_universe():
            try:
                df = await toobit_market.get_klines(s_, "1h", limit=60)
            except Exception:
                continue
            if df is None or len(df) < 52:
                continue
            closes = [float(x) for x in df["close"].tolist()]
            highs = [float(x) for x in df["high"].tolist()]
            lows = [float(x) for x in df["low"].tolist()]
            rng24 = (max(highs[-24:]) / max(1e-12, min(lows[-24:])) - 1.0) * 100.0
            if rng24 > RSI_MAX_24H_RANGE_PCT:
                res["skipped"].append({"symbol": s_, "why": f"دامنهٔ ۲۴ساعت {rng24:.1f}٪"})
                continue
            ema50 = _bs._ema(closes, 50)[-1]
            rs_ = (closes[-1] / closes[-1 - RSI_LOOKBACK_H] - 1.0 - bret) * 100.0
            if ema50 and sg * rs_ >= 1.0 and sg * (closes[-1] - ema50) > 0:
                rows_ = list(zip(df["timestamp"].tolist(), df["open"].tolist(), highs, lows, closes))
                cands.append((sg * rs_, s_, closes[-1], _rs_atr(rows_), rs_))
            await asyncio.sleep(0.15)
        cands.sort(reverse=True)
        res["candidates"] = [{"symbol": c[1], "rs_pct": round(c[4], 3)} for c in cands[:6]]
        want_tr = "up" if side == "long" else "down"
        n_done = 0
        _closed_slot = await _symbols_closed_since(slot * 4 * 3600)
        for _k, s_, px, atr, rs_ in cands:
            if n_done >= RSI_TOP_N:
                break
            if _norm_symbol(s_) in _closed_slot:   # V.2.18.5 — در همین بازه بسته شده (دستی/SL/…)
                res["skipped"].append({"symbol": s_, "why": "در همین بازهٔ ۴ ساعته بسته شده"})
                continue
            try:   # روند روزانهٔ نماد
                dd = await _daily_closed(s_, limit=40)
                if dd is None:
                    continue
                rd = list(zip(dd["timestamp"].tolist(), dd["open"].tolist(), dd["high"].tolist(),
                              dd["low"].tolist(), [float(x) for x in dd["close"].tolist()]))
                if _bi._daily_trend_series(rd)[1][-1] != want_tr:
                    res["skipped"].append({"symbol": s_, "why": f"روند روزانه {want_tr} نیست"})
                    continue
            except Exception:
                continue
            if not atr:
                continue
            sl_pct = min(4.0, max(0.8, 2 * atr / px * 100.0))
            _tpr = _exit_tp_r("rs_intraday_50", side)   # V.2.18.6
            sl, tp = px * (1 - sg * sl_pct / 100.0), px * (1 + sg * _tpr * sl_pct / 100.0)
            if not gate_ok:
                ok_p = _paper_open(s_, side, px, sl, tp, "rs_intraday_50", "btc_gate", score=95,
                                   drift=dict(_BTC_DRIFT_CACHE.get("state") or {}), time_stop_sec=float(_family_max_hold("rs_intraday_50")),
                                   extra={"matrix_cell": f"rs_intraday_50|{side}|{_market_state_now()}",
                                          "market_state": _market_state_now(), "gate_mode": mode, "btc_h1": bias})
                res["papered"].append({"symbol": s_, "ok": bool(ok_p)})
                n_done += 1
                continue
            out = await open_real_trade(s_, side, px, sl, tp, 95,
                                        diagnostics={"strategy_id": "rs_intraday_50", "rs_pct": round(rs_, 3),
                                                     "btc_ret12_pct": round(bret * 100, 3), "gate_mode": mode})
            ok_ = bool((out or {}).get("ok"))
            n_done += 1 if (ok_ or str((out or {}).get("reason") or "").startswith(
                ("forward_test", "matrix_off", "matrix_symbol_off"))) else 0   # V.2.20.0 — کاغذی هم سهم top_n
            res["opened"].append({"symbol": s_, "direction": side, "ok": ok_,
                                  "reason": str((out or {}).get("reason") or (out or {}).get("error") or "")[:160]})
        if not gate_ok:
            res["reason"] = (f"شرط BTC نسخهٔ {mode} برای {side} برقرار نیست (بایاس ۱h={bias}) — "
                             f"کاندیداها فقط کاغذی (btc_gate) ثبت شدند")
        elif not cands:
            res["reason"] = f"کاندیدای {side} با شرایط نبود"
    except Exception as e:
        res["error"] = str(e)[:200]
    return res


def _ex_top_from_result(r: dict) -> tuple[float | None, str | None]:
    """V.2.18.2 — میانگین خالص «بدون پرسودترین نماد» از همهٔ معاملات خودِ استراتژی (by_symbol)، نه از بدترین خانه."""
    bys = (r or {}).get("by_symbol") or {}
    tot = tot_n = 0.0
    best, best_c, best_n = None, None, 0
    for k, v in bys.items():
        try:
            n, a = int(v.get("n") or 0), float(v.get("net_avg_pct") or 0)
        except (TypeError, ValueError):
            continue
        tot += n * a
        tot_n += n
        if n and (best_c is None or n * a > best_c):
            best, best_c, best_n = k, n * a, n
    if best is None or tot_n - best_n <= 0:
        return None, best
    return round((tot - best_c) / (tot_n - best_n), 4), best


def _portfolio_report() -> dict:
    """V.2.18.1/2.18.2 — درآمد روزانه (کوتاه‌مدت، هر جهت جدا) و ماهانه (بلندمدت): انتظار از بک‌تست + نتیجهٔ زنده."""
    st = _BACKTEST_STATE
    pol = _MATRIX.get("policy") or {}
    live = _MATRIX.get("live") or {}
    notional = float(MIN_NOTIONAL_USDT) if "MIN_NOTIONAL_USDT" in globals() else 25.0

    def bt_of(r, prefix):
        a = r.get("all") or {}
        ext, top = _ex_top_from_result(r)
        cells = [v for k, v in pol.items() if k.startswith(prefix)]
        if ext is None and cells:   # پشتیبان: میانگین وزنی خانه‌ها
            ws = [(int(c.get("n_ex_top") or c.get("n") or 0), c.get("net_ex_top")) for c in cells if c.get("net_ex_top") is not None]
            wn = sum(n for n, _ in ws)
            ext = round(sum(n * float(v) for n, v in ws) / wn, 4) if wn else None
        return {"trades_per_day": r.get("trades_per_day"), "net_avg_pct": a.get("net_avg_pct"), "n": a.get("n"),
                "top_symbol": top, "net_avg_pct_ex_top_symbol": ext,
                "status": sorted({c.get("status") for c in cells if c.get("status")}) or None}

    def fam_live(prefix):
        rows = [v for k, v in live.items() if k.startswith(prefix)]
        n = sum(int(r.get("n") or 0) for r in rows)
        avg = (sum(float(r.get("avg_pct") or 0) * int(r.get("n") or 0) for r in rows) / n) if n else None
        return {"n": n, "avg_pct": round(avg, 4) if avg is not None else None,
                "usd_est": round(avg / 100.0 * notional * n, 3) if avg is not None else None}

    out = {"note": ("انتظار بر پایهٔ بک‌تست با حداقل حجم؛ «بدون پرسودترین نماد» = همهٔ معاملات منهای نماد پرسود (محافظه‌کارانه). "
                    "فقط وقتی شرط BTC همان جهت برقرار است معامله می‌شود. نتیجهٔ زنده جای بک‌تست را می‌گیرد."),
           "daily_income": {}, "monthly_long_term": {}}
    tot = 0.0
    for (fam, d), opts in GATE_VARIANTS.items():
        g = (_MATRIX.get("gate_mode") or {}).get(f"{fam}:{d}") or {}
        src, name = opts.get(str(g.get("mode") or "strict")) or opts["strict"]
        r = _variant_result(src, name)
        if not r:
            continue
        _em = _exit_mode(fam, d)   # V.2.18.6
        if _em != "base" and ((r.get("exit_modes") or {}).get(_em)):
            r = r["exit_modes"][_em]
        bt = bt_of(r, f"{fam}|{d}|")
        tpd, net = bt.get("trades_per_day"), bt.get("net_avg_pct_ex_top_symbol")
        if net is None:
            net = bt.get("net_avg_pct")
        bt["usd_per_day_conservative"] = round(tpd * net / 100.0 * notional, 3) if (tpd and net is not None) else None
        bt["gate_mode"] = g.get("mode") or "strict"
        bt["exit_mode"] = _em
        out["daily_income"][f"{fam}|{d}"] = {"backtest": bt, "live": fam_live(f"{fam}|{d}|")}
        if bt["usd_per_day_conservative"] and set(bt.get("status") or []) & {"on", "probe"}:
            tot += bt["usd_per_day_conservative"]
    out["daily_income_total_usd_conservative"] = round(tot, 3)
    dr = ((st.get("daily_research") or {}).get("tsmom_daily") or {})
    bt = bt_of(dr, "tsmom_daily|")
    per = (dr.get("period") or {}).get("days") or 0
    n_all = ((dr.get("all") or {}).get("n")) or 0
    net = bt.get("net_avg_pct")
    bt["trades_per_month"] = round(n_all / per * 30, 2) if per else None
    bt["usd_per_month"] = round(bt["trades_per_month"] * net / 100.0 * notional, 3) if (bt.get("trades_per_month") and net) else None
    out["monthly_long_term"]["tsmom_daily"] = {"backtest": bt, "live": fam_live("tsmom_daily|")}
    for _nm in ("tsmom_daily_ext", "trend_atr_daily"):   # V.2.20.0
        dr = ((st.get("daily_research") or {}).get(_nm) or {})
        if not dr:
            continue
        bt = bt_of(dr, f"{_nm}|")
        per = (dr.get("period") or {}).get("days") or 0
        n_all = ((dr.get("all") or {}).get("n")) or 0
        net = bt.get("net_avg_pct")
        bt["trades_per_month"] = round(n_all / per * 30, 2) if per else None
        bt["usd_per_month"] = (round(bt["trades_per_month"] * net / 100.0 * notional, 3)
                               if (bt.get("trades_per_month") and net) else None)
        bt["passes"] = bool(dr.get("passes"))
        bt["old_oos"] = dr.get("old_oos")
        if _nm == "tsmom_daily_ext":
            bt["extra_symbols_stats"] = dr.get("extra_symbols_stats")
        out["monthly_long_term"][_nm] = {"backtest": bt, "live": fam_live("trend_atr_daily|") if _nm == "trend_atr_daily"
                                         else {"note": "زنده زیر خانوادهٔ tsmom_daily"}}
    return out


def _rs_atr(rows: list, n: int = 14) -> float | None:
    import backtest_strategies as _bs
    a = _bs._atr([tuple(r[:5]) for r in rows], n)
    return a[-1] if a else None


async def _rel_strength_scan(force: bool = False) -> dict:
    """هر ۴ ساعت (بسته شدن کندل‌های ۰۰/۰۴/…/۲۰ UTC + ۹۰ ثانیه): همان قاعدهٔ بک‌تست ⇒ حداکثر ۲ ورود."""
    now = time.time()
    slot = int(now // (4 * 3600))
    if not RS_ENABLED:
        return {}
    # V.2.18.9 — اول rs_intraday_50 (مزیت بک‌تست بیشتر) جای پوزیشن را می‌گیرد؛ rel_strength تا ۱۰ دقیقه منتظر آن می‌ماند
    if not force and RSI_ENABLED and AUTO_MATRIX and _SCAN_SLOTS.get("rs_intraday_50") != slot and now - slot * 4 * 3600 < 600:
        return {}
    if not force and (_RS_STATE.get("last_slot") == slot or not _scan_gate("rel_strength", slot, now - slot * 4 * 3600, 90)):
        return {}
    _RS_STATE["last_slot"] = slot
    _scan_mark("rel_strength", slot)
    res: dict[str, Any] = {"ts": now, "slot_utc": time.strftime("%H:%M", time.gmtime(slot * 4 * 3600)), "opened": [], "candidates": []}
    # V.2.15.1 — نتیجه در هر حالت (حتی «BTC صعودی نیست») ثبت شود
    _RS_STATE["last_result"] = res
    _RS_STATE["last_scan"] = now
    try:
        import backtest_strategies as _bs
        import indicators as _ind
        bdf = await toobit_market.get_klines("BTC", "1h", limit=60)
        if bdf is None or len(bdf) < 30:
            res["reason"] = "کندل BTC در دسترس نیست"
            return res
        bret = float(bdf["close"].iloc[-1]) / float(bdf["close"].iloc[-25]) - 1.0
        bias = _ind.trend_bias(bdf)
        mode = _gate_mode("rel_strength", "long")   # V.2.18.2
        res.update(btc_ret24_pct=round(bret * 100, 3), btc_h1=bias, gate_mode=mode)
        if not bret > 0:
            res["reason"] = "بازده ۲۴ساعت BTC منفی است (شرط rel_strength)"
            return res
        gate_ok = mode == "ret" or bias == "long"
        res["gate_ok"] = gate_ok
        try:
            from watchlist import WATCHLIST as _WL
        except Exception:
            _WL = []
        cands = []
        for s_ in _WL:
            if s_ == "BTC":
                continue
            try:
                df = await toobit_market.get_klines(s_, "1h", limit=60)
            except Exception:
                continue
            if df is None or len(df) < 52:
                continue
            closes = [float(x) for x in df["close"].tolist()]
            ema50 = _bs._ema(closes, 50)[-1]
            ret = closes[-1] / closes[-25] - 1.0
            rs_ = (ret - bret) * 100.0
            rows_ = list(zip(df["timestamp"].tolist(), df["open"].tolist(), df["high"].tolist(), df["low"].tolist(), closes))
            atr = _rs_atr(rows_)
            if ema50 and atr and rs_ >= RS_MIN_RS_PCT and closes[-1] > ema50:
                cands.append((rs_, s_, closes[-1], atr))
            await asyncio.sleep(0.2)
        cands.sort(reverse=True)
        res["candidates"] = [{"symbol": s_, "rs_pct": round(r_, 3)} for r_, s_, _c, _a in cands[:5]]
        _closed_slot = await _symbols_closed_since(slot * 4 * 3600)   # V.2.18.5
        cands = [c for c in cands if _norm_symbol(c[1]) not in _closed_slot]
        for r_, s_, px, atr in cands[:RS_TOP_N]:
            sl_pct = min(RS_SL_MAX_PCT, max(RS_SL_MIN_PCT, RS_SL_ATR * atr / px * 100.0))
            sl = px * (1 - sl_pct / 100.0)
            tp = px * (1 + _exit_tp_r("rel_strength", "long") * sl_pct / 100.0)   # V.2.18.6
            if not gate_ok:   # V.2.18.2 — فقط بایاس ۱h مانع است ⇒ کاغذی برای سنجش اثر این شرط
                ok_p = _paper_open(s_, "long", px, sl, tp, "rel_strength", "btc_gate", score=95,
                                   drift=dict(_BTC_DRIFT_CACHE.get("state") or {}), time_stop_sec=float(_family_max_hold("rel_strength")),
                                   extra={"matrix_cell": f"rel_strength|long|{_market_state_now()}",
                                          "market_state": _market_state_now(), "gate_mode": mode, "btc_h1": bias})
                res.setdefault("papered", []).append({"symbol": s_, "ok": bool(ok_p)})
                continue
            out = await open_real_trade(s_, "long", px, sl, tp, 95,
                                        diagnostics={"strategy_id": "rel_strength", "rs_pct": round(r_, 3),
                                                     "atr_1h": atr, "btc_ret24_pct": round(bret * 100, 3)})
            res["opened"].append({"symbol": s_, "ok": bool((out or {}).get("ok")),
                                  "reason": str((out or {}).get("reason") or (out or {}).get("error") or "")[:160]})
        if not gate_ok:
            res["reason"] = f"بایاس ۱h BTC={bias} (نسخهٔ strict) — کاندیداها فقط کاغذی (btc_gate) ثبت شدند"
    except Exception as e:
        res["error"] = str(e)[:200]
    _RS_STATE["last_result"] = res
    _RS_STATE["last_scan"] = now
    return res


def _whatif_summary(rows: list[dict]) -> dict:
    """جمع قواعد خروج روی معاملاتی که مسیر کامل دارند (درصد خالص؛ ×۰٫۲۵ ≈ دلار با notional ۲۵$)."""
    items = [r for r in rows if isinstance(r.get("exit_whatif"), dict) and "base" in r["exit_whatif"]]
    tot: dict[str, float] = {}
    for r in items:
        for k in ("base", "be_net", "ratchet", "fail10"):
            tot[k] = round(tot.get(k, 0.0) + float(r["exit_whatif"].get(k) or 0), 4)
    return {
        "n": len(items),
        "sum_net_pct": tot,
        "note": "شبیه‌سازی محافظه‌کارانه روی کندل واقعی هر معامله؛ تا n≥۲۰ قاعده‌ای فعال نکن",
    }


try:
    _load_paper()
except Exception:
    pass


# ─────────────────────────────────────────────────────────────
# V.2.11.3 — ورود محافظت‌شده (LIMIT + priceType=INPUT + IOC با سقف لغزش)
# شاهد: TON شورت ۱ اکتبر — چک قبل از سفارش روی ۱٫۵۲۱ رد شد، سفارش مارکت روی ۱٫۵۱۸ (۰٫۲٪ بدتر) پر شد،
# SL از ۰٫۶۵٪ به ۰٫۸۴٪ رسید و گارد بعد از fill بست (−۰٫۰۳۶$ فقط هزینه).
# با این حالت: سفارش فقط تا «قیمت مرجع ± سقف لغزش» پر می‌شود؛ اگر بازار جلوتر رفته باشد، پر نمی‌شود و کارمزدی هم نیست.
# سقف لغزش طوری کوچک می‌شود که هر fill مجاز از گارد بعد از fill هم رد شود.
# پیش‌فرض خاموش؛ اول با self-test بدون ریسک (سفارش IOC دور از بازار که پر نمی‌شود) پارامترها تأیید شود.
# ─────────────────────────────────────────────────────────────
ENTRY_PROTECTED_IOC = False
ENTRY_MAX_SLIPPAGE_PCT = 0.08
ENTRY_PROTECTED_SELFTEST = False
_PROTECTED_SELFTEST: dict[str, Any] = {}

# V.2.13.0 — TP با کارمزد maker: خودکار (self-test یک‌بار؛ اگر موفق ⇒ برای همهٔ ورودها)
TREND_MAKER_TP = False      # V.2.18.4 — خاموش؛ دلیل در apply_runtime_settings
MAKER_TP_SELFTEST = False
_MAKER_SELFTEST: dict[str, Any] = {}
MAKER_TIF_CANDIDATES = ("LIMIT_MAKER", "POST_ONLY", "GTC")


async def _run_maker_selftest() -> dict:
    """سفارش BUY_OPEN limit با حداقل حجم ۲٪ زیر بازار ⇒ پذیرفته می‌شود؟ کدام timeInForce؟ لغو کار می‌کند؟
    (نمی‌تواند پر شود؛ اگر غیرمنتظره پر شد فوراً بسته می‌شود.)"""
    res: dict[str, Any] = {"ts": time.time(), "ok": False, "tries": []}
    try:
        _n, rows = await _open_positions_count()
        open_syms = {_norm_symbol(str(r.get("symbol") or "")) for r in (rows or [])}
    except Exception:
        open_syms = set()
    sym = next((s_ for s_ in ("DOGE", "XRP", "ADA", "TRX") if s_ not in open_syms), None)
    if not sym:
        res["reason"] = "همهٔ نمادهای آزمایشی پوزیشن باز دارند"
        return res
    res["symbol"] = sym
    try:
        filt = await toobit_private.get_symbol_filters(sym)
        tick = filt.get("tick_size")
        step = float(filt.get("step_size") or 1.0)
        min_qty = float(filt.get("min_qty") or step)
        lp = await toobit_market.get_live_price(sym)
        px = float((lp or {}).get("price") or 0)
        if not tick or px <= 0:
            res["reason"] = "tick_size یا قیمت در دسترس نیست"
            return res
        lim = toobit_private.format_price_value(toobit_private.round_price_to_tick(px * 0.98, float(tick), "down"), float(tick))
        qty = toobit_private.format_qty_value(toobit_private.round_qty_to_step(min_qty, step, min_qty), step)
        res.update(limit_price=lim, quantity=qty)
        for tif in MAKER_TIF_CANDIDATES:
            r = await toobit_private.place_limit_order(sym, "BUY_OPEN", qty, lim, tif,
                                                       client_order_id=f"sd_mtest_{uuid.uuid4().hex[:8]}")
            if r.get("error") or not (r.get("orderId") or r.get("clientOrderId")):
                res["tries"].append({"tif": tif, "accepted": False, "response": r})
                continue
            oid = r.get("orderId")
            await asyncio.sleep(1.0)
            filled = await _confirm_ioc_fill(sym, "long", attempts=1, wait_sec=0.2)
            if filled:
                try:
                    await toobit_private.close_position_market(sym, "long", str(filled.get("qty")))
                except Exception:
                    pass
                res["tries"].append({"tif": tif, "accepted": True, "unexpected_fill": True})
                res["reason"] = "سفارش دور از بازار پر شد (غیرمنتظره) — بسته شد؛ maker TP را روشن نکن"
                return res
            c = await toobit_private.cancel_order(sym, order_id=oid)
            cancel_ok = not c.get("error")
            res["tries"].append({"tif": tif, "accepted": True, "status": r.get("status"), "cancel_ok": cancel_ok,
                                 "cancel_response": c})
            if cancel_ok:
                res.update(ok=True, tif=tif, reason=f"پذیرفته شد با timeInForce={tif} و لغو کار کرد — می‌توان trend_maker_tp را روشن کرد")
            else:
                res["reason"] = "سفارش پذیرفته شد ولی لغو نشد — سفارش باز را دستی در صرافی ببین؛ maker TP را روشن نکن"
            return res
        res["reason"] = "هیچ timeInForce پذیرفته نشد"
    except Exception as e:
        res["reason"] = f"خطا: {str(e)[:160]}"
    return res


async def _place_maker_tp(meta: dict) -> None:
    """بعد از ورود روند: سفارش limit بستن روی TP (کارمزد maker). خطا ⇒ فقط ثبت؛ TP شرطی صرافی سر جایش است."""
    tif = (_MAKER_SELFTEST or {}).get("tif")
    if not (TREND_MAKER_TP and tif and (_MAKER_SELFTEST or {}).get("ok")):
        return
    try:
        sym = _norm_symbol(str(meta.get("symbol") or ""))
        filt = await toobit_private.get_symbol_filters(sym)
        tick = filt.get("tick_size")
        tp = float(meta.get("target") or 0)
        qty = str(meta.get("quantity") or "")
        if not tick or tp <= 0 or not qty:
            meta["maker_tp"] = {"ok": False, "reason": "tick/tp/qty نامعلوم"}
            return
        long_ = str(meta.get("direction")) == "long"
        price = toobit_private.format_price_value(
            toobit_private.round_price_to_tick(tp, float(tick), "up" if long_ else "down"), float(tick))
        r = await toobit_private.place_limit_order(sym, "SELL_CLOSE" if long_ else "BUY_CLOSE", qty, price, tif,
                                                   client_order_id=f"sd_mtp_{uuid.uuid4().hex[:12]}")
        if r.get("error") or not r.get("orderId"):
            meta["maker_tp"] = {"ok": False, "response": r}
            return
        meta["maker_tp"] = {"ok": True, "order_id": r.get("orderId"), "price": price, "tif": tif, "ts": time.time()}
    except Exception as e:
        meta["maker_tp"] = {"ok": False, "reason": str(e)[:120]}


async def _release_close_limits(key: str, meta: dict | None = None) -> dict:
    """V.2.18.4 — لغو همهٔ سفارش‌های limit «بستن» باز این نماد (maker TP قدیمی یا هر limit بستن دیگر)
    تا مقدار پوزیشن آزاد شود: SL/TP شرطی صرافی و بستن مارکت ربات فقط با مقدار آزاد اجرا می‌شوند."""
    out: dict[str, Any] = {"ts": time.time(), "canceled": []}
    try:
        await _cancel_maker_tp(meta)
    except Exception:
        pass
    try:
        raw = await toobit_private.get_open_orders(key, "LIMIT")
        if isinstance(raw, dict) and raw.get("error"):   # نوع LIMIT پذیرفته نشد ⇒ بدون فیلتر نوع
            out["error_limit_type"] = str(raw.get("error"))[:120]
            raw = await toobit_private._signed_get("/api/v1/futures/openOrders",
                                                   {"symbol": toobit_private._to_futures_symbol(key), "limit": 100})
            if isinstance(raw, dict) and raw.get("error"):
                out["error"] = str(raw.get("error"))[:120]
        for o in toobit_private._as_list(raw):
            if not isinstance(o, dict):
                continue
            side = str(o.get("side") or "").upper()
            if side not in ("SELL_CLOSE", "BUY_CLOSE") or not o.get("orderId"):
                continue
            _ot = f"{o.get('orderType') or ''} {o.get('type') or ''}".upper()
            try:
                _stp = float(o.get("stopPrice") or 0)
            except (TypeError, ValueError):
                _stp = 0.0
            if "STOP" in _ot or "PROFIT" in _ot or "LOSS" in _ot or _stp > 0:
                continue   # SL/TP شرطی هرگز لغو نشود
            r = await toobit_private.cancel_order(key, order_id=str(o.get("orderId")))
            out["canceled"].append({"orderId": o.get("orderId"), "side": side, "price": o.get("price"),
                                    "ok": not (isinstance(r, dict) and r.get("error"))})
    except Exception as e:
        out["error"] = str(e)[:120]
    if meta is not None:
        meta["close_limits_released"] = out
    return out


async def _cancel_maker_tp(meta: dict | None) -> None:
    """بعد از بسته شدن پوزیشن (با هر دلیلی): سفارش limit TP باقی‌مانده لغو شود."""
    try:
        mt = (meta or {}).get("maker_tp") or {}
        if not mt.get("ok") or mt.get("canceled"):
            return
        r = await toobit_private.cancel_order(_norm_symbol(str(meta.get("symbol") or "")), order_id=mt.get("order_id"))
        mt["canceled"] = True
        mt["cancel_response"] = r if r.get("error") else "ok"
    except Exception as e:
        try:
            (meta or {}).setdefault("maker_tp", {})["cancel_error"] = str(e)[:120]
        except Exception:
            pass


def _protected_entry_plan(direction: str, ref_price: float, signal_entry: float, stop_loss: float,
                          target: float, strategy_id: str | None, tick: float | None,
                          max_slip_pct: float) -> dict:
    """قیمت limit ورود: بدترین fill مجاز = ref×(1±slip)، گرد به tick در جهت امن، و کوچک‌شدن slip
    تا جایی که بدترین fill هم از گارد بعد از fill رد شود. خروجی: ok, limit_price, slip_used, reason."""
    out: dict[str, Any] = {"ok": False, "ref_price": ref_price, "tick": tick, "max_slip_pct": max_slip_pct}
    if not tick or tick <= 0:
        out["reason"] = "tick_size نامعلوم — سفارش مارکت عادی"
        return out
    if ref_price <= 0:
        out["reason"] = "قیمت مرجع نامعتبر"
        return out
    sign = 1.0 if str(direction).lower() != "short" else -1.0
    for frac in (1.0, 0.75, 0.5, 0.25, 0.0):
        slip = float(max_slip_pct) * frac
        raw = ref_price * (1.0 + sign * slip / 100.0)
        lim = toobit_private.round_price_to_tick(raw, tick, "down" if sign > 0 else "up")
        # اگر گرد کردن از مرجع هم بدتر کرد، یک tick به سمت امن
        if sign > 0 and lim < ref_price - 1e-12 and frac > 0:
            lim = toobit_private.round_price_to_tick(ref_price, tick, "down")
        if sign < 0 and lim > ref_price + 1e-12 and frac > 0:
            lim = toobit_private.round_price_to_tick(ref_price, tick, "up")
        _sl, _tp, ra = _reanchor_levels_from_fill(
            direction, float(signal_entry), lim, float(stop_loss), float(target), strategy_id=strategy_id,
        )
        if not ra.get("invalid"):
            out.update(ok=True, limit_price=lim, limit_str=toobit_private.format_price_value(lim, tick),
                       slip_used_pct=round(abs(lim / ref_price - 1.0) * 100.0, 4))
            return out
    out["reason"] = "حتی با لغزش صفر، گارد بعد از fill رد می‌کند"
    return out


async def _confirm_ioc_fill(symbol: str, direction: str, attempts: int = 3, wait_sec: float = 0.8) -> dict | None:
    """بعد از سفارش IOC: پوزیشن واقعی روی صرافی؟ None یعنی پر نشد (یا هنوز دیده نشده — مدیر بعداً بازیابی می‌کند)."""
    import asyncio as _aio
    key = _norm_symbol(symbol)
    want = "short" if str(direction).lower() == "short" else "long"
    for _ in range(max(1, attempts)):
        await _aio.sleep(wait_sec)
        try:
            _n, rows = await _open_positions_count()
        except Exception:
            rows = None
        for r in rows or []:
            try:
                if _norm_symbol(str(r.get("symbol") or "")) != key:
                    continue
                if toobit_private.parse_position_side(r) != want:
                    continue
                q = toobit_private.parse_position_qty(r)
                if q and q > 0:
                    return {"row": r, "qty": q}
            except Exception:
                continue
    return None


async def _run_protected_selftest() -> dict:
    """یک بار در هر بوت (وقتی entry_protected_ioc_selftest روشن است):
    سفارش LIMIT/INPUT/IOC خرید با حداقل حجم، ۲٪ زیر قیمت → نباید پر شود؛ فقط پذیرش پارامترها و فرمت قیمت را می‌سنجد."""
    res: dict[str, Any] = {"ts": time.time(), "ok": False}
    try:
        _n, rows = await _open_positions_count()
        open_syms = {_norm_symbol(str(r.get("symbol") or "")) for r in (rows or [])}
    except Exception:
        open_syms = set()
    sym = next((s_ for s_ in ("DOGE", "XRP", "ADA", "TRX") if s_ not in open_syms), None)
    if not sym:
        res["reason"] = "همهٔ نمادهای آزمایشی پوزیشن باز دارند — بعداً"
        return res
    res["symbol"] = sym
    try:
        filt = await toobit_private.get_symbol_filters(sym)
        tick = filt.get("tick_size")
        step = float(filt.get("step_size") or 1.0)
        min_qty = float(filt.get("min_qty") or step)
        lp = await toobit_market.get_live_price(sym)
        px = float((lp or {}).get("price") or 0)
        res.update(tick_size=tick, live_price=px, min_qty=min_qty)
        if not tick or px <= 0:
            res["reason"] = "tick_size یا قیمت لحظه‌ای در دسترس نیست"
            return res
        lim = toobit_private.round_price_to_tick(px * 0.98, float(tick), "down")
        qty_val = toobit_private.round_qty_to_step(min_qty, step, min_qty)
        qty_str = toobit_private.format_qty_value(qty_val, step)
        lim_str = toobit_private.format_price_value(lim, float(tick))
        res.update(limit_price=lim_str, quantity=qty_str)
        r = await toobit_private.place_futures_market_order(
            symbol=sym, side="BUY_OPEN", quantity=qty_str, limit_price=lim_str,
            client_order_id=f"sd_selftest_{uuid.uuid4().hex[:8]}",
        )
        res["exchange_response"] = r
        if r.get("error"):
            res["reason"] = "صرافی سفارش آزمایشی را نپذیرفت — حالت محافظت‌شده را روشن نکن"
            return res
        filled = await _confirm_ioc_fill(sym, "long", attempts=2, wait_sec=1.0)
        if filled:
            # نباید رخ دهد؛ برای ایمنی فوراً ببند
            res["unexpected_fill"] = True
            try:
                await toobit_private.close_position_market(sym, "long", str(filled.get("qty")))
            except Exception as ce:
                res["close_error"] = str(ce)[:120]
            res["reason"] = "سفارش دور از بازار پر شد (غیرمنتظره) — بسته شد؛ حالت محافظت‌شده را روشن نکن"
            return res
        res["ok"] = True
        res["reason"] = "پذیرفته شد و پر نشد (درست) — می‌توان entry_protected_ioc را روشن کرد"
    except Exception as e:
        res["reason"] = f"خطا: {str(e)[:160]}"
    return res


# ─────────────────────────────────────────────────────────────
# V.2.10.100 — ابزار ثبت (بدون تغییر منطق ورود/خروج)
# ─────────────────────────────────────────────────────────────
PRE_ORDER_SLIP_BAND_PCT = 0.05     # چک قبل از سفارش رنج: قیمت لحظه‌ای ± این درصد
RANGE_EXIT_IGNORE_REGIME = False   # پیش‌فرض خاموش: رفتار خروج .99 حفظ می‌شود تا نمونهٔ ۳۰تایی آلوده نشود
PRICE_PATH_MAX_POINTS = 240
SL_CHANGES_MAX = 30


def _geom(entry: float, stop_loss: float, target: float) -> dict:
    """هندسهٔ یک سطح ورود: فاصلهٔ SL/TP و RR خالص با همان friction ریل."""
    try:
        e, sl, tp = float(entry), float(stop_loss), float(target)
        sl_pct = abs(e - sl) / e * 100.0
        tp_pct = abs(tp - e) / e * 100.0
        fr = abs(float(ROUND_TRIP_FRICTION_PCT))
        net_rr = max(0.0, tp_pct - fr) / (sl_pct + fr) if (sl_pct + fr) > 0 else 0.0
        return {"entry": e, "sl_pct": round(sl_pct, 4), "tp_pct": round(tp_pct, 4), "net_rr": round(net_rr, 3)}
    except (TypeError, ValueError, ZeroDivisionError):
        return {}


def _log_sl_change(meta: dict, old_sl: Any, new_sl: Any, reason: str,
                   price: Any = None, verified: Any = None, extra: dict | None = None) -> None:
    """هر تغییر SL با زمان/قیمت/دلیل — برای اثبات علت خروج‌های کوچک."""
    try:
        now = time.time()
        row = {
            "t": round(now, 1),
            "elapsed": int(now - float(meta.get("opened_at") or now)),
            "from": float(old_sl) if old_sl not in (None, "") else None,
            "to": float(new_sl) if new_sl not in (None, "") else None,
            "reason": str(reason),
            "price": float(price) if price not in (None, "") else None,
            "verified": verified,
        }
        if extra:
            row.update(extra)
        lst = meta.setdefault("sl_changes", [])
        lst.append(row)
        if len(lst) > SL_CHANGES_MAX:
            del lst[: len(lst) - SL_CHANGES_MAX]
    except Exception:
        pass


def _sample_price_path(meta: dict, price: Any, now: float | None = None) -> None:
    """مسیر قیمت هر معامله (هر دور مدیر ≈۴۵ ثانیه) برای آزمون قواعد خروج روی معاملات واقعی."""
    try:
        now = float(now or time.time())
        t0 = float(meta.get("opened_at") or now)
        path = meta.setdefault("price_path", [])
        path.append([int(now - t0), float(price)])
        if len(path) > PRICE_PATH_MAX_POINTS:
            meta["price_path"] = path[:1] + path[1:-1][::2] + path[-1:]
    except Exception:
        pass


async def _pre_order_geometry_check(
    symbol: str, direction: str, signal_entry: float, stop_loss: float, target: float,
    strategy_id: str | None,
) -> tuple[bool, str, dict]:
    """V.2.10.100 — همان اعتبارسنجی بعد از fill را قبل از ارسال سفارش اجرا کن.

    گارد بعد از fill دست نمی‌خورد. این چک فقط سفارشی را نمی‌فرستد که روی قیمت لحظه‌ای
    (و برای رنج: ± باند اسلیپیج) همان گارد باطلش می‌کند — تا کارمزد «لغو فوری» پرداخت نشود.
    قیمت لحظه‌ای در دسترس نباشد → مانع نمی‌شود (گارد بعد از fill هنوز هست).
    """
    info: dict = {"band_pct": 0.0, "probes": []}
    try:
        lp = await toobit_market.get_live_price(symbol)
        px = float((lp or {}).get("price") or 0)
    except Exception:
        px = 0.0
    info["live_price"] = px
    if px <= 0:
        return True, "no_live_price", info
    sid = str(strategy_id or "")
    band = float(PRE_ORDER_SLIP_BAND_PCT) / 100.0 if sid == "range_scalp" else 0.0
    info["band_pct"] = band * 100.0
    probes = [px] if band <= 0 else [px * (1.0 - band), px, px * (1.0 + band)]
    for f in probes:
        _sl, _tp, ra = _reanchor_levels_from_fill(
            direction, float(signal_entry), f, float(stop_loss), float(target), strategy_id=strategy_id,
        )
        info["probes"].append({"fill": round(f, 8), "invalid": bool(ra.get("invalid")), "reason": ra.get("reason")})
        if ra.get("invalid"):
            return False, (
                f"pre_order: سفارش ارسال نشد — در fill≈{f:.6g} گارد بعد از fill رد می‌کرد "
                f"({ra.get('reason')})"
            ), info
    return True, "ok", info


def _passes_fee_filter(
    entry: float,
    stop_loss: float,
    target: float,
    strategy_id: str | None = None,
) -> tuple[bool, str]:
    """فیلتر هندسه + RR خالص بعد از اصطکاک (V.2.10.40).
    V.2.10.93: همیشه apply_runtime_settings تا min_rr/max_sl از Settings زنده باشد.
    V.2.10.97: سقف SL و min RR برای range_scalp از پارامترهای range می‌آید.
    """
    try:
        apply_runtime_settings()
    except Exception:
        pass
    if entry <= 0 or not _levels_finite(entry, stop_loss, target):
        return False, "entry/SL/TP نامعتبر یا غیرمتناهی"
    sl_dist = abs(entry - stop_loss) / entry * 100
    tp_dist = abs(target - entry) / entry * 100
    sid = str(strategy_id or "")
    max_sl = float(MAX_SL_DISTANCE_PCT)
    min_rr = float(MIN_RR_REAL)
    min_tp = float(MIN_TP_DISTANCE_PCT)
    if sid == "range_scalp":
        max_sl = float(RANGE_MAX_SL_DISTANCE_PCT)
        min_rr = float(RANGE_MIN_RR)
        min_tp = float(RANGE_MIN_TP_PCT)
    elif sid == "weak_trend":
        min_rr = float(MIN_RR_REAL)
    elif sid in ("rel_strength", "rs_intraday_50"):   # V.2.15.0/2.18.1 — هندسهٔ خودش (SL ۰٫۸–۴٪، TP ۲R)
        max_sl = float(RS_SL_MAX_PCT) + 0.05
        min_rr = 1.0
        min_tp = float(RS_SL_MIN_PCT)
    elif sid == "tsmom_daily":    # V.2.17.0 — SL روزانه ۳٪ تا سقف زنده
        max_sl = float(TSMOM_LIVE_SL_CAP_PCT) + 0.05
        min_rr = 1.0
        min_tp = 3.0
    elif sid == "trend_atr_daily":    # V.2.20.0
        max_sl = float(TREND_ATR_SL_CAP_PCT) + 0.05
        min_rr = 1.0
        min_tp = 3.0
    if sid in GH_GOLD_STRATEGIES:   # V.2.25.0 — هندسهٔ خود استراتژی (کارمزد/لغزش در بک‌تست حساب شده)
        if 0 < sl_dist <= float(GH_SL_CAP_PCT) + 0.05 and tp_dist > 0:
            return True, "ok"
        return False, f"هندسهٔ طلا نامعتبر (SL {sl_dist:.3f}% TP {tp_dist:.3f}%)"
    elif sid in GH_LIVE_STRATEGIES:    # V.2.22.1
        max_sl = float(GH_SL_CAP_PCT) + 0.05
        min_rr = 0.05   # V.2.24.0 — TP همان ROI خود استراتژی (adxmomentum: ۱٪ با SL ۱۰٪)
        min_tp = 0.5
    if sl_dist < MIN_SL_DISTANCE_PCT:
        return False, f"فاصله SL ({sl_dist:.2f}%) کمتر از حداقل ({MIN_SL_DISTANCE_PCT}%)"
    # V.2.10.44: تولرانس اعشار تا SL دقیقاً روی سقف رد نشود (مثل NEAR 1.50)
    if sl_dist > max_sl + 1e-6:
        return False, (
            f"فاصله SL ({sl_dist:.4f}%) بیشتر از سقف اسکالپ ({max_sl:.4f}%) — "
            f"ریسک یک‌ضرب غیرمجاز"
        )
    fr = abs(ROUND_TRIP_FRICTION_PCT)
    if tp_dist <= fr * 1.5:
        return False, f"هدف بعد از کارمزد سودی ندارد (TP {tp_dist:.2f}% ≤ friction)"
    if tp_dist < min_tp:
        return False, f"فاصله TP ({tp_dist:.2f}%) کمتر از حداقل {min_tp}%"
    # RR ناخالص (برای لاگ)
    gross_rr = (tp_dist / sl_dist) if sl_dist > 0 else 0.0
    # RR خالص: (TP − friction) / (SL + friction)
    net_tp = max(0.0, tp_dist - fr)
    net_sl = sl_dist + fr
    net_rr = (net_tp / net_sl) if net_sl > 0 else 0.0
    if net_rr < float(min_rr) - 1e-9:
        return False, (
            f"R:R خالص ضعیف ({net_rr:.2f} < {float(min_rr):.2f}) "
            f"gross={gross_rr:.2f} TP={tp_dist:.2f}% SL={sl_dist:.2f}% fr={fr:.2f}%"
        )
    return True, "ok"



def _levels_finite(*vals: float) -> bool:
    for v in vals:
        try:
            x = float(v)
        except (TypeError, ValueError):
            return False
        if x != x or x in (float("inf"), float("-inf")):
            return False
    return True


def _reanchor_levels_from_fill(
    direction: str,
    signal_entry: float,
    fill: float,
    stop_loss: float,
    target: float,
    strategy_id: str | None = None,
) -> tuple[float, float, dict]:
    """V.2.10.98: range keeps structural SL/TP. Trend still re-anchors geometry.
    Both paths validate with the same strategy fee policy used before the order.
    """
    info: dict = {"ok": True, "reanchored": False, "clamped_sl": False, "invalid": False, "reason": "", "strategy_id": strategy_id or "trend"}
    if not _levels_finite(signal_entry, fill, stop_loss, target) or fill <= 0 or signal_entry <= 0:
        info["ok"] = False
        info["invalid"] = True
        info["reason"] = "fill/signal نامعتبر"
        return stop_loss, target, info

    sid = str(strategy_id or "")
    d = str(direction).lower()
    if sid == "range_scalp":
        # Mid and edge do not move because the fill moved.
        if d == "short":
            struct_ok = target < fill < stop_loss
        else:
            struct_ok = stop_loss < fill < target
        if not struct_ok:
            info["ok"] = False
            info["invalid"] = True
            info["reason"] = "fill از ساختار رنج عبور کرد"
            return stop_loss, target, info
        ok, reason = _passes_fee_filter(fill, stop_loss, target, strategy_id="range_scalp")
        if not ok:
            info["ok"] = False
            info["invalid"] = True
            info["reason"] = f"fill_invalidated: {reason}"
            return stop_loss, target, info
        info["sl_dist_pct"] = round(abs(fill - stop_loss) / fill * 100.0, 4)
        info["tp_dist_pct"] = round(abs(target - fill) / fill * 100.0, 4)
        info["structural_fixed"] = True
        return float(stop_loss), float(target), info

    # فاصله درصدی اصلی از سیگنال — فقط trend / weak_trend
    sl_pct = abs(signal_entry - stop_loss) / signal_entry
    tp_pct = abs(target - signal_entry) / signal_entry
    if sl_pct <= 0:
        info["ok"] = False
        info["invalid"] = True
        info["reason"] = "sl_pct صفر"
        return stop_loss, target, info

    if d == "short":
        new_sl = fill * (1.0 + sl_pct)
        new_tp = fill * (1.0 - tp_pct)
    else:
        new_sl = fill * (1.0 - sl_pct)
        new_tp = fill * (1.0 + tp_pct)

    info["reanchored"] = abs(new_sl - stop_loss) / max(fill, 1e-12) > 1e-6 or abs(new_tp - target) / max(fill, 1e-12) > 1e-6

    sl_dist = abs(fill - new_sl) / fill * 100.0
    tp_dist = abs(new_tp - fill) / fill * 100.0
    max_sl_cap = (float(RS_SL_MAX_PCT) + 0.05 if sid in ("rel_strength", "rs_intraday_50")
                  else float(TSMOM_LIVE_SL_CAP_PCT) + 0.05 if sid == "tsmom_daily"
                  else float(TREND_ATR_SL_CAP_PCT) + 0.05 if sid == "trend_atr_daily"
                  else float(GH_SL_CAP_PCT) + 0.05 if sid in GH_LIVE_STRATEGIES else float(MAX_SL_DISTANCE_PCT))
    min_rr_need = (0.05 if sid in GH_LIVE_STRATEGIES
                   else 1.0 if sid in ("rel_strength", "tsmom_daily", "rs_intraday_50", "trend_atr_daily")
                   else float(MIN_RR_REAL))

    if sl_dist > max_sl_cap + 1e-6:
        max_frac = max_sl_cap / 100.0
        if d == "short":
            new_sl = fill * (1.0 + max_frac)
        else:
            new_sl = fill * (1.0 - max_frac)
        sl_dist = max_sl_cap
        info["clamped_sl"] = True
        fr = abs(ROUND_TRIP_FRICTION_PCT)
        need_tp = min_rr_need * (sl_dist + fr) + fr
        if tp_dist < need_tp:
            tp_dist = need_tp
            frac_tp = tp_dist / 100.0
            if d == "short":
                new_tp = fill * (1.0 - frac_tp)
            else:
                new_tp = fill * (1.0 + frac_tp)

    ok, reason = _passes_fee_filter(fill, new_sl, new_tp, strategy_id=sid or "trend")
    if not ok:
        info["ok"] = False
        info["invalid"] = True
        info["reason"] = f"fill_invalidated: {reason}"
        return new_sl, new_tp, info

    info["sl_dist_pct"] = round(sl_dist, 4)
    info["tp_dist_pct"] = round(abs(new_tp - fill) / fill * 100.0, 4)
    return float(new_sl), float(new_tp), info


def _match_history_row(
    rows: list,
    symbol_key: str,
    *,
    fill_entry: float | None = None,
    qty: float | None = None,
    opened_at: float | None = None,
    closed_after: float | None = None,
) -> dict | None:
    """V.2.10.56: Match دقیق‌تر رکورد CLOSED تاریخچه با ترکیب price/qty/time."""
    key_u = symbol_key.upper().replace("-SWAP-USDT", "").replace("USDT", "")
    candidates: list[tuple[float, dict]] = []
    now = time.time()
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "")
        sym_n = sym.upper().replace("-SWAP-USDT", "").replace("USDT", "")
        if key_u not in sym_n and sym_n not in key_u:
            continue
        st = str(r.get("status") or "").upper()
        if st and st not in ("CLOSED", "CLOSE", ""):
            continue
        score = 0.0
        try:
            open_px = float(r.get("openAvgPrice") or r.get("entryPrice") or 0)
        except (TypeError, ValueError):
            open_px = 0.0
        try:
            close_qty = abs(float(r.get("closeTotalQty") or r.get("maxPosition") or r.get("position") or 0))
        except (TypeError, ValueError):
            close_qty = 0.0
        # open time / close time (ms)
        try:
            ot = float(r.get("openTime") or 0) / 1000.0
        except (TypeError, ValueError):
            ot = 0.0
        try:
            ct = float(r.get("closeTime") or 0) / 1000.0
        except (TypeError, ValueError):
            ct = 0.0

        if fill_entry and open_px > 0:
            rel = abs(open_px - fill_entry) / max(fill_entry, 1e-12)
            if rel < 0.001:
                score += 50
            elif rel < 0.003:
                score += 30
            elif rel < 0.01:
                score += 10
            else:
                score -= 20
        if qty and close_qty > 0:
            qrel = abs(close_qty - qty) / max(qty, 1e-12)
            if qrel < 0.02:
                score += 30
            elif qrel < 0.08:
                score += 15
            else:
                score -= 10
        if opened_at and ot > 0:
            dt = abs(ot - opened_at)
            if dt < 30:
                score += 25
            elif dt < 120:
                score += 12
            elif dt < 600:
                score += 5
        if closed_after and ct > 0:
            if ct >= closed_after - 5:
                score += 15
            # خیلی قدیمی نسبت به close ما
            if ct < closed_after - 3600:
                score -= 30
        # تازگی close
        if ct > 0 and now - ct < 120:
            score += 10
        candidates.append((score, r))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best = candidates[0]
    if best_score < 20:
        # fallback: اولین CLOSED هم‌نماد اگر هیچ امتیاز معناداری نبود
        return best if best_score >= 0 else None
    return best


def _demo_symbol_wr(symbol: str, direction: str) -> tuple[float | None, int]:
    """WR دمو از کش signal_filters (اگر موجود)."""
    try:
        import signal_filters
        by_sym = signal_filters._stats_cache.get("by_symbol") or {}
        key = _norm_symbol(symbol)
        st = by_sym.get(key) or by_sym.get(symbol)
        if not st:
            return None, 0
        total = int(st.get("total") or 0)
        wr = st.get("win_rate")
        if wr is None:
            return None, total
        return float(wr), total
    except Exception:
        return None, 0


def _exchange_symbol_wr(symbol: str, direction: str | None = None) -> tuple[float | None, int]:
    """WR از تاریخچهٔ حافظه — در صورت امکان فقط همان جهت (V.2.10.58)."""
    key = _norm_symbol(symbol)
    dir_n = (direction or "").strip().lower() or None
    if dir_n in ("buy", "long"):
        dir_n = "long"
    elif dir_n in ("sell", "short"):
        dir_n = "short"
    wins = losses = 0
    for h in _history:
        sym = _norm_symbol(str(h.get("symbol") or "").replace("-SWAP-USDT", "").replace("USDT", ""))
        if sym != key and _norm_symbol(str(h.get("symbol") or "")) != key:
            continue
        if dir_n:
            hd = str(h.get("direction") or h.get("side") or "").strip().lower()
            if hd in ("buy", "long", "buy_open"):
                hd = "long"
            elif hd in ("sell", "short", "sell_open"):
                hd = "short"
            if hd and hd != dir_n:
                continue
        st = str(h.get("status") or "").lower()
        if st and st not in ("closed", "closed_external"):
            continue
        try:
            pnl = float(h.get("approx_pnl") if h.get("approx_pnl") is not None else h.get("pnl") or 0)
        except Exception:
            continue
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1
    total = wins + losses
    if total <= 0:
        return None, 0
    return 100.0 * wins / total, total


async def _exchange_symbol_wr_live(symbol: str, direction: str | None = None) -> tuple[float | None, int]:
    """WR زنده Toobit — ترجیح حافظه؛ فیلتر جهت وقتی ممکن باشد (V.2.10.58)."""
    key = _norm_symbol(symbol)
    dir_n = (direction or "").strip().lower() or None
    if dir_n in ("buy", "long"):
        dir_n = "long"
    elif dir_n in ("sell", "short"):
        dir_n = "short"
    mem_wr, mem_n = _exchange_symbol_wr(key, dir_n)
    if mem_n >= LIVE_WR_BLOCK_MIN_N and mem_wr is not None:
        return mem_wr, mem_n
    try:
        hist = await toobit_private.fetch_exchange_history(limit=40)
        items = ((hist or {}).get("positions_summary") or {}).get("items") or []
        wins = losses = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            sym = str(it.get("symbol") or "")
            nsym = _norm_symbol(sym.replace("-SWAP-USDT", "").replace("-USDT", ""))
            if nsym != key:
                continue
            if dir_n:
                side = str(it.get("side") or it.get("direction") or "").upper()
                is_long = side in ("LONG", "BUY")
                is_short = side in ("SHORT", "SELL")
                if dir_n == "long" and not is_long:
                    continue
                if dir_n == "short" and not is_short:
                    continue
            try:
                pnl = float(it.get("pnl") or 0)
            except Exception:
                continue
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
        total = wins + losses
        if total >= LIVE_WR_PROBATION_MIN_N:
            return 100.0 * wins / total, total
        if total > mem_n:
            return (100.0 * wins / total if total else None), total
    except Exception as e:
        logger.warning("live exchange WR failed %s: %s", key, e)
    return mem_wr, mem_n



def _trade_net_pnl_usdt(h: dict) -> float | None:
    """V.2.10.87 — فقط PnL دلاری خالص معامله؛ رد واحد اشتباه / پرت."""
    if not isinstance(h, dict):
        return None
    # اولویت: decision_net → realized → approx
    candidates: list[tuple[str, float]] = []
    for k in ("decision_net_pnl", "realized_pnl", "approx_pnl", "net_pnl", "pnl"):
        if h.get(k) is None:
            continue
        try:
            v = float(h.get(k))
        except (TypeError, ValueError):
            continue
        candidates.append((k, v))
    if not candidates:
        return None
    # اگر approx_pnl_pct هم‌اندازه با approx_pnl بود → احتمالاً درصد به‌جای USDT
    try:
        pct = h.get("approx_pnl_pct")
        if pct is not None:
            pct_f = float(pct)
            for k, v in candidates:
                if k in ("approx_pnl", "pnl") and abs(abs(v) - abs(pct_f)) < 1e-6 and abs(v) > 0.5:
                    # مقدار شبیه درصد است نه دلار اسکالپ
                    continue
                if k in ("approx_pnl", "pnl") and abs(v) > 3.0 and abs(pct_f) > 0.01 and abs(v / pct_f - 1.0) < 0.05:
                    continue
    except Exception:
        pass
    for k, v in candidates:
        # سقف منطقی برای یک اسکالپ با مارجین کوچک حساب ریل
        if abs(v) > 8.0:
            continue
        if abs(v) < 1e-12:
            continue
        return v
    return None


def _decisive_symbol_dir_stats(symbol: str, direction: str | None = None) -> dict:
    """V.2.10.87 — آمار قاطع نماد+جهت فقط با net USDT معتبر (|pnl|>=0.08 و <=8)."""
    key = _norm_symbol(symbol)
    dir_n = (direction or "").strip().lower() or None
    if dir_n in ("buy", "long", "buy_open"):
        dir_n = "long"
    elif dir_n in ("sell", "short", "sell_open"):
        dir_n = "short"
    wins: list[float] = []
    losses: list[float] = []
    skipped_bad = 0
    for h in list(_history or []):
        if not isinstance(h, dict):
            continue
        sym = _norm_symbol(str(h.get("symbol") or "").replace("-SWAP-USDT", "").replace("USDT", ""))
        if sym != key and _norm_symbol(str(h.get("symbol") or "")) != key:
            continue
        if dir_n:
            hd = str(h.get("direction") or h.get("side") or "").strip().lower()
            if hd in ("buy", "long", "buy_open"):
                hd = "long"
            elif hd in ("sell", "short", "sell_open"):
                hd = "short"
            if hd and hd != dir_n:
                continue
        st = str(h.get("status") or "").lower()
        if st and st not in ("closed", "closed_external", ""):
            continue
        pnl = _trade_net_pnl_usdt(h)
        if pnl is None:
            skipped_bad += 1
            continue
        if abs(pnl) < 0.08:
            continue  # scratch / noise — قاطع نیست
        if pnl > 0:
            wins.append(pnl)
        else:
            losses.append(pnl)
    n = len(wins) + len(losses)
    total = sum(wins) + sum(losses)
    wr = (100.0 * len(wins) / n) if n else None
    exp = (total / n) if n else None
    return {
        "symbol": key,
        "direction": dir_n or "any",
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": None if wr is None else round(wr, 1),
        "total_pnl": round(total, 4),
        "expectancy": None if exp is None else round(exp, 4),
        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "pnl_unit": "usdt_net",
        "skipped_invalid_pnl": skipped_bad,
    }


def _symbol_dir_policy_from_stats(st: dict) -> dict:
    """keep / probation / strict / block بر اساس n و WR و expectancy."""
    n = int(st.get("n") or 0)
    wr = st.get("wr")
    exp = st.get("expectancy")
    tier = "observe"
    size_mult = 1.0
    extra_conf = 0
    extra_rr = 0.0
    allow = True
    reason = "نمونه کم — مشاهده"
    if n >= LIVE_WR_BLOCK_MIN_N and wr is not None and wr <= 0:
        tier, allow, reason = "block", False, f"WR=0% n={n}"
    elif n >= LIVE_WR_BLOCK_MIN_N and wr is not None and wr < float(REAL_MIN_SYMBOL_WR or LIVE_WR_BLOCK_PCT):
        tier, allow, reason = "block", False, f"WR={wr}% n={n} < {REAL_MIN_SYMBOL_WR}"
    elif n >= 8 and exp is not None and exp < -0.12:
        tier, allow, reason = "block", False, f"expectancy={exp} n={n}"
    elif n >= 5 and exp is not None and exp < 0 and wr is not None and wr < 55:
        tier, size_mult = "strict", float(LIVE_WR_PROBATION_SIZE_MULT)
        extra_conf, extra_rr = 5, 0.10
        reason = f"strict WR={wr}% exp={exp} size={size_mult:.0%} conf+{extra_conf} rr+{extra_rr}"
    elif n >= LIVE_WR_PROBATION_MIN_N and wr is not None and wr < LIVE_WR_PROBATION_PCT:
        tier, size_mult = "probation", float(LIVE_WR_PROBATION_SIZE_MULT)
        extra_conf = 3
        reason = f"probation WR={wr}% n={n} size={size_mult:.0%} conf+{extra_conf}"
    elif n >= LIVE_WR_PROBATION_MIN_N and exp is not None and exp < 0:
        tier, size_mult = "probation", float(LIVE_WR_PROBATION_SIZE_MULT)
        extra_conf = 3
        reason = f"probation exp={exp} n={n} size={size_mult:.0%}"
    elif n >= 5 and wr is not None and wr >= 55 and (exp is None or exp >= 0):
        tier, reason = "keep", f"keep WR={wr}% exp={exp} n={n}"
    elif n >= 3 and wr is not None and wr >= 50 and (exp is None or exp >= 0):
        tier, reason = "keep", f"keep-early WR={wr}% n={n}"
    rank = {"keep": 0, "observe": 1, "probation": 2, "strict": 3, "block": 4}.get(tier, 9)
    return {
        "tier": tier,
        "tier_rank": rank,
        "allow": allow,
        "size_mult": size_mult,
        "extra_min_confluence": extra_conf,
        "extra_min_rr": extra_rr,
        "policy_reason": reason,
    }


def _build_symbol_direction_tiers() -> list[dict]:
    pairs: set[tuple[str, str]] = set()
    for h in list(_history or []):
        if not isinstance(h, dict):
            continue
        sym = _norm_symbol(str(h.get("symbol") or ""))
        if not sym:
            continue
        hd = str(h.get("direction") or h.get("side") or "").strip().lower()
        if hd in ("buy", "long", "buy_open"):
            hd = "long"
        elif hd in ("sell", "short", "sell_open"):
            hd = "short"
        else:
            continue
        pairs.add((sym, hd))
    rows = []
    for sym, d in sorted(pairs):
        st = _decisive_symbol_dir_stats(sym, d)
        if st["n"] < 2:
            continue
        pol = _symbol_dir_policy_from_stats(st)
        rows.append({**st, **pol})
    rows.sort(key=lambda x: (x.get("tier_rank", 9), -(x.get("n") or 0)))
    return rows


async def _live_wr_gate(symbol: str, direction: str) -> tuple[bool, str, float]:
    """V.2.10.82 — سیاست تطبیقی نماد+جهت: keep / probation / strict / block."""
    key = _norm_symbol(symbol)
    st = _decisive_symbol_dir_stats(key, direction)
    if st["n"] < LIVE_WR_PROBATION_MIN_N:
        real_wr, real_n = await _exchange_symbol_wr_live(key, direction)
        if real_n and real_n > st["n"]:
            st = {
                **st,
                "n": int(real_n),
                "wr": None if real_wr is None else round(float(real_wr), 1),
            }
    pol = _symbol_dir_policy_from_stats(st)
    try:
        _symbol_dir_policy_cache[key] = {
            "direction": (direction or "").lower(),
            **pol,
            "stats": st,
            "ts": time.time(),
        }
    except Exception:
        pass
    if not pol.get("allow", True):
        return False, (
            f"block {key}/{direction}: {pol.get('policy_reason')} "
            f"(جامعه آماری نماد+جهت)"
        ), 1.0
    sm = float(pol.get("size_mult") or 1.0)
    if sm < 0.999:
        return True, str(pol.get("policy_reason") or "probation"), sm
    if pol.get("tier") == "keep":
        return True, str(pol.get("policy_reason") or "keep"), 1.0
    return True, "ok", 1.0


def _record_attempt(symbol: str, ok: bool, reason: str, **extra: Any) -> None:
    key = _norm_symbol(symbol)
    _last_attempts[key] = {
        "symbol": key,
        "ts": time.time(),
        "ok": ok,
        "reason": reason,
        **extra,
    }



def _fetch_btc_regime_for_gate(diagnostics: dict | None = None) -> tuple[str | None, float | None, str | None]:
    """برچسب / conf / stack بیت‌کوین برای گیت‌ها و auto-pause."""
    btc_label = btc_conf = btc_stack = None
    if isinstance(diagnostics, dict):
        btc_label = diagnostics.get("btc_regime_label")
        btc_conf = diagnostics.get("btc_regime_confidence")
        btc_stack = diagnostics.get("btc_ema_stack_1h") or diagnostics.get("btc_stack")
    if not btc_label:
        try:
            from indicators import get_btc_regime_snapshot
            snap = get_btc_regime_snapshot() or {}
            btc_label = snap.get("label") or snap.get("regime_label")
            btc_conf = snap.get("confidence") if btc_conf is None else btc_conf
            btc_stack = snap.get("ema_stack_1h") or snap.get("stack") or btc_stack
        except Exception:
            pass
    try:
        bc = float(btc_conf) if btc_conf is not None else None
    except (TypeError, ValueError):
        bc = None
    stack = str(btc_stack).lower() if btc_stack else None
    label = str(btc_label).upper() if btc_label else None
    return label, bc, stack



def _symbol_adx_value(diagnostics: dict | None) -> float | None:
    if not isinstance(diagnostics, dict):
        return None
    try:
        v = diagnostics.get("adx_1h")
        if v is None:
            v = diagnostics.get("adx")
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _symbol_adx_strong(diagnostics: dict | None) -> bool:
    """V.2.10.65/66: ADX خود نماد ≥ ADX_STRONG_BYPASS_BTC"""
    adx = _symbol_adx_value(diagnostics)
    return adx is not None and adx >= float(ADX_STRONG_BYPASS_BTC)



def _build_entry_block_summary(
    *,
    pause: bool,
    pause_reason: str,
    news_active: bool,
    n_open: int,
    max_open: int,
) -> dict:
    """V.2.10.79 — چیپ‌های فشرده برای UI: ok/fail + یک خط خلاصه."""
    chips: list[dict] = []
    blockers: list[str] = []

    if not ENABLE_NEW_ENTRIES:
        chips.append({"ok": False, "id": "manual", "t": "ورود خاموش"})
        blockers.append("ورود از تنظیمات خاموش")
    elif pause:
        pr = (pause_reason or "pause").strip()
        short = pr
        if "قفل سراسری" in pr or "GLOBAL" in pr.upper() or "قفل‌SL" in pr:
            # تایمر باقی‌مانده را حفظ کن (مثلاً 574s)
            left = _global_sl_remaining()
            m = re.search(r"(\d+)\s*s", pr)
            if m and left <= 0:
                try:
                    left = int(m.group(1))
                except ValueError:
                    left = 0
            if left > 0:
                short = f"قفل‌SL {left}s"
            else:
                short = "قفل‌SL سراسری"
        elif "CHOP" in pr.upper():
            short = "روند: BTC=CHOP"   # V.2.20.1 — فقط استراتژی روند (که خودش کاغذی است)
        elif "WEAK" in pr.upper():
            short = "روند: BTC=WEAK"
        elif "خبر" in pr or "news" in pr.lower():
            short = "خبر"
        chips.append({"ok": False, "id": "pause", "t": short})
        blockers.append(short if "قفل‌SL" in short else pr)
    else:
        chips.append({"ok": True, "id": "pause", "t": "بدون‌pause"})

    if news_active:
        chips.append({"ok": False, "id": "news", "t": "خبر"})
        blockers.append("blackout خبر")
    else:
        chips.append({"ok": True, "id": "news", "t": "خبرOK"})

    if n_open >= max(1, int(max_open or 1)):
        chips.append({"ok": False, "id": "slots", "t": f"اسلات‌پر {n_open}/{max_open}"})
        blockers.append("اسلات پر")
    else:
        chips.append({"ok": True, "id": "slots", "t": f"اسلات {n_open}/{max_open}"})

    # V.2.11.0 — رانش BTC (از کش؛ بدون I/O)
    try:
        _dst = _BTC_DRIFT_CACHE.get("state") or {}
        if _dst:
            _dd = str(_dst.get("dir") or "none")
            chips.append({
                "ok": True, "id": "btc_drift",
                "t": {"up": "BTC↑ رنج‌شورت بسته", "down": "BTC↓ رنج‌لانگ بسته"}.get(_dd, "BTC→ بدون رانش"),
            })
    except Exception:
        pass

    # rejectهای اخیر ورود (نه بستن خارجی)
    near: list[dict] = []
    try:
        items = sorted(
            (_last_attempts or {}).values(),
            key=lambda x: float(x.get("ts") or 0),
            reverse=True,
        )[:12]
        for a in items:
            if a.get("ok"):
                continue
            reason = str(a.get("reason") or "")
            if reason.startswith("بسته شد") or "خارجی" in reason:
                continue
            sym = str(a.get("symbol") or "?")
            # V.2.11.6 — فقط متن اصلی رد (نه توضیحات «| diag | regime=… adx1h=…» یا یادداشت پاس دوم)
            core = reason.split(" | ")[0]
            rshort = core
            for needle, lab in (
                ("btc_drift", "BTC-drift"),
                ("pre_order", "pre-order"),
                ("entry_ioc_unfilled", "IOC-unfilled"),
                ("هم‌جهت", "same-dir"),
                ("خبری", "news"),
                ("news_blackout", "news"),
                ("R:R", "RR↓"),
                ("confluence", "score↓"),
                ("امتیاز", "score↓"),
                ("OVEREXT", "OVEREXT"),
                ("overextension", "OVEREXT"),
                ("تعقیب", "OVEREXT"),
                ("کول‌داون", "cooldown"),
                ("cooldown", "cooldown"),
                ("CHOP", "BTC-CHOP"),
                ("WEAK", "BTC-WEAK"),
                ("ADX", "ADX"),
                ("notional", "notional"),
                ("WR", "WR"),
                ("فاصله SL", "SL-band"),
                ("CI ", "CI"),
                ("ER ", "ER"),
                ("تریگر", "trigger"),
            ):
                if needle.lower() in core.lower() or needle in core:
                    rshort = lab
                    break
            else:
                rshort = core[:28]
            near.append({
                "symbol": sym,
                "score": a.get("score"),
                "t": rshort,
            })
            if len(near) >= 4:
                break
    except Exception:
        near = []

    for n in near[:3]:
        chips.append({
            "ok": False,
            "id": f"rej_{n['symbol']}",
            "t": f"{n['symbol']}:{n['t']}",
        })
        blockers.append(f"{n['symbol']} {n['t']}")

    if not blockers:
        line = f"آزاد · منتظر score≥{MIN_CONFLUENCE_REAL}"
    else:
        line = " · ".join(blockers[:4])

    _btc_pause_only = bool(pause) and (
        "CHOP" in str(pause_reason or "").upper() or "WEAK" in str(pause_reason or "").upper()
    ) and ("قفل" not in str(pause_reason or ""))
    _alt_live = (
        (ENABLE_RANGE_SCALP and not range_signal_only_effective()) or ENABLE_WEAK_TREND
    )
    slots_ok = n_open < max(1, int(max_open or 1))
    can_enter_trend = (not pause) and (not news_active) and ENABLE_NEW_ENTRIES and slots_ok
    can_enter_alt = (
        _btc_pause_only and _alt_live and (not news_active) and ENABLE_NEW_ENTRIES and slots_ok
    )
    if can_enter_alt and not can_enter_trend:
        chips.append({"ok": True, "id": "alt", "t": "range/weak باز"})
        if blockers:
            line = "pause روند · range/weak_trend باز است · " + line
        else:
            line = "pause روند · range/weak_trend باز است"

    # V.2.20.1 — pause شرط BTC فقط روی استراتژی روند است؛ استراتژی‌های روزانه و قدرت نسبی مسیر جدا دارند
    _indep = _independent_strategies_state()
    _n_ready = sum(1 for v in _indep.values() if v.get("can_trade_real"))
    chips.insert(1, {"ok": _n_ready > 0, "id": "indep",
                     "t": f"روزانه/قدرت نسبی: {_n_ready} آمادهٔ پول واقعی (pause شاملشان نیست)"})
    if pause and _btc_pause_only:
        line = (f"pause فقط روی استراتژی روند (آن هم در آزمون کاغذی است) · {_n_ready} استراتژی مستقل آمادهٔ پول واقعی · "
                + line)
    return {
        "chips": chips[:9],
        "line": line,
        "independent_strategies": _indep,
        "can_enter": bool(can_enter_trend or can_enter_alt or _n_ready > 0),
        "can_enter_trend": bool(can_enter_trend),
        "range_signal_only": bool(RANGE_SIGNAL_ONLY),
        "enable_range_scalp": bool(ENABLE_RANGE_SCALP),
        "enable_weak_trend": bool(ENABLE_WEAK_TREND),
        "min_confluence": MIN_CONFLUENCE_REAL,
        "min_rr": MIN_RR_REAL,
    }



def _independent_strategies_state() -> dict:
    """V.2.20.1 — استراتژی‌هایی که توقف خودکار BTC (CHOP/WEAK) شاملشان نیست: چه زمانی و با چه شرطی پول واقعی می‌گیرند."""
    out: dict = {}
    pol = (_MATRIX.get("policy") or {}) if isinstance(_MATRIX.get("policy"), dict) else {}
    for fam, d, when in (("trend_atr_daily", "long", "روزی یک بار ~۰۰:۰۷ UTC"),
                         ("tsmom_daily", "long", "روزی یک بار ~۰۰:۰۵ UTC"),
                         ("rs_intraday_50", "long", "هر ۴ ساعت"), ("rel_strength", "long", "هر ۴ ساعت")):
        cells = {k: (v or {}).get("status") for k, v in pol.items() if k.startswith(f"{fam}|{d}|")}
        on = any(v in ("on", "probe") for v in cells.values())
        why = None
        if fam in DAILY_FAMILIES:
            passes = bool(_daily_research(fam).get("passes"))
            ok = on and passes
            if not passes:
                why = "آزمون ۲ ساله قبول نشده"
        else:
            fst = _fwd_get(fam, d)
            ok = on and fst.get("mode") == "live"
            if fst.get("mode") != "live":
                pn = int((fst.get("paper") or {}).get("n") or 0)
                why = f"آزمون کاغذی رو به جلو ({pn}/{FWD_MICRO_MIN_N})"
        if not on:
            why = why or "خانهٔ جدول خاموش"
        out[f"{fam}:{d}"] = {"can_trade_real": bool(ok), "scan": when, "why_not": None if ok else why}
    return out


def _market_mode_for_entry(diagnostics: dict | None = None) -> str:
    """V.2.10.98 — trend | weak_trend_candidate | range_candidate | noise.
    BTC WEAK/CHOP is context, not an automatic rename of a healthy trend into range.
    """
    d = diagnostics if isinstance(diagnostics, dict) else {}
    explicit = str(d.get("strategy_id") or "")
    if explicit == "range_scalp":
        return "range_candidate"
    if explicit == "weak_trend":
        return "weak_trend_candidate"
    try:
        ci_v = d.get("choppiness_1h") or d.get("ci") or d.get("chop_index")
        er_v = d.get("efficiency_ratio_1h") or d.get("er")
        adx_v = d.get("adx_1h") or d.get("adx")
        ci_f = float(ci_v) if ci_v is not None else None
        er_f = float(er_v) if er_v is not None else None
        adx_f = float(adx_v) if adx_v is not None else None
    except (TypeError, ValueError):
        ci_f, er_f, adx_f = None, None, None
    sym = str(d.get("regime_label") or d.get("regime") or "").upper()
    lab, _bc, _stack = _fetch_btc_regime_for_gate(d if d else None)
    lab_u = str(lab or "").upper()
    healthy = (
        "TREND" in sym
        and er_f is not None and er_f >= 0.28
        and (ci_f is None or ci_f < 55)
        and (adx_f is None or adx_f >= float(WEAK_TREND_MIN_ADX))
    )
    if healthy and lab_u in ("CHOP", "WEAK"):
        return "weak_trend_candidate"
    if healthy:
        return "trend"
    if ci_f is not None and ci_f >= float(RANGE_CI_HARD_MAX) and (er_f is None or er_f < 0.12):
        return "noise"
    if er_f is not None and er_f < float(RANGE_ER_FLOOR) and (ci_f is None or ci_f >= 55):
        return "noise"
    looks_range = (
        (ci_f is not None and ci_f >= 52 and (er_f is None or er_f < 0.35))
        or (adx_f is not None and adx_f < 22 and ci_f is not None and ci_f >= 48 and (er_f is None or er_f < 0.40))
    )
    if looks_range:
        return "range_candidate"
    if lab_u in ("CHOP", "WEAK") and "TREND" not in sym:
        return "range_candidate"
    return "trend"


def _range_scalp_eligible(symbol: str, diagnostics: dict | None = None) -> tuple[bool, str]:
    """آیا مسیر range_scalp برای دور زدن pause/گیت BTC مجاز است؟"""
    if not ENABLE_RANGE_SCALP:
        return False, "range_scalp خاموش"
    mode = _market_mode_for_entry(diagnostics)
    if mode != "range_candidate":
        return False, f"مسیر range نیست ({mode})"
    lab, bc, _stack = _fetch_btc_regime_for_gate(diagnostics if isinstance(diagnostics, dict) else None)
    lab_u = str(lab or "").upper()
    if lab_u == "CHOP" and not RANGE_ALLOW_BTC_CHOP:
        return False, "range روی CHOP غیرفعال"
    if lab_u == "WEAK" and not RANGE_ALLOW_BTC_WEAK:
        return False, "range روی WEAK غیرفعال"
    # سقف فقط روی پوزیشن‌های خود range — trend را نمی‌شمارد
    try:
        n_range = sum(
            1 for m in _tracked.values()
            if m.get("status") == "open" and str(m.get("strategy_id") or "") == "range_scalp"
        )
        if n_range >= int(RANGE_MAX_OPEN_POSITIONS):
            return False, f"سقف range_scalp ({RANGE_MAX_OPEN_POSITIONS}) پر"
    except Exception:
        pass
    return True, "range_candidate"


def btc_auto_entry_pause_state(diagnostics: dict | None = None) -> tuple[bool, str]:
    """
    V.2.10.51 — آیا ورود جدید باید به‌خاطر رژیم BTC متوقف شود؟
    فقط وقتی AUTO_PAUSE_ENTRIES_ON_BTC_REGIME=true.
    اولویت پایین‌تر از enable_new_entries دستی.
    """
    if not AUTO_PAUSE_ENTRIES_ON_BTC_REGIME:
        return False, ""
    label, bc, stack = _fetch_btc_regime_for_gate(diagnostics)
    if not label:
        return False, ""
    conf_floor = float(AUTO_RESUME_MIN_BTC_CONF)
    if label == "CHOP":
        return True, f"توقف خودکار ورود — BTC=CHOP"
    if label == "WEAK" and bc is not None and bc < conf_floor:
        return True, f"توقف خودکار ورود — BTC=WEAK({bc:.0f}) < {conf_floor:.0f}"
    if AUTO_PAUSE_ON_BTC_BEAR_STACK and stack == "bear" and (bc is None or bc < conf_floor):
        return True, f"توقف خودکار ورود — BTC stack=bear conf={bc}"
    return False, ""



def _btc_regime_is_weak(diagnostics: dict | None = None) -> bool:
    """BTC در WEAK/CHOP یا conf پایین → بازار برای آلت پرریسک."""
    try:
        d = diagnostics if isinstance(diagnostics, dict) else {}
        btc = d.get("btc") if isinstance(d.get("btc"), dict) else d
        lab = str(
            btc.get("btc_regime_label")
            or btc.get("regime_label")
            or btc.get("regime")
            or ""
        ).upper()
        if "CHOP" in lab or "WEAK" in lab:
            return True
        try:
            bc = float(btc.get("btc_regime_confidence") or btc.get("regime_confidence") or 99)
            if bc < float(BTC_WEAK_MIN_CONF):
                return True
        except Exception:
            pass
        # اگر diagnostics خود نماد است، از btc_auto_entry_pause استفاده کن
        paused, reason = btc_auto_entry_pause_state(d if d else None)
        if paused and ("WEAK" in (reason or "").upper() or "CHOP" in (reason or "").upper()):
            return True
    except Exception:
        pass
    return False


def _effective_max_same_direction(diagnostics: dict | None = None) -> int:
    """V.2.10.84: در BTC ضعیف سقف هم‌جهت = ۱."""
    try:
        if _btc_regime_is_weak(diagnostics):
            return int(WEAK_BTC_MAX_SAME_DIRECTION)
    except Exception:
        pass
    return int(MAX_SAME_DIRECTION_POSITIONS)


def _same_dir_underwater(direction: str, rows: list) -> tuple[bool, str]:
    """اگر پوزیشن هم‌جهت باز با ضرر شناور باشد → بلوک ورود هم‌جهت."""
    if not UNDERWATER_BLOCK_SAME_DIR:
        return False, ""
    direction = str(direction or "").lower()
    # tracked
    for key, tr in list(_tracked.items()):
        if tr.get("status") != "open":
            continue
        if str(tr.get("direction") or "").lower() != direction:
            continue
        try:
            pct = float(tr.get("unrealized_pct") or 0)
        except Exception:
            pct = 0.0
        if pct < -abs(UNDERWATER_MIN_LOSS_PCT):
            return True, (
                f"هم‌جهت {direction} روی {key} در ضرر شناور ({pct:.2f}%) — "
                f"ورود جدید تا برگشت نزدیک صفر ممنوع"
            )
        try:
            u = float(tr.get("unrealized_usdt") or 0)
            if u < -abs(float(UNDERWATER_MIN_LOSS_USDT)):
                return True, (
                    f"هم‌جهت {direction} روی {key} ضرر دلاری ({u:.3f}$) — "
                    f"ورود جدید ممنوع"
                )
        except Exception:
            pass
    # exchange rows (profitRate / unrealizedPnL)
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        try:
            qty = toobit_private.parse_position_qty(r)
        except Exception:
            qty = 0
        if qty <= 0:
            continue
        try:
            rdir = toobit_private.parse_position_side(r)
        except Exception:
            rdir = ""
        if str(rdir).lower() != direction:
            continue
        sym = _norm_symbol(str(r.get("symbol") or ""))
        # prefer tracked already checked
        if sym in _tracked and _tracked[sym].get("status") == "open":
            continue
        try:
            pr = float(r.get("profitRate") or r.get("unrealizedPnl") or r.get("unrealizedPnL") or 0)
            # profitRate often fraction or percent
            if abs(pr) < 1.5 and pr < -abs(UNDERWATER_MIN_LOSS_PCT) / 100.0:
                return True, f"هم‌جهت {direction} روی صرافی ({sym}) در ضرر — ورود ممنوع"
            if pr <= -abs(UNDERWATER_MIN_LOSS_PCT):
                return True, f"هم‌جهت {direction} روی صرافی ({sym}) ضرر ({pr}) — ورود ممنوع"
        except Exception:
            pass
    return False, ""



async def _entry_anti_noise_check(symbol: str, direction: str) -> tuple[bool, str]:
    """V.2.10.91/92 — نویز کندل / تأیید ۲ کندل / انتقال روند نسبت به EMA20 (۵m).

    V.2.10.92:
    - فقط کندل‌های بسته‌شده (کندل در حال تشکیل حذف می‌شود)
    - خطای API / داده کم → fail-closed (ورود رد) تا اسکالپ روی نویز باز نشود
    """
    need = (
        ENABLE_ENTRY_CANDLE_CONFIRM
        or ENABLE_CANDLE_NOISE_FILTER
        or ENABLE_TREND_TRANSITION_GUARD
    )
    if not need:
        return True, ""
    d = (direction or "").strip().lower()
    if d in ("buy", "buy_open"):
        d = "long"
    elif d in ("sell", "sell_open"):
        d = "short"
    if d not in ("long", "short"):
        return True, ""

    def _unavailable(why: str) -> tuple[bool, str]:
        if ANTI_NOISE_FAIL_CLOSED:
            return False, f"anti-noise داده ناکافی ({why}) — ورود رد"
        return True, ""

    try:
        raw = await toobit_market.get_klines(symbol, "5m", limit=40)
    except Exception as e:
        logger.debug("anti-noise klines failed %s: %s", symbol, e)
        return _unavailable("klines")

    rows: list[tuple[float | None, float, float, float, float]] = []
    try:
        data = raw
        # V.2.10.94 — پشتیبانی DataFrame (خروجی واقعی toobit_market.get_klines)
        try:
            import pandas as _pd
            if isinstance(raw, _pd.DataFrame):
                data = raw.to_dict(orient="records")
        except Exception:
            pass
        if hasattr(raw, "to_dict") and not isinstance(raw, (list, dict, tuple)):
            try:
                data = raw.to_dict(orient="records")  # type: ignore
            except Exception:
                pass
        if isinstance(raw, dict):
            data = raw.get("data") or raw.get("klines") or raw.get("candles") or []
        if data is None:
            data = []
        # DataFrame truth-value: هرگز `data or []` روی DataFrame نزن
        if not isinstance(data, (list, tuple)):
            try:
                data = list(data)
            except Exception:
                return _unavailable("parse")
        for it in data:
            ts = None
            if isinstance(it, (list, tuple)) and len(it) >= 5:
                try:
                    ts = float(it[0])
                except (TypeError, ValueError):
                    ts = None
                o, h, l, c = float(it[1]), float(it[2]), float(it[3]), float(it[4])
            elif isinstance(it, dict):
                raw_ts = it.get("openTime") or it.get("t") or it.get("time") or it.get("ts")
                try:
                    ts = float(raw_ts) if raw_ts is not None else None
                except (TypeError, ValueError):
                    ts = None
                o = float(it.get("open") or it.get("o") or 0)
                h = float(it.get("high") or it.get("h") or 0)
                l = float(it.get("low") or it.get("l") or 0)
                c = float(it.get("close") or it.get("c") or 0)
            else:
                continue
            if o > 0 and h > 0 and l > 0 and c > 0:
                rows.append((ts, o, h, l, c))
    except Exception as e:
        logger.debug("anti-noise parse failed %s: %s", symbol, e)
        return _unavailable("parse")

    if len(rows) < 21:
        return _unavailable(f"bars={len(rows)}")

    interval_ms = 5 * 60 * 1000
    last_ts = rows[-1][0]
    drop_last = True
    if last_ts is not None:
        ts_ms = last_ts if last_ts > 10_000_000_000 else last_ts * 1000.0
        age = (time.time() * 1000.0) - ts_ms
        drop_last = age < (interval_ms - 10_000)
    if drop_last:
        rows = rows[:-1]
    if len(rows) < 20:
        return _unavailable("closed-bars")

    rows = [(o, h, l, c) for _ts, o, h, l, c in rows]

    # ATR(14) ساده از True Range
    trs: list[float] = []
    for i in range(1, len(rows)):
        o, h, l, c = rows[i]
        _po, _ph, _pl, pc = rows[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    atr = sum(trs[-14:]) / 14.0 if len(trs) >= 14 else (sum(trs) / len(trs) if trs else 0.0)
    if atr <= 0:
        return _unavailable("atr")

    o, h, l, c = rows[-1]
    rng = h - l
    if rng <= 0:
        rng = 1e-12

    # --- Candle noise: range vs ATR ---
    if ENABLE_CANDLE_NOISE_FILTER:
        if rng > float(CANDLE_NOISE_MAX_ATR) * atr:
            return False, (
                f"کندل نویزی/انفجاری (range={rng/atr:.2f}×ATR ≥ {CANDLE_NOISE_MAX_ATR}) — صبر"
            )
        # wick خلاف جهت
        upper = h - max(o, c)
        lower = min(o, c) - l
        if d == "long":
            wick_ratio = upper / rng
            if wick_ratio >= float(CANDLE_NOISE_MAX_WICK):
                return False, (
                    f"سایه بالای نویزی ({wick_ratio*100:.0f}%≥{CANDLE_NOISE_MAX_WICK*100:.0f}%) — احتمال رد حرکت long"
                )
        else:
            wick_ratio = lower / rng
            if wick_ratio >= float(CANDLE_NOISE_MAX_WICK):
                return False, (
                    f"سایه پایین نویزی ({wick_ratio*100:.0f}%≥{CANDLE_NOISE_MAX_WICK*100:.0f}%) — احتمال رد حرکت short"
                )

    # --- 2-candle confirmation (only closed 5m bars) ---
    if ENABLE_ENTRY_CANDLE_CONFIRM:
        n = max(2, int(ENTRY_CONFIRM_CANDLES))
        use = rows[-n:]
        ok_bars = 0
        for bo, bh, bl, bc in use:
            if d == "long" and bc >= bo:
                ok_bars += 1
            elif d == "short" and bc <= bo:
                ok_bars += 1
        if ok_bars < n:
            return False, (
                f"تأیید {n} کندل ۵m ناقص ({ok_bars}/{n} هم‌جهت {d}) — صبر برای تثبیت"
            )

    # --- Trend transition: price vs EMA20 on 5m ---
    if ENABLE_TREND_TRANSITION_GUARD:
        closes = [r[3] for r in rows]
        # EMA20
        k = 2 / (20 + 1)
        ema = closes[0]
        for px in closes[1:]:
            ema = px * k + ema * (1 - k)
        last = closes[-1]
        buf = float(TRANSITION_EMA_BUFFER_PCT) / 100.0
        # شیب EMA: مقایسه با ۵ کندل قبل
        ema_series = []
        e = closes[0]
        for px in closes:
            e = px * k + e * (1 - k)
            ema_series.append(e)
        slope = ema_series[-1] - ema_series[-6] if len(ema_series) >= 6 else 0.0
        if d == "long":
            if last < ema * (1 - buf):
                return False, (
                    f"انتقال روند: قیمت زیر EMA20 ({last:.6g}<{ema:.6g}) — long ممنوع"
                )
            if slope < 0 and last < ema * (1 + buf):
                return False, (
                    f"انتقال روند: شیب EMA20 منفی و قیمت نزدیک/زیر میانگین — long محتاط/رد"
                )
        else:
            if last > ema * (1 + buf):
                return False, (
                    f"انتقال روند: قیمت بالای EMA20 ({last:.6g}>{ema:.6g}) — short ممنوع"
                )
            if slope > 0 and last > ema * (1 - buf):
                return False, (
                    f"انتقال روند: شیب EMA20 مثبت و قیمت نزدیک/بالای میانگین — short محتاط/رد"
                )

    return True, ""


async def can_open_real_trade(symbol: str, direction: str, entry: float,
                             stop_loss: float, target: float,
                             confluence_score: float,
                             diagnostics: dict | None = None,
                             _skip_rr: bool = False,
                             _skip_underwater: bool = False,
                             _skip_samedir_cap: bool = False,
                             _skip_overext: bool = False,
                             _probe: bool = False) -> tuple[bool, str]:
    try:
        apply_runtime_settings()
    except Exception:
        pass
    key = _norm_symbol(symbol)
    if not REAL_TRADING_ENABLED:
        return False, "REAL_TRADING_ENABLED خاموش است"
    if not ENABLE_NEW_ENTRIES:
        return False, "ورود جدید از تنظیمات متوقف شده (enable_new_entries=false)"
    # V.2.10.68 — blackout خبر high-impact (بر ADX قوی هم اولویت دارد)
    # V.2.10.74 — reason ساخت‌یافته برای last_attempts (news_blackout_reject)
    try:
        from news_blackout import news_blackout_state
        _nb = news_blackout_state()
        if _nb.get("active"):
            _ev = _nb.get("event_title") or _nb.get("event") or ""
            _mins = _nb.get("minutes_to_event")
            _parts = ["news_blackout_reject"]
            if _ev:
                _parts.append(str(_ev))
            if _mins is not None:
                try:
                    _parts.append(f"{int(_mins)}m_to_event")
                except Exception:
                    pass
            _msg = " | ".join(_parts)
            if _nb.get("reason"):
                _msg = f"{_msg} — {_nb.get('reason')}"
            return False, _msg
    except Exception as _nbe:
        logger.debug("news_blackout check: %s", _nbe)
    _explicit = ""
    if isinstance(diagnostics, dict):
        _explicit = str(diagnostics.get("strategy_id") or "")
    _ap, _ap_reason = btc_auto_entry_pause_state(diagnostics if isinstance(diagnostics, dict) else None)
    # V.2.11.0 — رانش کوتاه‌مدت BTC (کش ۶۰ث؛ خطا → none)
    try:
        _drift = await _btc_drift_state()
    except Exception:
        _drift = {"dir": "none"}
    _drift_follow = False
    if _explicit in GH_LIVE_STRATEGIES:   # V.2.22.1 — استراتژی‌های گیت‌هاب
        return await _can_open_gh(symbol, direction, entry, stop_loss, target, _explicit)
    if _explicit in ("rel_strength", "rs_intraday_50") and not LEGACY_LIVE_ENABLED:   # V.2.35.1 — پیشنهاد منتقد
        return False, "موتور قدیمی rel_strength/rs_intraday خاموش"
    if _explicit in ("rel_strength", "tsmom_daily", "rs_intraday_50", "trend_atr_daily"):   # V.2.15.0/2.17.0/2.18.1/2.20.0
        return await _can_open_rel_strength(symbol, direction, entry, stop_loss, target, confluence_score,
                                            diagnostics if isinstance(diagnostics, dict) else None, _probe,
                                            family=_explicit)
    if not LEGACY_LIVE_ENABLED:   # V.2.35.0 — روند/رنج/weak_trend (watchlist) دیگر با پول واقعی معامله نمی‌کند
        return False, "موتور قدیمی روند/رنج خاموش — فقط استراتژی‌های GH و روزانه"
    _strategy_id = "trend"
    if _explicit in ("range_scalp", "weak_trend", "trend"):
        _strategy_id = _explicit
    elif _ap and BTC_DRIFT_TREND_FOLLOW and _with_drift(direction, _drift) and _drift_follow_ok(
        diagnostics if isinstance(diagnostics, dict) else None
    )[0] and ENABLE_WEAK_TREND:
        # V.2.11.0: سیگنال روندِ هم‌جهت رانش تأییدشدهٔ BTC → weak_trend (سایز کمتر، بقیهٔ گیت‌ها پابرجا)
        _strategy_id = "weak_trend"
        _drift_follow = True
    elif _ap:
        _rs_ok, _ = _range_scalp_eligible(symbol, diagnostics if isinstance(diagnostics, dict) else None)
        if _rs_ok:
            _strategy_id = "range_scalp"
        elif _market_mode_for_entry(diagnostics if isinstance(diagnostics, dict) else None) == "weak_trend_candidate" and ENABLE_WEAK_TREND:
            _strategy_id = "weak_trend"
    else:
        mode = _market_mode_for_entry(diagnostics if isinstance(diagnostics, dict) else None)
        if mode == "range_candidate":
            _rs_ok2, _ = _range_scalp_eligible(symbol, diagnostics if isinstance(diagnostics, dict) else None)
            if _rs_ok2:
                _strategy_id = "range_scalp"
        elif mode == "weak_trend_candidate" and ENABLE_WEAK_TREND:
            _strategy_id = "weak_trend"
    if _strategy_id == "range_scalp" and range_signal_only_effective():
        return False, "range_signal_only — سیگنال رنج ثبت می‌شود، سفارش زنده خاموش است"

    if _ap:
        _ap_is_chop = "CHOP" in str(_ap_reason or "").upper()
        if _strategy_id == "range_scalp":
            pass
        elif _strategy_id == "weak_trend" and ENABLE_WEAK_TREND:
            pass
        elif (
            ENABLE_STRONG_ADX_BYPASS_BTC_PAUSE
            and _symbol_adx_strong(diagnostics if isinstance(diagnostics, dict) else None)
            and not (_ap_is_chop and not ENABLE_ADX_BYPASS_BTC_CHOP)
        ):
            pass
        else:
            return False, _ap_reason
    if not toobit_private.keys_configured():
        return False, "کلید Toobit تنظیم نشده"
    _need_conf = int(MIN_CONFLUENCE_REAL)
    if _strategy_id == "range_scalp":
        _need_conf = int(RANGE_MIN_CONFLUENCE)
    elif _strategy_id == "weak_trend":
        _need_conf = min(int(MIN_CONFLUENCE_REAL), int(WEAK_TREND_MIN_CONFLUENCE))
    try:
        _pc = _symbol_dir_policy_cache.get(_norm_symbol(symbol)) or {}
        _dir_ok = str(_pc.get("direction") or "").lower() in ("", str(direction or "").lower())
        if _dir_ok and _strategy_id == "trend":
            _need_conf += int(_pc.get("extra_min_confluence") or 0)
    except Exception:
        pass
    if confluence_score < _need_conf:
        extra = ""
        if _need_conf > MIN_CONFLUENCE_REAL and _strategy_id != "range_scalp":
            extra = f" (پایه {MIN_CONFLUENCE_REAL}+سخت‌گیری نماد)"
        elif _strategy_id == "range_scalp":
            extra = " (range_scalp)"
        return False, f"امتیاز {confluence_score} < {_need_conf}{extra}"
    if daily_loss_breached():
        return False, "سقف ضرر روزانه پر شده"

    # پوزیشن ریل همین نماد از قبل باز است
    meta = _tracked.get(key)
    if meta and meta.get("status") == "open":
        return False, "پوزیشن ریل همین نماد باز است"

    # کول‌داون بعد از رد اخیر (جز وقتی دلیل فقط «باز است»)
    prev = _last_attempts.get(key)
    if prev and not prev.get("ok"):
        age = time.time() - float(prev.get("ts") or 0)
        prev_reason = str(prev.get("reason") or "")
        if "باز است" in prev_reason:
            pass
        elif _is_soft_market_reject(prev_reason):
            # V.2.10.95: رد CHOP/WEAK/ADX/anti-noise → فقط ۹۰ثانیه، نه ۱۲ دقیقه
            soft_cd = 90
            if age < soft_cd:
                left = int(soft_cd - age)
                return False, f"کول‌داون کوتاه رژیم/تأیید ({left}s باقی) — قبلی: {prev_reason[:80]}"
        elif age < SYMBOL_COOLDOWN_SECONDS:
            left = int(SYMBOL_COOLDOWN_SECONDS - age)
            return False, f"کول‌داون نماد ({left}s باقی) — قبلی: {prev_reason}"

    
    # V.2.10.15/16: کول‌داون پایدار پس از بستن (دیسک)
    
    # V.2.10.17: قفل سراسری بعد از چند SL پشت‌سرهم
    gleft = _global_sl_remaining()
    if gleft > 0:
        return False, f"قفل سراسری پس از چند SL ({gleft}s باقی)"

    # V.2.10.17: قفل کوتاه‌مدت نماد کم‌سود
    lleft = _low_profit_remaining(key)
    if lleft > 0:
        return False, f"قفل کم‌سود نماد ({lleft}s باقی)"

    # V.2.10.47: قفل نماد بعد از ۲× SL
    sleft = _symbol_sl_lock_remaining(key)
    if sleft > 0:
        return False, f"قفل نماد پس از چند SL ({sleft}s باقی)"

    left_close = _post_close_remaining(key)
    if left_close > 0:
        kind = (_close_cooldown_meta.get(key) or {}).get("kind") or "close"
        label = {"profit": "برد", "sl": "SL", "negative": "منفی"}.get(str(kind), "بستن")
        return False, f"کول‌داون پس از {label} ({left_close}s باقی)"

    # V.2.10.59: هیسترزیس نرم بعد از برد (افت ER/ADX نسبت به baseline برد)
    if isinstance(diagnostics, dict):
        cur_er = diagnostics.get("efficiency_ratio_1h") or diagnostics.get("er")
        cur_adx = diagnostics.get("adx_1h") or diagnostics.get("adx")
        try:
            cur_er_f = float(cur_er) if cur_er is not None else None
        except (TypeError, ValueError):
            cur_er_f = None
        try:
            cur_adx_f = float(cur_adx) if cur_adx is not None else None
        except (TypeError, ValueError):
            cur_adx_f = None
        ok_h, why_h = _check_post_profit_hysteresis(key, cur_er_f, cur_adx_f)
        if not ok_h:
            return False, why_h

    # V.2.10.40: سقف پوزیشن روی equity نه available
    bal_preview = await _equity_balance()
    max_pos = _effective_max_positions(bal_preview)
    n_open, rows = await _open_positions_count()
    if rows is None:
        n_open = 99  # API error → block new entry this cycle
        rows = []
    if n_open >= max_pos:
        return False, f"حداکثر {max_pos} پوزیشن باز مجاز است (الان {n_open}، موجودی {bal_preview:.2f})"
    for r in rows:
        if not isinstance(r, dict):
            continue
        if _norm_symbol(str(r.get("symbol") or "")) == key and toobit_private.parse_position_qty(r) > 0:
            return False, "روی صرافی برای این نماد پوزیشن باز است"

    # V.2.10.14 + V.2.10.84: سقف هم‌جهت (در BTC ضعیف = ۱) + بلاک underwater
    _uw, _uw_why = _same_dir_underwater(direction, rows)
    if _uw and not _skip_underwater:
        # V.2.11.6 — پاس دوم بدون این گیت؛ اگر بقیه رد شوند ⇒ کاغذی «same_dir_underwater»
        if PAPER_TRACK_UNDERWATER_REJECTS and not _skip_rr and not _probe:
            _uw_why = await _paper_rr_probe(
                symbol, direction, entry, stop_loss, target, confluence_score, diagnostics, str(_uw_why),
                _strategy_id, skip="underwater", label="same_dir_underwater",
                only_note="فقط قانون هم‌جهتِ در ضرر مانع بود", after_note="بدون قانون هم‌جهت هم رد",
            )
        return False, _uw_why

    same_dir = 0
    for tr in _tracked.values():
        if tr.get("status") == "open" and tr.get("direction") == direction:
            same_dir += 1
    for r in rows:
        if not isinstance(r, dict):
            continue
        if toobit_private.parse_position_qty(r) <= 0:
            continue
        rdir = toobit_private.parse_position_side(r)
        if rdir == direction:
            rkey = _norm_symbol(str(r.get("symbol") or ""))
            if rkey in _tracked and _tracked[rkey].get("status") == "open":
                continue
            same_dir += 1
    _max_sd = _effective_max_same_direction(diagnostics if isinstance(diagnostics, dict) else None)
    if _with_drift(direction, _drift):
        # V.2.11.0: جهتِ هم‌راستا با رانش BTC تا سقف عادی هم‌جهت (پیش‌فرض ۲) مجاز است
        _max_sd = max(_max_sd, min(int(BTC_DRIFT_SAME_DIR_CAP), int(MAX_SAME_DIRECTION_POSITIONS)))
    _weak_cap_only = _max_sd < int(MAX_SAME_DIRECTION_POSITIONS) and same_dir < int(MAX_SAME_DIRECTION_POSITIONS)
    if same_dir >= _max_sd and not (_skip_samedir_cap and _weak_cap_only):
        _weak_note = " (BTC ضعیف→سقف۱)" if _max_sd < MAX_SAME_DIRECTION_POSITIONS else ""
        _cap_why = f"سقف پوزیشن هم‌جهت ({direction}): {same_dir}/{_max_sd}{_weak_note}"
        # V.2.11.10 — فقط سقفِ کاهش‌یافتهٔ «BTC ضعیف» مانع بود؟ ⇒ پاس دوم بدون آن ⇒ کاغذی «same_dir_cap»
        if _weak_cap_only and not _probe and PAPER_TRACK_SAMEDIR_CAP_REJECTS:
            _cap_why = await _paper_rr_probe(
                symbol, direction, entry, stop_loss, target, confluence_score, diagnostics, _cap_why,
                _strategy_id, skip="samedir", label="same_dir_cap",
                only_note="فقط سقف هم‌جهتِ BTC ضعیف مانع بود", after_note="بدون این سقف هم رد",
            )
        return False, _cap_why

    ok, reason = _passes_fee_filter(entry, stop_loss, target, strategy_id=_strategy_id)
    if not ok:
        _rr_only = "R:R خالص ضعیف" in str(reason)
        if _skip_rr and _rr_only:
            pass  # V.2.11.4 پاس دوم: فقط R:R نادیده گرفته می‌شود تا بقیهٔ گیت‌ها سنجیده شوند
        else:
            if (_rr_only and not _skip_rr and not _skip_underwater and not _probe and PAPER_TRACK_RR_REJECTS
                    and _strategy_id in ("trend", "weak_trend")):
                reason = await _paper_rr_probe(
                    symbol, direction, entry, stop_loss, target, confluence_score,
                    diagnostics, str(reason), _strategy_id,
                )
            # V.2.11.10 — فقط «SL کوچک‌تر از حداقل» ⇒ همان سیگنال با SL بازشده و TP مجاز، پاس دوم ⇒ کاغذی «sl_widen»
            _slmin_only = ("فاصله SL" in str(reason) and "کمتر از حداقل" in str(reason))
            if (_slmin_only and not _probe and PAPER_TRACK_SLMIN_REJECTS
                    and _strategy_id in ("trend", "weak_trend")):
                try:
                    _nsl, _ntp, _wi = _widen_geometry(direction, float(entry), float(stop_loss), float(target))
                    reason = await _paper_rr_probe(
                        symbol, direction, entry, _nsl, _ntp, confluence_score, diagnostics, str(reason),
                        _strategy_id, skip="slmin", label="sl_widen",
                        only_note=f"فقط حداقل SL مانع بود (SL→{_wi['sl_pct']}٪، TP→{_wi['tp_pct']}٪)",
                        after_note="با SL بازشده هم رد",
                    )
                except Exception as _we:
                    logger.debug("sl widen probe failed %s: %s", symbol, _we)
            return False, reason

    # V.2.10.82 — نماد/جهت ضعیف: RR خالص سخت‌تر
    try:
        _pc = _symbol_dir_policy_cache.get(_norm_symbol(symbol)) or {}
        _ex_rr = float(_pc.get("extra_min_rr") or 0)
        if _ex_rr > 0 and entry and stop_loss and target and _strategy_id == "trend":
            fr = float(ROUND_TRIP_FRICTION_PCT if "ROUND_TRIP_FRICTION_PCT" in dir() else 0.18)
            try:
                fr = float(ROUND_TRIP_FRICTION_PCT)
            except Exception:
                fr = 0.18
            sl_d = abs(float(entry) - float(stop_loss)) / float(entry) * 100.0
            tp_d = abs(float(target) - float(entry)) / float(entry) * 100.0
            net_tp = max(0.0, tp_d - fr)
            net_sl = sl_d + fr
            net_rr = (net_tp / net_sl) if net_sl > 0 else 0.0
            need = float(MIN_RR_REAL) + _ex_rr
            if net_rr < need:
                return False, (
                    f"R:R سخت‌گیری نماد ({net_rr:.2f} < {need:.2f}) "
                    f"— tier={_pc.get('tier')} {str(_pc.get('policy_reason') or '')[:40]}"
                )
    except Exception:
        pass

    # V.2.10.75 — ضد تعقیب: اگر ورود از نظر ATR بیش‌ازحد کشیده شده، رد کن
    # (کاهش ورودهایی که بلافاصله خلاف جهت می‌روند)
    if _strategy_id != "range_scalp" and isinstance(diagnostics, dict):
        try:
            ox = diagnostics.get("overextension_atr")
            if ox is not None and float(ox) >= 1.25 and not _skip_overext:
                _ox_why = f"تعقیب افراطی (overextension_atr={float(ox):.2f} ≥ 1.25) — صبر برای پولبک"
                # V.2.11.11 — فقط همین مانع؟ ⇒ پاس دوم بدون آن ⇒ کاغذی (به تفکیک شدت روند)
                if not _probe and PAPER_TRACK_OVEREXT_REJECTS and _strategy_id in ("trend", "weak_trend"):
                    _ox_lab, _ox_info = _overext_label(diagnostics)
                    _ox_why = await _paper_rr_probe(
                        symbol, direction, entry, stop_loss, target, confluence_score, diagnostics, _ox_why,
                        _strategy_id, skip="overext", label=_ox_lab,
                        only_note=f"فقط تعقیب افراطی مانع بود ({'روند خیلی قوی' if _ox_lab == 'overext_strong' else 'روند عادی'})",
                        after_note="بدون فیلتر تعقیب هم رد", extra_info=_ox_info,
                    )
                return False, _ox_why
        except (TypeError, ValueError):
            pass

    if _strategy_id != "range_scalp" and isinstance(diagnostics, dict):
        bonus = diagnostics.get("entry_triggered_bonus")
        if bonus is not None and int(bonus) <= 0:
            return False, "تریگر ورود ۵m فعال نیست"
        if ENABLE_REAL_M5_CLOSED_TRIGGER:
            trig = str(diagnostics.get("entry_trigger_type") or "")
            if trig == "m15_bias":
                return False, "تریگر فقط ۱۵m بدون تثبیت ۵m بسته‌شده — ورود ریل رد"
        if ENABLE_CHOP_FILTER_REAL or ENABLE_REGIME_ALIGN_REAL:
            if _strategy_id == "range_scalp":
                adx_15 = adx_30 = None
            else:
                adx_15 = diagnostics.get("adx_15m")
                adx_30 = diagnostics.get("adx_30m")
            try:
                a15 = float(adx_15) if adx_15 is not None else None
                a30 = float(adx_30) if adx_30 is not None else None
            except (TypeError, ValueError):
                a15, a30 = None, None

            # 1) چاپ: هر دو ADX پایین
            if ENABLE_CHOP_FILTER_REAL and a15 is not None and a30 is not None:
                if a15 < CHOP_ADX_THRESHOLD and a30 < CHOP_ADX_THRESHOLD:
                    return False, (
                        f"بازار چاپی/بی‌روند (ADX15={a15:.0f} ADX30={a30:.0f} "
                        f"< {CHOP_ADX_THRESHOLD:.0f}) — ریل رد شد"
                    )

            if ENABLE_REGIME_ALIGN_REAL:
                # 2) حداقل قدرت روند در یکی از TFها
                if a15 is not None and a30 is not None:
                    mx = max(a15, a30)
                    if mx < REGIME_MIN_ADX:
                        return False, (
                            f"قدرت رژیم ضعیف (max ADX15/30={mx:.0f} < {REGIME_MIN_ADX:.0f}) — ریل رد شد"
                        )

                # 3) هم‌جهتی با HTF خود نماد (h4/h1)
                if REGIME_REQUIRE_SYMBOL_HTF:
                    h4t = diagnostics.get("h4_trend") or diagnostics.get("h4_bias")
                    h1t = diagnostics.get("h1_trend") or diagnostics.get("h1_bias")
                    for label, val in (("H4", h4t), ("H1", h1t)):
                        if val in ("long", "short") and val != direction:
                            return False, (
                                f"خلاف رژیم نماد ({label}={val} ≠ {direction}) — ریل رد شد"
                            )

                # 4) هم‌جهتی با رژیم BTC وقتی هر دو HTF بیت‌کوین یک‌جهت‌اند
                if REGIME_REQUIRE_BTC_ALIGN:
                    btc_reg = str(diagnostics.get("btc_regime") or "")
                    if "/" in btc_reg:
                        parts = [p.strip() for p in btc_reg.split("/")]
                        if (
                            len(parts) >= 2
                            and parts[0] in ("long", "short")
                            and parts[0] == parts[1]
                            and parts[0] != direction
                        ):
                            return False, (
                                f"خلاف رژیم BTC ({btc_reg} ≠ {direction}) — ریل رد شد"
                            )


    # V.2.10.33: رد ریل وقتی ER نویزی است (روند برچسب‌خورده ولی حرکت بی‌کیفیت)
    # V.2.10.48: گیت نرم رژیم BTC — در چاپ بیت‌کوین آلت باز نشود
    if ENABLE_BTC_CHOP_GATE and key not in ("BTC", "BTCUSDT"):
        btc_label = None
        btc_conf = None
        if isinstance(diagnostics, dict):
            btc_label = diagnostics.get("btc_regime_label")
            btc_conf = diagnostics.get("btc_regime_confidence")
        if not btc_label:
            try:
                from indicators import get_btc_regime_snapshot
                snap = get_btc_regime_snapshot()
                btc_label = snap.get("label")
                btc_conf = snap.get("confidence")
            except Exception:
                pass
        if btc_label:
            lab = str(btc_label).upper()
            try:
                bc = float(btc_conf) if btc_conf is not None else None
            except (TypeError, ValueError):
                bc = None
            if lab == "CHOP" and BTC_CHOP_BLOCK_ALTS:
                if _strategy_id == "range_scalp" and RANGE_ALLOW_BTC_CHOP:
                    pass  # V.2.10.97 range_scalp
                elif _strategy_id == "weak_trend" and ENABLE_WEAK_TREND:
                    pass
                elif (
                    ENABLE_ADX_BYPASS_BTC_CHOP
                    and ENABLE_STRONG_ADX_BYPASS_BTC_PAUSE
                    and _symbol_adx_strong(diagnostics)
                ):
                    pass  # فقط اگر صریحاً اجازه bypass CHOP داده شده باشد
                else:
                    return False, (
                        "رژیم BTC=CHOP — ورود آلت مسدود "
                        "(بازار نویزی/بدون جهت؛ ADX نماد CHOP بیت‌کوین را دور نمی‌زند)"
                    )
            if lab == "WEAK" and bc is not None and bc < BTC_WEAK_MIN_CONF:
                if _strategy_id == "range_scalp" and RANGE_ALLOW_BTC_WEAK:
                    pass  # V.2.10.97 range_scalp
                elif _strategy_id == "weak_trend" and ENABLE_WEAK_TREND:
                    pass
                elif ENABLE_STRONG_ADX_BYPASS_BTC_PAUSE and _symbol_adx_strong(diagnostics):
                    pass  # V.2.10.66/76: ADX قوی نماد — وتوی WEAK برداشته شد
                else:
                    return False, (
                        f"رژیم BTC=WEAK({bc:.0f}) < {BTC_WEAK_MIN_CONF:.0f} — ورود آلت محتاط/رد"
                    )

    # V.2.10.99: برای range_scalp اعمال نمی‌شود — رنج واقعی ذاتاً ER نزدیک صفر دارد و
    # کف ۰٫۰۴ با فیلتر شیب رنج عملاً ناسازگار بود (ورود رنج تقریباً ناممکن).
    if ENABLE_ER_NOISE_FILTER_REAL and _strategy_id != "range_scalp" and isinstance(diagnostics, dict):
        er_v = diagnostics.get("efficiency_ratio_1h")
        try:
            er_f = float(er_v) if er_v is not None else None
        except (TypeError, ValueError):
            er_f = None
        _er_floor = float(RANGE_ER_FLOOR) if _strategy_id == "range_scalp" else float(ER_NOISE_MAX)
        if er_f is not None and er_f < _er_floor:
            return False, (
                f"ER نویزی ({er_f:.3f} < {_er_floor}) — حرکت بی‌کیفیت علیرغم برچسب رژیم؛ ریل رد"
            )

    # V.2.10.90 — CI بالا = رنج/نویز (حتی اگر ADX/stack خوب باشد)
    if ENABLE_CI_NOISE_FILTER_REAL and _strategy_id != "range_scalp" and isinstance(diagnostics, dict):
        try:
            ci_v = diagnostics.get("choppiness_1h")
            if ci_v is None:
                ci_v = diagnostics.get("ci") or diagnostics.get("chop_index")
            ci_f = float(ci_v) if ci_v is not None else None
        except (TypeError, ValueError):
            ci_f = None
        _ci_cap = float(RANGE_CI_HARD_MAX) if _strategy_id == "range_scalp" else float(CI_NOISE_MAX)
        if ci_f is not None and ci_f >= _ci_cap:
            return False, (
                f"CI نویز/رنج ({ci_f:.1f} ≥ {_ci_cap:.0f}) — برچسب روند ممکن است گمراه‌کننده باشد؛ ریل رد"
            )

    # V.2.10.90 — روند ظاهری: TREND_OK ولی ER ضعیف + CI بالا
    # V.2.10.97: در range_scalp این گیت روندی اعمال نمی‌شود
    if ENABLE_TREND_QUALITY_GATE and _strategy_id != "range_scalp" and isinstance(diagnostics, dict):
        try:
            lab = str(
                diagnostics.get("regime_label")
                or diagnostics.get("regime")
                or ""
            ).upper()
            er_v = diagnostics.get("efficiency_ratio_1h") or diagnostics.get("er")
            ci_v = diagnostics.get("choppiness_1h") or diagnostics.get("ci") or diagnostics.get("chop_index")
            er_f = float(er_v) if er_v is not None else None
            ci_f = float(ci_v) if ci_v is not None else None
        except (TypeError, ValueError):
            lab, er_f, ci_f = "", None, None
        if "TREND" in lab and er_f is not None and ci_f is not None:
            if er_f < float(TREND_QUALITY_MIN_ER) and ci_f >= float(TREND_QUALITY_MAX_CI):
                return False, (
                    f"روند ظاهری/نویزی (label={lab} ER={er_f:.3f}<{TREND_QUALITY_MIN_ER} "
                    f"CI={ci_f:.1f}≥{TREND_QUALITY_MAX_CI:.0f}) — ورود ریل رد"
                )


    # V.2.10.91 — ER سخت‌تر فقط برای آلت‌ها
    if ENABLE_ALT_ER_STRICT and _strategy_id != "range_scalp" and isinstance(diagnostics, dict):
        _sym_u = _norm_symbol(symbol).upper()
        if _sym_u not in ("BTC", "BTCUSDT"):
            try:
                _er_a = diagnostics.get("efficiency_ratio_1h") or diagnostics.get("er")
                _er_af = float(_er_a) if _er_a is not None else None
            except (TypeError, ValueError):
                _er_af = None
            _alt_er_need = float(RANGE_ER_FLOOR) if _strategy_id == "range_scalp" else float(ALT_ER_MIN)
            if _er_af is not None and _er_af < _alt_er_need:
                return False, (
                    f"ER آلت ضعیف ({_er_af:.3f} < {_alt_er_need}) — نویز/روند کم‌کیفیت؛ ریل رد"
                )

    # V.2.10.63 — کف ADX 1h: TREND_OK با ADX ضعیف وارد نشود
    # V.2.10.97: range_scalp از کف ADX روندی معاف است (رنج به ADX بالا نیاز ندارد)
    if ENABLE_MIN_ADX_ENTRY and _strategy_id != "range_scalp" and isinstance(diagnostics, dict):
        try:
            adx_v = diagnostics.get("adx_1h")
            if adx_v is None:
                adx_v = diagnostics.get("adx")
            adx_f = float(adx_v) if adx_v is not None else None
        except (TypeError, ValueError):
            adx_f = None
        _adx_need = float(WEAK_TREND_MIN_ADX) if _strategy_id == "weak_trend" else float(MIN_ADX_1H_FOR_ENTRY)
        if adx_f is not None and adx_f < _adx_need:
            return False, (
                f"ADX ضعیف ({adx_f:.1f} < {_adx_need:.0f}) — "
                f"روند برچسب‌خورده ولی قدرت کافی نیست؛ ریل رد"
            )
        if key not in ("BTC", "BTCUSDT") and _strategy_id != "weak_trend":
            strong_own = adx_f is not None and adx_f >= ADX_STRONG_BYPASS_BTC
            if strong_own:
                # روند خود نماد قوی است؛ BTC ADX را برای این ورود سخت نگیر
                pass
            else:
                try:
                    btc_adx = diagnostics.get("btc_adx_1h")
                    if btc_adx is None:
                        btc_adx = diagnostics.get("btc_adx")
                    btc_adx_f = float(btc_adx) if btc_adx is not None else None
                except (TypeError, ValueError):
                    btc_adx_f = None
                if btc_adx_f is None:
                    try:
                        from indicators import get_btc_regime_snapshot
                        snap = get_btc_regime_snapshot() or {}
                        btc_adx_f = snap.get("adx_1h") or snap.get("adx")
                        if btc_adx_f is not None:
                            btc_adx_f = float(btc_adx_f)
                    except Exception:
                        btc_adx_f = None
                if btc_adx_f is not None and btc_adx_f < MIN_BTC_ADX_1H_FOR_ALT:
                    return False, (
                        f"ADX بیت‌کوین ضعیف ({btc_adx_f:.1f} < {MIN_BTC_ADX_1H_FOR_ALT:.0f}) — "
                        f"ورود آلت رد (ADX نماد {adx_f:.1f} < {ADX_STRONG_BYPASS_BTC:.0f})"
                    )

    if _strategy_id != "range_scalp":
        try:
            _an_ok, _an_why = await _entry_anti_noise_check(symbol, direction)
            if not _an_ok:
                return False, _an_why
        except Exception as _ane:
            logger.debug("anti-noise gate error %s: %s", symbol, _ane)

    if _strategy_id != "range_scalp":
        demo_wr, demo_n = _demo_symbol_wr(key, direction)
        if demo_n >= REAL_MIN_SYMBOL_SAMPLES and demo_wr is not None and demo_wr < REAL_MIN_SYMBOL_WR:
            return False, (
                f"WR دمو نماد {key}={demo_wr:.1f}% روی {demo_n} معامله "
                f"(حداقل {REAL_MIN_SYMBOL_WR}% لازم)"
            )
        ok_wr, wr_reason, _size_mult = await _live_wr_gate(key, direction)
        if not ok_wr:
            return False, wr_reason

    bal = await _available_balance()
    if bal < MIN_MARGIN_USDT:
        return False, f"موجودی آزاد ({bal:.2f}) کمتر از حداقل مارجین"

    # V.2.10.28 Phase1: Regime Confidence — فقط soft/log (نه گیت)
    # V.2.10.30: reason غنی برای last_attempts
    # V.2.13.0 — جدول تصمیم خودکار (آخرین گیت؛ خانهٔ خاموش ⇒ کاغذی)
    _mkt = None
    _cell = None
    _cstat = None
    if not _probe:
        try:
            _mkt = _market_state_now()
            _cell = f"{_matrix_family(_strategy_id)}|{direction}|{_mkt}"
            _cstat = _matrix_status(_cell)
        except Exception:
            _cstat = None
        _sf = (_MATRIX.get("symbol_filter") or {}).get(_matrix_family(_strategy_id)) if _cstat is not None else None
        if _sf is not None and _norm_symbol(symbol) not in set(_sf):
            _papered = _paper_open(
                symbol, direction, entry, stop_loss, target, str(_strategy_id or "trend"), "matrix_symbol_off",
                score=confluence_score, drift=dict(_BTC_DRIFT_CACHE.get("state") or {}),
                time_stop_sec=float(RANGE_TIME_STOP_SEC if _strategy_id == "range_scalp" else MAX_HOLD_SECONDS),
                extra={"matrix_cell": _cell, "market_state": _mkt},
            )
            return False, (f"matrix_symbol_off: {_norm_symbol(symbol)} برای {_matrix_family(_strategy_id)} در فهرست نمادهای سازگار نیست"
                           + (" · کاغذی ثبت شد" if _papered else ""))
        if _cstat == "off":
            _papered = _paper_open(
                symbol, direction, entry, stop_loss, target, str(_strategy_id or "trend"), "matrix_off",
                score=confluence_score, drift=dict(_BTC_DRIFT_CACHE.get("state") or {}),
                time_stop_sec=float(RANGE_TIME_STOP_SEC if _strategy_id == "range_scalp" else MAX_HOLD_SECONDS),
                extra={"matrix_cell": _cell, "market_state": _mkt},
            )
            _why_cell = (((_MATRIX.get("policy") or {}).get(_cell) or {}).get("why")
                         or ((_MATRIX.get("demoted") or {}).get(_cell) or {}).get("why") or "")
            return False, f"matrix_off: {_cell} — {_why_cell}" + (" · کاغذی ثبت شد" if _papered else "")
        if _cstat == "probe":
            _n_probe = sum(1 for _m in _tracked.values()
                           if isinstance(_m, dict) and _m.get("status") == "open" and _m.get("matrix_status") == "probe")
            if _n_probe >= MATRIX_PROBE_MAX_OPEN:
                return False, f"matrix_probe_busy: {_cell} — سقف هم‌زمان خانه‌های آزمایشی ({_n_probe}/{MATRIX_PROBE_MAX_OPEN})"
    # V.2.11.0 — آخرین گیت (بعد از عبور از همهٔ گیت‌های دیگر): رنجِ خلاف رانش تأییدشدهٔ BTC باز نمی‌شود.
    # همین سیگنال «کاغذی» دنبال می‌شود تا اثر واقعی این فیلتر روی سود سنجیده شود.
    if _strategy_id == "range_scalp" and BTC_DRIFT_GUARD_RANGE and _against_drift(direction, _drift):
        _papered = _paper_open(
            symbol, direction, entry, stop_loss, target, "range_scalp",
            "btc_drift_guard", score=confluence_score, drift=_drift, time_stop_sec=RANGE_TIME_STOP_SEC,
        )
        return False, (
            f"[range] btc_drift: {_drift_label(_drift)} — {direction} رنج خلاف رانش BTC رد شد"
            + (" · کاغذی ثبت شد" if _papered else "")
        )
    # V.2.19.1 — ترند/رنج هم فقط بعد از اثبات در آزمون کاغذی رو به جلو با پول واقعی
    _famx = _matrix_family(_strategy_id)
    if not _probe and _famx in FORWARD_FAMILIES and _fwd_micro_busy(_famx, direction):   # V.2.20.0
        return False, str(_fwd_micro_busy(_famx, direction))
    if not _probe and _famx in FORWARD_FAMILIES and _fwd_get(_famx, direction).get("mode") != "live":
        _papered = _paper_open(
            symbol, direction, entry, stop_loss, target, str(_strategy_id or "trend"), "forward_test",
            score=confluence_score, drift=dict(_BTC_DRIFT_CACHE.get("state") or {}),
            time_stop_sec=float(RANGE_TIME_STOP_SEC if _strategy_id == "range_scalp" else MAX_HOLD_SECONDS),
            extra={"matrix_cell": _cell, "market_state": _mkt, "fwd_family": _famx},
        )
        _pn = int((_fwd_get(_famx, direction).get("paper") or {}).get("n") or 0)
        return False, (f"forward_test: {_famx}/{direction} در آزمون کاغذی رو به جلو ({_pn}/{FWD_PROMOTE_MIN_N})"
                       + (" · کاغذی ثبت شد" if _papered else ""))
    try:
        _pending_drift_follow[_norm_symbol(symbol)] = bool(_drift_follow)
        if _strategy_id == "range_scalp":
            _pending_range_source[_norm_symbol(symbol)] = "engine" if _explicit == "range_scalp" else "relabel"
    except Exception:
        pass
    try:
        _pending_strategy[_norm_symbol(symbol)] = str(_strategy_id or "trend")
        if _cell:
            _pending_matrix[_norm_symbol(symbol)] = {"matrix_cell": _cell, "market_state": _mkt,
                                                     "matrix_status": _cstat or "no_policy"}
    except Exception:
        pass
    if isinstance(diagnostics, dict):
        return True, _format_open_reason("ok", diagnostics)
    return True, "ok"


def _max_margin_for(equity: float, available: float | None = None) -> float:
    """سقف مارجین نسبتی از equity؛ هرگز بیشتر از available آزاد نباشد."""
    soft = equity * MAX_MARGIN_FRACTION
    cap = max(MIN_MARGIN_USDT, min(soft, MAX_MARGIN_USDT_ABS, equity * 0.95))
    if available is not None and available > 0:
        cap = min(cap, available * 0.95)
    return cap


def _calc_margin(equity: float, entry: float = 0.0, available: float | None = None) -> float:
    """
    V.2.10.40: مارجین = MARGIN_FRACTION × equity (نه available).
    available فقط سقف نقدینگی آزاد است تا سفارش رد نشود.
    """
    free = available if available is not None else equity
    cap = _max_margin_for(equity, free)
    m = equity * MARGIN_FRACTION
    m = max(MIN_MARGIN_USDT, min(cap, m))
    if entry > 0 and LEVERAGE > 0:
        min_notional = _effective_min_notional(equity)
        need = min_notional / LEVERAGE
        if m < need:
            m = min(need, equity * MAX_MARGIN_FRACTION, cap)
    # هرگز بیشتر از آزاد
    m = min(m, free * 0.95) if free > 0 else m
    return round(max(MIN_MARGIN_USDT, min(m, cap)), 4)


def _format_qty(qty: float, entry: float, step: float = 0.0) -> str:
    """فرمت qty مطابق step صرافی (در صورت نبود step از قیمت حدس می‌زند)."""
    if qty <= 0:
        return "0"
    if step and step > 0:
        return toobit_private.format_qty_value(qty, step)
    if entry >= 1000:
        s = f"{qty:.4f}"
    elif entry >= 10:
        s = f"{qty:.3f}"
    elif entry >= 1:
        s = f"{qty:.2f}"
    else:
        s = f"{qty:.0f}" if qty >= 1 else f"{qty:.2f}"
    return s.rstrip("0").rstrip(".") or "0"


def _exchange_order_qty(result) -> float | None:
    """V.2.39.1 — origQty/executedQty از پاسخ سفارش (خود پاسخ یا data)."""
    for src in (result, (result or {}).get("data") if isinstance(result, dict) else None):
        if not isinstance(src, dict):
            continue
        for k in ("origQty", "executedQty", "executeQty"):
            try:
                v = float(src.get(k) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                return v
    return None


async def _resolve_qty(symbol: str, entry: float, notional: float,
                       floor_override: float | None = None) -> tuple[str, float, dict]:
    """
    qty را طوری بساز که minQty / stepSize / minNotional و contractMultiplier رعایت شود.
    V.2.10.25: notional واقعی = qty * price * contract_multiplier
    (ETH mult=0.01 · DOT/OP/XRP mult=0.1 · ADA/DOGE mult=1)
    """
    filt = await toobit_private.get_symbol_filters(symbol)
    min_qty = float(filt.get("min_qty") or 0.001)
    step = float(filt.get("step_size") or 0.001)
    try:
        mult = float(filt.get("contract_multiplier") or 1.0) or 1.0
    except (TypeError, ValueError):
        mult = 1.0
    if step <= 0:
        step = 0.001
    if min_qty <= 0:
        min_qty = step
    min_notional = float(filt.get("min_notional") or 0.0)
    # کف داخلی: مارجین×اهرم
    floor_notional = max(MIN_MARGIN_USDT * LEVERAGE, MIN_NOTIONAL_USDT * 0.98, min_notional or 0.0)
    if floor_override is not None:   # V.2.38.2 — GH با SL پهن: کف ۱۵$ (نه ۲۴٫۵$) تا سقف ضرر هر ورود رعایت شود
        floor_notional = max(float(floor_override), min_notional or 0.0)
    target_notional = max(notional, floor_notional)
    if entry <= 0:
        return "0", 0.0, filt

    unit = entry * mult  # ارزش یک واحد qty

    def _fit(n: float) -> tuple[float, float]:
        q = n / unit
        q = max(q, min_qty)
        q = toobit_private.round_qty_to_step(q, step, min_qty)
        if q < min_qty:
            q = toobit_private.round_qty_to_step(min_qty + step, step, min_qty)
            if q < min_qty:
                q = min_qty
        an = q * unit
        return q, an

    qty, actual_notional = _fit(target_notional)
    # اگر هنوز زیر کف مارجین: بزرگ‌تر کن
    need_n = max(target_notional, min_qty * unit * 1.05)
    if actual_notional < floor_notional * 0.98 or qty < min_qty:
        qty, actual_notional = _fit(need_n)
    # هنوز کم؟ حداقل مارجین ۳$ را با ضریب اطمینان بزن
    if actual_notional < floor_notional * 0.98:
        qty, actual_notional = _fit(floor_notional * 1.15)
    if floor_override is not None and (qty - step) * unit < MIN_MARGIN_USDT * LEVERAGE / 0.98:
        # V.2.39.1 — یک پله ذخیره: صرافی ممکن است یک پله رو به پایین گرد کند (ETH ۰٫۷ ⇒ ۰٫۶)
        qty = toobit_private.round_qty_to_step(qty + step, step, min_qty)
        actual_notional = qty * unit
    qty_str = toobit_private.format_qty_value(qty, step)
    return qty_str, qty, {
        **filt,
        "target_notional": target_notional,
        "actual_notional": actual_notional,
        "contract_multiplier": mult,
        "min_qty": min_qty,
        "step_size": step,
        "min_notional": min_notional,
    }


def _estimate_adverse_usdt(notional: float, entry: float, stop_loss: float) -> float:
    """زیان قیمتی + اصطکاک روی notional. برای سقف بودجهٔ range/weak بعد از گردکردن حجم."""
    try:
        n = float(notional)
        e = float(entry)
        sl = float(stop_loss)
    except (TypeError, ValueError):
        return 1e9
    if e <= 0 or n <= 0:
        return 1e9
    sl_pct = abs(e - sl) / e * 100.0
    fr = abs(float(ROUND_TRIP_FRICTION_PCT))
    return n * (sl_pct + fr) / 100.0


def _margin_for_strategy(
    base_margin: float,
    strategy_id: str,
    entry: float,
    stop_loss: float,
    equity: float,
    available: float,
) -> tuple[float, str | None, dict]:
    """ضریب سایز range/weak را با max(MIN_MARGIN) برنمی‌گرداند.
    اگر notional زیر کف برنامه باشد، فقط وقتی زیان تخمینی داخل بودجه بماند تا کف بالا می‌رود.
    """
    sid = str(strategy_id or "trend")
    info: dict = {"strategy_id": sid, "bumped": False, "base_margin": float(base_margin)}
    if sid in ("rel_strength", "rs_intraday_50", "tsmom_daily", "trend_atr_daily") or sid in GH_LIVE_STRATEGIES:
        # V.2.18.3 — همان حجم بک‌تست: حداقل notional (~۲۵$)، نه ۲۰٪ موجودی (~۴۵$). SL این‌ها تا ۴–۶٪ است؛
        # با ۴۵$ ضرر هر SL ≈ ۱٫۹$ (۴٪ موجودی) می‌شد. بزرگ شدن فقط از مسیر اثبات زنده (_matrix_size_mult).
        floor_n = float(_effective_min_notional(equity if equity > 0 else available))
        mult = 1.0
        if sid in GH_LIVE_STRATEGIES:   # V.2.31.0 — حجم بیشتر برای سودده‌ترین‌ها، با سقف ضرر ۸٪ موجودی
            rk = _gh_rank(sid)
            try:   # V.2.38.2 — بزرگ‌کردن فقط با کاغذی رو به جلوی مثبت
                _fs = _bg_reg.fwd_stats(sid)
                _fw_ok = int(_fs.get("n") or 0) >= GH_SIZEUP_FWD_N and float(_fs.get("net_avg_pct") or -1) > GH_SIZEUP_FWD_AVG
            except Exception:
                _fw_ok = False
            info["fwd_ok"] = _fw_ok
            if rk is not None and rk < len(GH_RANK_SIZE_MULT) and _fw_ok:
                mult = float(GH_RANK_SIZE_MULT[rk])
                cap_loss = float(equity if equity > 0 else available) * GH_RANK_MAX_LOSS_PCT / 100.0
                per_n = _estimate_adverse_usdt(1.0, entry, stop_loss)   # ضرر هر ۱$ notional
                if per_n > 0:
                    mult = max(1.0, min(mult, cap_loss / per_n / floor_n))
            info["rank"] = rk
        n_ = floor_n * mult
        if sid in GH_LIVE_STRATEGIES:   # V.2.38.2 — یک SL نباید بیشتر از ~نصف سقف ضرر روزانه را بخورد
            _pn = _estimate_adverse_usdt(1.0, entry, stop_loss)
            if 0 < _pn < 1e8 and n_ * _pn > GH_MAX_TRADE_LOSS_USDT:
                n_ = max(float(GH_SIZE_FLOOR_USDT), GH_MAX_TRADE_LOSS_USDT / _pn)
                mult = n_ / floor_n
                info["loss_capped"] = True
        m = n_ / max(float(LEVERAGE), 1.0)
        info.update(size_mult=round(mult, 3), fixed_notional=round(n_, 4),
                    est_loss=round(_estimate_adverse_usdt(n_, entry, stop_loss), 4))
        if mult > 1.0:
            cap_m = _max_margin_for(equity if equity > 0 else available, available if available > 0 else None)
            return round(min(m, float(cap_m)) if cap_m else m, 4), None, info
        return round(min(float(base_margin), m) if base_margin > 0 else m, 4), None, info
    if sid not in ("range_scalp", "weak_trend"):
        return float(base_margin), None, info
    mult = float(RANGE_SIZE_MULT if sid == "range_scalp" else WEAK_TREND_SIZE_MULT)
    budget = float(RANGE_MAX_LOSS_USDT if sid == "range_scalp" else WEAK_TREND_MAX_LOSS_USDT)
    margin = float(base_margin) * mult
    info["size_mult"] = mult
    info["budget"] = budget
    info["margin_after_mult"] = round(margin, 4)
    notional = margin * float(LEVERAGE)
    floor_n = float(_effective_min_notional(equity if equity > 0 else available))
    info["floor_notional"] = floor_n
    if notional + 1e-9 < floor_n * 0.98:
        floor_margin = floor_n / max(float(LEVERAGE), 1.0)
        cap = _max_margin_for(equity if equity > 0 else available, available if available > 0 else None)
        est = _estimate_adverse_usdt(floor_n, entry, stop_loss)
        info["est_loss_at_floor"] = round(est, 4)
        info["margin_cap"] = round(cap, 4)
        if est <= budget + 1e-9 and floor_margin <= cap + 1e-6:
            margin = floor_margin
            info["bumped"] = True
        else:
            why = (
                f"سایز {sid} بعد از ضریب {mult:.2f} notional {notional:.2f} < کف {floor_n:.1f}؛ "
                f"بالابردن تا کف زیان≈{est:.3f}$ در برابر بودجه {budget:.2f}$ "
                f"(سقف مارجین {cap:.2f}) — سفارش رد شد"
            )
            return margin, why, info
    est_final = _estimate_adverse_usdt(margin * float(LEVERAGE), entry, stop_loss)
    info["est_loss"] = round(est_final, 4)
    if est_final > budget + 1e-6:
        why = (
            f"زیان تخمینی {sid} {est_final:.3f}$ > بودجه {budget:.2f}$ "
            f"(notional {margin * float(LEVERAGE):.2f})"
        )
        return margin, why, info
    return round(float(margin), 4), None, info


async def open_real_trade(symbol: str, direction: str, entry: float,
                          stop_loss: float, target: float,
                          confluence_score: float,
                          diagnostics: dict | None = None) -> dict[str, Any]:
    """
    باز کردن پوزیشن واقعی با سفارش مارکت + اهرم ثابت + ثبت در ردیاب داخلی.
    """
    allowed, reason = await can_open_real_trade(
        symbol, direction, entry, stop_loss, target, confluence_score,
        diagnostics=diagnostics,
    )
    if not allowed:
        # کول‌داون را دوباره زمان‌بندی نکن (وگرنه هر سیکل ۱۲ دقیقه از نو شروع می‌شود)
        try:
            print(f"[regime] skip {symbol} {direction} score={confluence_score} | {_format_open_reason(str(reason)[:80], diagnostics)}", flush=True)
        except Exception:
            pass
        if not str(reason).startswith("کول‌داون"):
            # reason رد + رژیم (اگر diagnostics باشد)
            rich = reason
            try:
                if isinstance(diagnostics, dict) and diagnostics.get("regime_label") is not None:
                    rich = f"{reason} | {_format_open_reason('diag', diagnostics)}"
            except Exception:
                rich = reason
            _record_attempt(symbol, False, rich, score=confluence_score, direction=direction)
        return {"ok": False, "reason": reason}

    available = await _available_balance()
    equity = await _equity_balance()
    if equity <= 0:
        equity = available
    margin = _calc_margin(equity, entry=entry, available=available)
    size_mult = 1.0
    _sid = "trend"
    _size_info: dict = {}
    try:
        _sid = str(_pending_strategy.pop(_norm_symbol(symbol), None) or "trend")
    except Exception:
        _sid = "trend"
    if isinstance(diagnostics, dict) and diagnostics.get("strategy_id") in ("range_scalp", "weak_trend", "trend", "rel_strength",
                                                                            "rs_intraday_50",
                                                                            "tsmom_daily", "trend_atr_daily",
                                                                            *GH_LIVE_STRATEGIES):
        _sid = str(diagnostics.get("strategy_id"))
    if _sid == "trend":
        try:
            _ok_wr, _wr_reason, _sm = await _live_wr_gate(symbol, direction)
            _sm = float(_sm or 1.0)
            size_mult = _sm
            if _sm < 0.999:
                margin = max(MIN_MARGIN_USDT, margin * _sm)
                logger.info(
                    "probation size %s %s mult=%.2f margin=%.3f | %s",
                    symbol, direction, size_mult, margin, _wr_reason,
                )
                _record_attempt(
                    symbol, True, f"size_probation:{_wr_reason}",
                    score=confluence_score, direction=direction, size_mult=size_mult,
                )
        except Exception as e:
            logger.warning("size_mult failed: %s", e)
            size_mult = 1.0
        notional = margin * LEVERAGE
        min_notional = _effective_min_notional(equity)
        if notional < min_notional * 0.98:
            reason = (
                f"notional تقریبی {notional:.2f} USDT کمتر از حداقل {min_notional:.1f} "
                f"(موجودی {available:.2f} کافی نیست)"
            )
            _record_attempt(symbol, False, reason, score=confluence_score, direction=direction)
            return {"ok": False, "reason": reason}
    else:
        sized, size_reject, _size_info = _margin_for_strategy(
            margin, _sid, entry, stop_loss, equity, available,
        )
        size_mult = float(_size_info.get("size_mult") or size_mult)
        if size_reject:
            _record_attempt(symbol, False, size_reject, score=confluence_score, direction=direction)
            return {"ok": False, "reason": size_reject, "size": _size_info}
        margin = sized
        logger.info(
            "%s size %s mult=%.2f margin=%.3f bumped=%s est=%s",
            _sid, symbol, size_mult, margin, _size_info.get("bumped"), _size_info.get("est_loss"),
        )
    # V.2.16.0 — حجم بیشتر فقط برای خانه‌های اثبات‌شدهٔ زنده (و با سقف ضرر ۱٪ موجودی)
    _sz_reason = "base"
    try:
        _cell_now = (_pending_matrix.get(_norm_symbol(symbol)) or {}).get("matrix_cell")
        _slp = abs(float(entry) - float(stop_loss)) / float(entry) * 100.0
        _mm, _sz_reason = _matrix_size_mult(_cell_now, _slp, float(equity or 0), float(margin) * LEVERAGE)
        if _mm > 1.0:
            _cap_m = _max_margin_for(equity if equity > 0 else available, available if available > 0 else None)
            margin = min(float(margin) * _mm, float(_cap_m)) if _cap_m else float(margin) * _mm
            size_mult = float(size_mult) * _mm
    except Exception as _sze:
        logger.debug("size mult failed %s: %s", symbol, _sze)
    notional = margin * LEVERAGE

    qty_str, qty_val, filt_meta = await _resolve_qty(
        symbol, entry, notional, floor_override=(GH_SIZE_FLOOR_USDT if _sid in GH_LIVE_STRATEGIES else None))
    if not qty_str or qty_str == "0" or qty_val <= 0:
        _record_attempt(symbol, False, "quantity محاسبه‌شده صفر است", score=confluence_score)
        return {"ok": False, "reason": "quantity محاسبه‌شده صفر است"}

    # V.2.10.25: notional واقعی = qty * price * contract_multiplier
    ct = float(
        filt_meta.get("contract_multiplier")
        or filt_meta.get("contract_size")
        or filt_meta.get("multiplier")
        or 1.0
    )
    if ct <= 0:
        ct = 1.0
    actual_notional = float(filt_meta.get("actual_notional") or 0) or (qty_val * entry * ct)
    actual_notional = max(actual_notional, qty_val * entry * ct)
    actual_margin = actual_notional / max(LEVERAGE, 1)
    if _sid in ("range_scalp", "weak_trend"):
        _bgt = float(RANGE_MAX_LOSS_USDT if _sid == "range_scalp" else WEAK_TREND_MAX_LOSS_USDT)
        _est2 = _estimate_adverse_usdt(actual_notional, entry, stop_loss)
        if _est2 > _bgt + 1e-6:
            reason = (
                f"پس از گردکردن حجم، زیان تخمینی {_sid} {_est2:.3f}$ > بودجه {_bgt:.2f}$ "
                f"(notional {actual_notional:.2f})"
            )
            _record_attempt(symbol, False, reason, score=confluence_score, direction=direction)
            return {"ok": False, "reason": reason}
    elif _sid in GH_LIVE_STRATEGIES and actual_notional > max(1.6 * float(notional), GH_MAX_NOTIONAL_ABS_USDT):
        reason = (f"حجم بعد از گردکردن {actual_notional:.2f}$ بیش از سقف {max(1.6 * float(notional), GH_MAX_NOTIONAL_ABS_USDT):.2f}$ "
                  f"(min_qty/پلهٔ نماد بزرگ) — V.2.40.0")
        _record_attempt(symbol, False, reason, score=confluence_score, direction=direction)
        return {"ok": False, "reason": reason}
    elif _sid in GH_LIVE_STRATEGIES and _estimate_adverse_usdt(actual_notional, entry, stop_loss) > GH_MAX_TRADE_LOSS_HARD_USDT:
        reason = (f"پس از گردکردن حجم، زیان تخمینی {_sid} {_estimate_adverse_usdt(actual_notional, entry, stop_loss):.3f}$ "
                  f"> سقف {GH_MAX_TRADE_LOSS_HARD_USDT:.2f}$ (notional {actual_notional:.2f})")
        _record_attempt(symbol, False, reason, score=confluence_score, direction=direction)
        return {"ok": False, "reason": reason}
    elif actual_margin < MIN_MARGIN_USDT * 0.98:
        reason = (
            f"مارجین تقریبی {actual_margin:.2f}$ کمتر از کف {MIN_MARGIN_USDT:.1f}$ "
            f"(notional {actual_notional:.2f})"
        )
        _record_attempt(symbol, False, reason, score=confluence_score, direction=direction)
        return {"ok": False, "reason": reason}

    # V.2.10.100 — چک قبل از سفارش با همان گارد بعد از fill (گارد بعد از fill دست‌نخورده می‌ماند)
    _pre_ok, _pre_why, _pre_info = await _pre_order_geometry_check(
        symbol, direction, float(entry), float(stop_loss), float(target), _sid,
    )
    if not _pre_ok:
        _record_attempt(
            symbol, False, _pre_why, score=confluence_score, direction=direction,
            strategy=_sid, pre_order=_pre_info, signal_geom=_geom(entry, stop_loss, target),
        )
        logger.info("REAL PRE-ORDER SKIP %s %s: %s", symbol, direction, _pre_why)
        return {"ok": False, "reason": _pre_why, "pre_order": _pre_info}

    # V.2.11.3 — ورود محافظت‌شده (اختیاری)
    _entry_mode = "market"
    _limit_str: str | None = None
    _entry_plan: dict | None = None
    if ENTRY_PROTECTED_IOC:
        try:
            _filt_p = await toobit_private.get_symbol_filters(symbol)
            _ref = float((_pre_info or {}).get("live_price") or 0) or float(entry)
            _entry_plan = _protected_entry_plan(
                direction, _ref, float(entry), float(stop_loss), float(target), _sid,
                _filt_p.get("tick_size"), float(ENTRY_MAX_SLIPPAGE_PCT),
            )
            if _entry_plan.get("ok"):
                _limit_str = str(_entry_plan["limit_str"])
                _entry_mode = "protected_ioc"
            elif "گارد" in str(_entry_plan.get("reason") or ""):
                _why_p = f"pre_order: ورود محافظت‌شده ممکن نیست — {_entry_plan.get('reason')}"
                _record_attempt(symbol, False, _why_p, score=confluence_score, direction=direction,
                                strategy=_sid, entry_plan=_entry_plan)
                return {"ok": False, "reason": _why_p, "entry_plan": _entry_plan}
            else:
                _entry_mode = "market_fallback"
        except Exception as _pe:
            logger.warning("protected entry plan failed %s: %s", symbol, _pe)
            _entry_mode = "market_fallback"

    side = "BUY_OPEN" if direction == "long" else "SELL_OPEN"
    logger.info(
        "REAL OPEN %s %s qty=%s margin≈%s lev=%s score=%s filt=%s",
        symbol, side, qty_str, margin, LEVERAGE, confluence_score,
        {k: filt_meta.get(k) for k in ("min_qty", "step_size", "min_notional", "actual_notional", "contract_multiplier")},
    )
    result = await toobit_private.place_futures_market_order(
        symbol=symbol,
        side=side,
        quantity=qty_str,
        leverage=LEVERAGE,
        take_profit=str(target),
        stop_loss=str(stop_loss),
        limit_price=_limit_str,
    )
    # یک‌بار retry اگر quantity too small — qty را ×۲ یا حداقل notional بالاتر
    if result.get("error"):
        detail_raw = result.get("response") or result.get("message") or result
        detail = detail_raw
        if isinstance(detail, dict):
            detail = detail.get("msg") or detail.get("message") or detail.get("error") or str(detail)
        detail_s = str(detail).lower()
        if "quantity" in detail_s and "small" in detail_s:
            # V.2.10.24: چند پله retry با notional بالاتر — پیش‌فرض step/min اشتباه (1) حذف شد
            step = float(filt_meta.get("step_size") or 0.001)
            min_qty = float(filt_meta.get("min_qty") or 0.001)
            if step <= 0:
                step = 0.001
            if min_qty <= 0:
                min_qty = step
            mult = float(filt_meta.get("contract_multiplier") or 1.0) or 1.0
            unit = max(entry * mult, 1e-12)
            # V.2.10.55: سقف ریسک — retry نباید از max margin مجاز فراتر برود
            try:
                _eq = await _equity_balance()
            except Exception:
                _eq = available
            max_margin_allowed = min(
                float(_eq or 0) * MAX_MARGIN_FRACTION,
                MAX_MARGIN_USDT_ABS,
            )
            max_notional_allowed = max(max_margin_allowed * LEVERAGE, MIN_MARGIN_USDT * LEVERAGE)
            max_qty_by_risk = max_notional_allowed / unit
            candidates = [
                max(qty_val * 3.0, min_qty * 5),
                max(qty_val * 5.0, min_qty * 10),
                max((MIN_MARGIN_USDT * LEVERAGE * 1.2) / unit, min_qty * 5),
            ]
            # فقط اگر هنوز زیر سقف ریسک است، پله‌های بالاتر را اضافه کن
            for bump_n in (50.0, 100.0):
                q = max(bump_n / unit, min_qty * 10)
                if q <= max_qty_by_risk * 1.02:
                    candidates.append(q)
            result_ok = False
            for bump in candidates:
                if bump > max_qty_by_risk * 1.05:
                    logger.warning(
                        "REAL OPEN retry skip %s bump≈%.6f exceeds risk cap qty≈%.6f",
                        symbol, bump, max_qty_by_risk,
                    )
                    continue
                qty_val2 = toobit_private.round_qty_to_step(bump, step, min_qty)
                if qty_val2 < min_qty:
                    qty_val2 = toobit_private.round_qty_to_step(min_qty + step, step, min_qty)
                qty_str2 = toobit_private.format_qty_value(qty_val2, step)
                if qty_str2 in ("0", "0.0", "") or qty_val2 <= 0:
                    continue
                logger.warning(
                    "REAL OPEN retry %s qty %s → %s (bump≈%.6f) after too-small",
                    symbol, qty_str, qty_str2, bump,
                )
                result = await toobit_private.place_futures_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=qty_str2,
                    leverage=LEVERAGE,
                    take_profit=str(target),
                    stop_loss=str(stop_loss),
                    limit_price=_limit_str,
                )
                qty_str = qty_str2
                qty_val = qty_val2
                if not result.get("error"):
                    result_ok = True
                    break
                d2 = result.get("response") or result.get("message") or result
                if isinstance(d2, dict):
                    d2 = d2.get("msg") or d2.get("message") or str(d2)
                if "quantity" not in str(d2).lower() or "small" not in str(d2).lower():
                    break  # خطای دیگر — ادامه نده
            if not result_ok:
                logger.error("REAL OPEN %s still quantity too small after retries", symbol)
    if result.get("error"):
        detail = result.get("response") or result.get("message") or result
        if isinstance(detail, dict):
            detail = detail.get("msg") or detail.get("message") or detail.get("error") or str(detail)
        reason = f"خطای صرافی: {detail}"
        _record_attempt(
            symbol, False, reason,
            score=confluence_score, direction=direction,
            qty=qty_str, margin=margin, exchange=result,
        )
        print(f"[real_trade] OPEN failed {symbol}: {reason}", flush=True)
        return {"ok": False, "reason": reason, "exchange": result}

    # V.2.39.1 — حجم واقعی پذیرفته‌شدهٔ صرافی (Toobit حجم را بی‌صدا رو به پایین گرد می‌کند) ⇒ ثبت و استفاده
    _sent_qty = qty_str
    _ex_qty = _exchange_order_qty(result)
    if _ex_qty and _ex_qty > 0 and abs(_ex_qty - float(qty_val)) > 1e-12 and not (
            0.5 * float(qty_val) <= _ex_qty <= float(qty_val) * (1 + 1e-9)):   # V.2.39.3 — منتقد: فقط کاهش منطقی
        logger.warning("REAL OPEN %s exchange qty %s out of bounds vs sent %s — ignored", symbol, _ex_qty, qty_str)
    elif _ex_qty and _ex_qty > 0 and abs(_ex_qty - float(qty_val)) > 1e-12:
        logger.warning("REAL OPEN %s exchange qty %s != sent %s", symbol, _ex_qty, qty_str)
        try:
            _stp = float(filt_meta.get("step_size") or 0) or 0.001
            qty_str = toobit_private.format_qty_value(_ex_qty, _stp)
            qty_val = _ex_qty
        except Exception:
            pass

    # V.2.11.3 — IOC محافظت‌شده: آیا واقعاً پر شد؟ (پر نشد = بدون پوزیشن و بدون کارمزد)
    _partial_fill = False
    if _entry_mode == "protected_ioc":
        _fill = await _confirm_ioc_fill(symbol, direction)
        if _fill is None:
            _why_u = (
                f"entry_ioc_unfilled: قیمت از سقف لغزش {float(ENTRY_MAX_SLIPPAGE_PCT):.2f}٪ "
                f"(limit {_limit_str}) عبور کرد — سفارش پر نشد، کارمزدی پرداخت نشد"
            )
            _record_attempt(symbol, False, _why_u, score=confluence_score, direction=direction,
                            strategy=_sid, entry_plan=_entry_plan, exchange=result)
            logger.info("REAL IOC UNFILLED %s %s limit=%s", symbol, direction, _limit_str)
            return {"ok": False, "reason": _why_u, "entry_mode": _entry_mode, "entry_plan": _entry_plan}
        try:
            _step_f = float(filt_meta.get("step_size") or 0) or 0.001
            _q_f = float(_fill.get("qty") or 0)
            if _q_f > 0 and abs(_q_f - float(qty_val)) > _step_f * 0.5:
                _partial_fill = _q_f < float(qty_val)
                qty_str = toobit_private.format_qty_value(_q_f, _step_f)
                qty_val = _q_f
        except Exception:
            pass

    key = _norm_symbol(symbol)
    trade_id = f"real_{key}_{uuid.uuid4().hex[:10]}"
    actual_notional = float(qty_val) * float(entry) * ct   # V.2.39.3 — بعد از اصلاح حجم صرافی/پر شدن جزئی/retry (قبلاً کهنه)
    meta = {
        "trade_id": trade_id,
        "symbol": key,
        "direction": direction,
        # V.2.10.55: signal_entry = قیمت سیگنال؛ entry بعداً با Fill واقعی هم‌تراز می‌شود
        "signal_entry": float(entry),
        "entry": float(entry),
        "fill_entry": None,
        "entry_slippage_pct": None,
        "stop_loss": float(stop_loss),
        "original_stop_loss": float(stop_loss),
        "target": float(target),
        "quantity": qty_str,
        "sent_qty": _sent_qty, "exchange_qty": _ex_qty,   # V.2.39.1
        "margin_usdt": margin,
        "leverage": LEVERAGE,
        "score": float(confluence_score),
        "opened_at": time.time(),
        "profit_locked": False,
        "status": "open",
        "app_version": APP_VERSION,
        "strategy_id": str(_sid or "trend"),
        # V.2.10.100 — ثبت برای دفتر معاملات
        "pre_order": _pre_info,
        # V.2.11.3
        "entry_mode": _entry_mode,
        "entry_limit_price": _limit_str,
        "entry_plan": _entry_plan,
        "partial_fill": _partial_fill,
        # V.2.11.0
        "btc_ctx": dict(_BTC_DRIFT_CACHE.get("state") or {}),
        "drift_follow": bool(_pending_drift_follow.pop(_norm_symbol(symbol), False)),
        "range_source": _pending_range_source.pop(_norm_symbol(symbol), None),
        **(_pending_matrix.pop(_norm_symbol(symbol), None) or {}),  # V.2.13.0 matrix_cell / market_state / matrix_status
        "initial_sl": stop_loss,
        "signal_geom": _geom(entry, stop_loss, target),
        "notional_actual": round(float(actual_notional or 0), 4),
        "risk_usdt_est": round(float(actual_notional or 0) * (_geom(entry, stop_loss, target).get("sl_pct", 0) + abs(float(ROUND_TRIP_FRICTION_PCT))) / 100.0, 4),
        "sl_changes": [],
        "price_path": [],
        # V.2.10.39 — snapshot تنظیمات برای آمار به تفکیک نسخه
        "settings_snapshot": {
            "app_version": APP_VERSION,
            "min_confluence": MIN_CONFLUENCE_REAL,
            "min_sl_distance_pct": MIN_SL_DISTANCE_PCT,
            "max_sl_distance_pct": MAX_SL_DISTANCE_PCT,
            "min_rr": MIN_RR_REAL,
            "profit_lock_trigger": PROFIT_LOCK_TRIGGER_RATIO,
            "min_profit_pct": MIN_PROFIT_PCT_TO_LOCK,
            "breakeven_trigger_pct": BREAKEVEN_TRIGGER_PCT,
            "float_profit_exit": ENABLE_FLOAT_PROFIT_EXIT,
            "float_min_profit_usdt": FLOAT_MIN_PROFIT_USDT,
            "emergency_loss_pct": MAX_UNREALIZED_LOSS_PCT,
            "regime_tighten_sl": ENABLE_REGIME_TIGHTEN_SL,
            "max_hold_seconds": MAX_HOLD_SECONDS,
            "leverage": LEVERAGE,
            "margin_fraction": MARGIN_FRACTION,
            "strategy_id": str(_sid or "trend"),
            "enable_range_scalp": ENABLE_RANGE_SCALP,
            "range_size_mult": RANGE_SIZE_MULT,
            "range_min_rr": RANGE_MIN_RR,
            "range_signal_only": RANGE_SIGNAL_ONLY,
        },
    }
    if _sid == "range_scalp":
        meta["time_stop_deadline"] = time.time() + float(RANGE_TIME_STOP_SEC)
        meta["initial_risk"] = abs(float(entry) - float(stop_loss))
        if isinstance(diagnostics, dict):
            for fld in ("range_low", "range_high", "range_mid"):
                if diagnostics.get(fld) is not None:
                    meta[fld] = diagnostics.get(fld)
        snap = meta.get("settings_snapshot")
        if isinstance(snap, dict):
            snap["time_stop_deadline"] = meta.get("time_stop_deadline")
            snap["initial_risk"] = meta.get("initial_risk")
            for fld in ("range_low", "range_high", "range_mid"):
                if meta.get(fld) is not None:
                    snap[fld] = meta.get(fld)
    # V.2.10.59: snapshot رژیم برای هیسترزیس پس از برد
    if isinstance(diagnostics, dict):
        try:
            _er = diagnostics.get("efficiency_ratio_1h") or diagnostics.get("er")
            _adx = diagnostics.get("adx_1h") or diagnostics.get("adx")
            if _er is not None:
                meta["regime_er"] = float(_er)
            if _adx is not None:
                meta["regime_adx"] = float(_adx)
        except Exception:
            pass
    # V.2.10.77 — entry observation (بدون اثر روی گیت)
    try:
        meta["entry_observation"] = _build_entry_observation(
            diagnostics if isinstance(diagnostics, dict) else None,
            entry=float(entry),
            stop_loss=float(stop_loss),
            target=float(target),
            direction=str(direction),
            confluence_score=float(confluence_score) if confluence_score is not None else 0.0,
        )
        meta["lifecycle_observation"] = _init_lifecycle_observation(
            float(entry),
            str(direction),
            abs(float(entry) - float(stop_loss)) if float(stop_loss) > 0 else None,
        )
    except Exception as _obs_e:
        logger.debug("entry observation failed: %s", _obs_e)
    _tracked[key] = meta
    _open_reason = _format_open_reason("opened", diagnostics)
    print(f"[regime] {symbol} {direction} {_open_reason}")
    _record_attempt(symbol, True, _open_reason, score=confluence_score, direction=direction, trade_id=trade_id)
    logger.info("REAL TRACKED %s entry=%s tp=%s sl=%s", key, entry, target, stop_loss)
    print(f"[real_trade] OPENED {key} {direction} @ {entry} score={confluence_score} id={trade_id}", flush=True)

    # ثبت و تأیید TP/SL روی خود صرافی (نه فقط حلقه نرم‌افزار)
    tpsl = {"verified": False, "sl_on_exchange": False, "tp_on_exchange": False}
    try:
        tpsl = await toobit_private.attach_tpsl_and_verify(
            symbol=symbol,
            direction=direction,
            take_profit=str(target),
            stop_loss=str(stop_loss),
            quantity=qty_str,
        )
        meta["sl_on_exchange"] = bool(tpsl.get("sl_on_exchange"))
        meta["tp_on_exchange"] = bool(tpsl.get("tp_on_exchange"))
        meta["tpsl_source"] = tpsl.get("source")
        # V.2.10.41 — ذخیره clientOrderIdهای SL/TP برای exit_reason قطعی
        try:
            for o in (tpsl.get("orders") or []):
                if not isinstance(o, dict):
                    continue
                kind = str(o.get("kind") or "").lower()
                cid = o.get("clientOrderId")
                if not cid:
                    continue
                if kind == "sl":
                    meta["sl_client_order_id"] = str(cid)
                elif kind == "tp":
                    meta["tp_client_order_id"] = str(cid)
        except Exception:
            pass
        print(
            f"[real_trade] TPSL {key} sl={meta['sl_on_exchange']} tp={meta['tp_on_exchange']} source={tpsl.get('source')}",
            flush=True,
        )
        if not meta["sl_on_exchange"]:
            logger.error("REAL SL NOT CONFIRMED ON EXCHANGE for %s — software loop is the only protection", key)
    except Exception as e:
        logger.exception("REAL TPSL attach failed for %s: %s", key, e)
        meta["sl_on_exchange"] = False
        meta["tp_on_exchange"] = False
        tpsl = {"verified": False, "error": str(e)}

    # ذخیره اختیاری در Supabase (اگر جدول real_trades باشد)
    try:
        _save_tracked()
    except Exception as e:
        logger.warning("save tracked after open failed: %s", e)

    try:
        from database.supabase_client import save_real_trade
        await save_real_trade(meta)
    except Exception as e:
        logger.warning("persist open real trade failed: %s", e)

    # V.2.10.23: تأیید مارجین واقعی صرافی (qty×price گاهی با notional واقعی فرق دارد)
    try:
        import asyncio as _aio
        await _aio.sleep(0.9)
        _n, live_rows = await _open_positions_count()
        if live_rows is None:
            live_rows = []  # do not treat as all closed
        key_v = _norm_symbol(symbol)
        ex_margin = None
        for row in live_rows or []:
            if _norm_symbol(str(row.get("symbol") or "")) != key_v:
                continue
            try:
                ex_margin = float(row.get("margin") or 0)
            except Exception:
                ex_margin = None
            break
        if ex_margin is not None and 0 < ex_margin < MIN_MARGIN_USDT * 0.98:
            logger.error(
                "REAL OPEN %s exchange margin %.4f < floor %.1f — force close",
                key_v, ex_margin, MIN_MARGIN_USDT,
            )
            # V.2.10.56: مسیر واحد close ledger
            try:
                if key_v in _tracked and _tracked[key_v].get("status") == "open":
                    await _close_tracked(key_v, "undersized_margin")
                else:
                    await toobit_private.close_position_market(key_v, direction, qty_str)
                    if key_v in _tracked:
                        _tracked[key_v]["status"] = "closed"
                        _tracked[key_v]["closed_at"] = time.time()
                        _tracked[key_v]["exit_reason"] = "undersized_margin"
            except Exception as ce:
                logger.exception("force close undersized %s: %s", key_v, ce)
            try:
                _mark_symbol_closed(key_v, "undersized_margin")
            except Exception:
                pass
            reason = (
                f"مارجین واقعی صرافی {ex_margin:.2f}$ کمتر از کف {MIN_MARGIN_USDT:.1f}$ "
                f"— پوزیشن بسته شد"
            )
            _record_attempt(symbol, False, reason, score=confluence_score, direction=direction)
            return {"ok": False, "reason": reason, "exchange_margin": ex_margin}
        if ex_margin is not None and ex_margin > 0:
            meta["margin"] = str(ex_margin)
            meta["margin_usdt"] = ex_margin
            margin = ex_margin
        # V.2.10.55 — Fill reconciliation: avgPrice واقعی صرافی
        for row in live_rows or []:
            if _norm_symbol(str(row.get("symbol") or "")) != key_v:
                continue
            try:
                fill_px = float(
                    row.get("avgPrice")
                    or row.get("entryPrice")
                    or row.get("openPrice")
                    or 0
                )
            except (TypeError, ValueError):
                fill_px = 0.0
            if fill_px > 0:
                sig = float(meta.get("signal_entry") or entry)
                try:   # V.2.39.3 — notional و ریسک با حجم و قیمت پرشدهٔ واقعی
                    _nq = float(meta.get("quantity") or qty_val) * float(fill_px) * ct
                    meta["notional_actual"] = round(_nq, 4)
                    meta["risk_usdt_est"] = round(_nq * (abs(fill_px - float(stop_loss)) / fill_px * 100.0
                                                         + abs(float(ROUND_TRIP_FRICTION_PCT))) / 100.0, 4)
                except Exception:
                    pass
                meta["fill_entry"] = fill_px
                meta["entry"] = fill_px  # مدیریت ریسک/progress روی Fill
                # V.2.10.77/78 — lifecycle از Fill واقعی شروع شود
                try:
                    _risk = None
                    try:
                        _sl0 = float(meta.get("original_stop_loss") or meta.get("stop_loss") or 0)
                        if _sl0 > 0:
                            _risk = abs(float(fill_px) - _sl0)
                    except (TypeError, ValueError):
                        _risk = None
                    meta["lifecycle_observation"] = _init_lifecycle_observation(
                        float(fill_px), str(meta.get("direction") or direction), _risk
                    )
                    if isinstance(meta.get("entry_observation"), dict):
                        meta["entry_observation"]["fill_price"] = float(fill_px)
                        if _risk:
                            meta["entry_observation"]["initial_risk_price"] = round(_risk, 8)
                except Exception:
                    pass
                if sig > 0:
                    slip = ((fill_px - sig) / sig) * 100.0
                    if str(direction).lower() == "short":
                        slip = -slip  # برای short، fill پایین‌تر = slippage منفی بهتر
                    meta["entry_slippage_pct"] = round(slip, 4)
                logger.info(
                    "REAL FILL %s signal=%.6f fill=%.6f slip=%.4f%%",
                    key_v, sig, fill_px, float(meta.get("entry_slippage_pct") or 0),
                )
                print(
                    f"[real_trade] FILL {key_v} signal={sig} fill={fill_px} "
                    f"slip={meta.get('entry_slippage_pct')}%",
                    flush=True,
                )
                # V.2.10.56 — Post-fill re-anchor SL/TP نسبت به Fill واقعی
                try:
                    old_sl = float(meta.get("stop_loss") or stop_loss)
                    old_tp = float(meta.get("target") or target)
                    new_sl, new_tp, ra = _reanchor_levels_from_fill(
                        direction, sig if sig > 0 else fill_px, fill_px, old_sl, old_tp,
                        strategy_id=meta.get("strategy_id"),
                    )
                    meta["post_fill_validate"] = ra
                    if ra.get("invalid"):
                        # V.2.10.100 — ثبت دقیق علت ابطال: شرایط قبل از سفارش در برابر بعد از fill
                        try:
                            meta["fill_invalidation"] = {
                                "reason": ra.get("reason"),
                                "signal_entry": sig,
                                "pre_order_live_price": (meta.get("pre_order") or {}).get("live_price"),
                                "fill": fill_px,
                                "slippage_pct": meta.get("entry_slippage_pct"),
                                "stop_loss": old_sl,
                                "target": old_tp,
                                "geom_at_signal": _geom(sig if sig > 0 else fill_px, old_sl, old_tp),
                                "geom_at_fill": _geom(fill_px, old_sl, old_tp),
                                "strategy_id": meta.get("strategy_id"),
                            }
                        except Exception:
                            pass
                        logger.error(
                            "REAL FILL INVALIDATED %s: %s — force close",
                            key_v, ra.get("reason"),
                        )
                        print(
                            f"[real_trade] FILL_INVALIDATED {key_v} {ra.get('reason')}",
                            flush=True,
                        )
                        meta["stop_loss"] = new_sl
                        meta["target"] = new_tp
                        # بستن یکپارچه
                        try:
                            await _close_tracked(key_v, "fill_invalidated_trade")
                        except Exception as ce:
                            logger.exception("fill invalidate close failed %s: %s", key_v, ce)
                            try:
                                await toobit_private.close_position_market(key_v, direction, qty_str)
                            except Exception:
                                pass
                            meta["status"] = "closed"
                            meta["exit_reason"] = "fill_invalidated_trade"
                            meta["closed_at"] = time.time()
                        return {
                            "ok": False,
                            "reason": f"fill_invalidated_trade: {ra.get('reason')}",
                            "fill_entry": fill_px,
                            "signal_entry": sig,
                            "reanchor": ra,
                        }
                    if ra.get("reanchored") or ra.get("clamped_sl"):
                        _log_sl_change(meta, old_sl, new_sl, "post_fill_reanchor", price=fill_px,
                                       extra={"clamped": bool(ra.get("clamped_sl"))})
                        meta["stop_loss"] = new_sl
                        meta["target"] = new_tp
                        meta["original_stop_loss"] = float(meta.get("original_stop_loss") or old_sl)
                        logger.info(
                            "REAL REANCHOR %s fill=%.6f sl=%.6f→%.6f tp=%.6f→%.6f clamped=%s",
                            key_v, fill_px, old_sl, new_sl, old_tp, new_tp, ra.get("clamped_sl"),
                        )
                        print(
                            f"[real_trade] REANCHOR {key_v} SL {old_sl}→{new_sl} TP {old_tp}→{new_tp} "
                            f"clamped={ra.get('clamped_sl')}",
                            flush=True,
                        )
                        # ثبت مجدد TP/SL روی صرافی با سطوح جدید
                        try:
                            tpsl2 = await toobit_private.attach_tpsl_and_verify(
                                symbol=symbol,
                                direction=direction,
                                take_profit=str(new_tp),
                                stop_loss=str(new_sl),
                                quantity=qty_str,
                            )
                            meta["sl_on_exchange"] = bool(tpsl2.get("sl_on_exchange"))
                            meta["tp_on_exchange"] = bool(tpsl2.get("tp_on_exchange"))
                            meta["tpsl_source"] = tpsl2.get("source") or meta.get("tpsl_source")
                            print(
                                f"[real_trade] TPSL-REANCHOR {key_v} "
                                f"sl={meta.get('sl_on_exchange')} tp={meta.get('tp_on_exchange')}",
                                flush=True,
                            )
                        except Exception as te:
                            logger.warning("reanchor TPSL failed %s: %s", key_v, te)
                except Exception as re_e:
                    logger.warning("post-fill reanchor failed %s: %s", key_v, re_e)
            break
    except Exception as e:
        logger.warning("post-open margin/fill verify failed %s: %s", symbol, e)

    # V.2.12.3/2.13.0 — TP با کارمزد maker (اگر self-test موفق بوده، برای همهٔ ورودها)
    await _place_maker_tp(meta)
    # V.2.11.6 — fill واقعی/لغزش/چرخهٔ عمر بعد از save اولیه ثبت می‌شوند؛ یک بار دیگر ذخیره تا بعد از ری‌استارت بمانند
    try:
        from database.supabase_client import upsert_open_real_trade
        await upsert_open_real_trade(meta)
    except Exception as _ue:
        logger.debug("post-fill upsert failed %s: %s", symbol, _ue)

    return {
        "ok": True,
        "symbol": symbol,
        "direction": direction,
        "side": side,
        "quantity": qty_str,
        "margin_usdt": margin,
        "leverage": LEVERAGE,
        "entry": meta.get("entry", entry),
        "signal_entry": meta.get("signal_entry", entry),
        "fill_entry": meta.get("fill_entry"),
        "entry_slippage_pct": meta.get("entry_slippage_pct"),
        "stop_loss": stop_loss,
        "original_stop_loss": stop_loss,
        "target": target,
        "trade_id": trade_id,
        "exchange": result,
        "tpsl": {
            "sl_on_exchange": meta.get("sl_on_exchange"),
            "tp_on_exchange": meta.get("tp_on_exchange"),
            "source": tpsl.get("source"),
            "orders": tpsl.get("orders"),
        },
    }


def _progress(direction: str, entry: float, target: float, price: float) -> float:
    """نسبت پیشرفت به سمت هدف (۰ تا ۱+). منفی = خلاف جهت."""
    dist = abs(target - entry)
    if dist <= 0:
        return 0.0
    if direction == "long":
        return (price - entry) / dist
    return (entry - price) / dist



def _build_entry_observation(
    diagnostics: dict | None,
    *,
    entry: float,
    stop_loss: float,
    target: float,
    direction: str,
    confluence_score: float,
) -> dict:
    """V.2.10.77/78 — snapshot ورود فقط برای تحلیل؛ روی گیت اثر ندارد."""
    d = diagnostics if isinstance(diagnostics, dict) else {}
    obs: dict[str, Any] = {
        "app_version": APP_VERSION,
        "direction": str(direction).lower(),
        "entry_price": float(entry),
        "confluence": float(confluence_score) if confluence_score is not None else None,
        "entry_time": time.time(),
    }

    def _f(key, *alts):
        for k in (key,) + alts:
            v = d.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None

    obs["entry_adx"] = _f("adx_1h", "adx")
    obs["entry_er"] = _f("efficiency_ratio_1h", "er")
    obs["entry_ci"] = _f("choppiness_1h", "ci")
    obs["entry_overextension_atr"] = _f("overextension_atr")
    obs["entry_atr"] = _f("atr_1h", "atr", "atr_14")
    adx_now = obs["entry_adx"]
    adx_prev = _f("adx_1h_prev", "adx_prev_15m", "adx_15m_ago")
    if adx_now is not None and adx_prev is not None:
        obs["entry_adx_slope"] = round(adx_now - adx_prev, 4)
    else:
        obs["entry_adx_slope"] = None
    obs["entry_regime"] = d.get("regime_label") or d.get("regime")
    obs["entry_btc_regime"] = d.get("btc_regime_label") or d.get("btc_regime")
    obs["entry_htf_distance"] = _f("htf_distance_atr", "distance_to_htf_atr", "htf_distance")
    try:
        sl = abs(float(entry) - float(stop_loss))
        tp = abs(float(target) - float(entry))
        if entry > 0 and sl > 0:
            sl_pct = sl / float(entry) * 100.0
            tp_pct = tp / float(entry) * 100.0
            fr = float(ROUND_TRIP_FRICTION_PCT)
            obs["entry_sl_pct"] = round(sl_pct, 4)
            obs["entry_tp_pct"] = round(tp_pct, 4)
            obs["entry_net_rr"] = round(max(0.0, (tp_pct - fr) / max(sl_pct, 1e-9)), 4)
            obs["initial_risk_price"] = round(sl, 8)
        else:
            obs["entry_net_rr"] = None
            obs["initial_risk_price"] = None
    except Exception:
        obs["entry_net_rr"] = None
        obs["initial_risk_price"] = None
    # V.2.10.78 — anti-chase observation
    ox = obs.get("entry_overextension_atr")
    try:
        obs["anti_chase_would_reject"] = bool(ox is not None and float(ox) >= 1.25)
        obs["anti_chase_threshold"] = 1.25
    except (TypeError, ValueError):
        obs["anti_chase_would_reject"] = None
        obs["anti_chase_threshold"] = 1.25
    # V.2.10.78 — strong ADX bypass attribution (observation only)
    try:
        strong = bool(
            ENABLE_STRONG_ADX_BYPASS_BTC_PAUSE
            and obs.get("entry_adx") is not None
            and float(obs["entry_adx"]) >= float(ADX_STRONG_BYPASS_BTC)
        )
    except (TypeError, ValueError):
        strong = False
    obs["strong_symbol_bypass"] = strong
    obs["bypass_used"] = strong
    btc_lab = str(obs.get("entry_btc_regime") or "").upper()
    if strong:
        if "CHOP" in btc_lab:
            obs["bypass_reason"] = f"adx>={ADX_STRONG_BYPASS_BTC:.0f}_btc_chop"
        elif "WEAK" in btc_lab:
            obs["bypass_reason"] = f"adx>={ADX_STRONG_BYPASS_BTC:.0f}_btc_weak"
        else:
            obs["bypass_reason"] = f"adx>={ADX_STRONG_BYPASS_BTC:.0f}_btc_pause_eligible"
    else:
        obs["bypass_reason"] = None
    return obs


def _init_lifecycle_observation(entry: float, direction: str, initial_risk: float | None = None) -> dict:
    """V.2.10.77/78 — MAE/MFE sampled در طول عمر پوزیشن."""
    e = float(entry)
    now = time.time()
    return {
        "best_favorable_price": e,
        "worst_adverse_price": e,
        "best_sampled_price": e,
        "worst_sampled_price": e,
        "max_favorable_excursion": 0.0,
        "max_adverse_excursion": 0.0,
        "max_favorable_excursion_pct": 0.0,
        "max_adverse_excursion_pct": 0.0,
        "mfe_r": None,
        "mae_r": None,
        "initial_risk_price": float(initial_risk) if initial_risk and initial_risk > 0 else None,
        "snapshot_count": 0,
        "direction": str(direction).lower(),
        "entry_price": e,
        "observation_started_at": now,
        "last_observation_at": now,
        "max_observation_gap_sec": 0.0,
        "observation_gap_sec": 0.0,
        "mae_mfe_quality": "insufficient",
        "price_source": "sampled_manage_loop",
    }


def _update_lifecycle_observation(meta: dict, price: float) -> None:
    """هر تیک قیمت در حلقهٔ مدیریت — observation فقط (V.2.10.78)."""
    try:
        px = float(price)
    except (TypeError, ValueError):
        return
    if px <= 0:
        return
    life = meta.get("lifecycle_observation")
    if not isinstance(life, dict):
        entry = float(meta.get("fill_entry") or meta.get("entry") or 0)
        if entry <= 0:
            return
        risk = None
        try:
            sl0 = float(meta.get("original_stop_loss") or meta.get("stop_loss") or 0)
            if sl0 > 0:
                risk = abs(entry - sl0)
        except (TypeError, ValueError):
            risk = None
        life = _init_lifecycle_observation(entry, str(meta.get("direction") or "long"), risk)
        meta["lifecycle_observation"] = life
    entry = float(life.get("entry_price") or meta.get("fill_entry") or meta.get("entry") or 0)
    if entry <= 0:
        return
    direction = str(life.get("direction") or meta.get("direction") or "long").lower()
    now = time.time()
    last = float(life.get("last_observation_at") or life.get("observation_started_at") or now)
    gap = max(0.0, now - last)
    life["observation_gap_sec"] = round(gap, 2)
    life["max_observation_gap_sec"] = round(
        max(float(life.get("max_observation_gap_sec") or 0), gap), 2
    )
    life["last_observation_at"] = now
    life["snapshot_count"] = int(life.get("snapshot_count") or 0) + 1

    if direction == "short":
        if px < float(life.get("best_favorable_price") or entry):
            life["best_favorable_price"] = px
            life["best_sampled_price"] = px
        if px > float(life.get("worst_adverse_price") or entry):
            life["worst_adverse_price"] = px
            life["worst_sampled_price"] = px
        mfe = max(0.0, entry - float(life["best_favorable_price"]))
        mae = max(0.0, float(life["worst_adverse_price"]) - entry)
    else:
        if px > float(life.get("best_favorable_price") or entry):
            life["best_favorable_price"] = px
            life["best_sampled_price"] = px
        if px < float(life.get("worst_adverse_price") or entry):
            life["worst_adverse_price"] = px
            life["worst_sampled_price"] = px
        mfe = max(0.0, float(life["best_favorable_price"]) - entry)
        mae = max(0.0, entry - float(life["worst_adverse_price"]))

    life["max_favorable_excursion"] = round(mfe, 8)
    life["max_adverse_excursion"] = round(mae, 8)
    life["max_favorable_excursion_pct"] = round(mfe / entry * 100.0, 4)
    life["max_adverse_excursion_pct"] = round(mae / entry * 100.0, 4)

    # risk in R
    risk = life.get("initial_risk_price")
    if not risk or float(risk) <= 0:
        try:
            sl0 = float(meta.get("original_stop_loss") or meta.get("stop_loss") or 0)
            if sl0 > 0:
                risk = abs(entry - sl0)
                life["initial_risk_price"] = round(risk, 8)
        except (TypeError, ValueError):
            risk = None
    if risk and float(risk) > 0:
        life["mfe_r"] = round(mfe / float(risk), 4)
        life["mae_r"] = round(mae / float(risk), 4)
    else:
        life["mfe_r"] = None
        life["mae_r"] = None

    atr = None
    eo = meta.get("entry_observation") if isinstance(meta.get("entry_observation"), dict) else {}
    try:
        atr = float(eo.get("entry_atr")) if eo.get("entry_atr") is not None else None
    except (TypeError, ValueError):
        atr = None
    if atr and atr > 0:
        life["mfe_atr"] = round(mfe / atr, 4)
        life["mae_atr"] = round(mae / atr, 4)
    else:
        life["mfe_atr"] = None
        life["mae_atr"] = None

    # quality from gap / coverage
    started = float(life.get("observation_started_at") or now)
    elapsed = max(now - started, 1e-6)
    expected_ticks = max(elapsed / 45.0, 1.0)
    coverage = min(1.0, float(life["snapshot_count"]) / expected_ticks)
    life["observation_coverage_ratio"] = round(coverage, 4)
    max_gap = float(life.get("max_observation_gap_sec") or 0)
    if life["snapshot_count"] < 2 or coverage < 0.4 or max_gap > 180:
        life["mae_mfe_quality"] = "insufficient"
    elif coverage < 0.7 or max_gap > 90:
        life["mae_mfe_quality"] = "degraded"
    else:
        life["mae_mfe_quality"] = "good"


def _finalize_lifecycle_observation(meta: dict, net_pnl: float | None = None) -> dict:
    """در بستن: lifecycle را قفل و به result بچسبان (V.2.10.78)."""
    life = meta.get("lifecycle_observation")
    if not isinstance(life, dict):
        life = {}
    out = dict(life)
    out["observation_ended_at"] = time.time()
    if net_pnl is not None:
        try:
            out["net_pnl_at_close"] = round(float(net_pnl), 6)
        except (TypeError, ValueError):
            pass
    out["mfe_net_pct"] = out.get("max_favorable_excursion_pct")
    out["mae_net_pct"] = out.get("max_adverse_excursion_pct")
    out["MFE_R"] = out.get("mfe_r")
    out["MAE_R"] = out.get("mae_r")
    # carry entry overextension for close attribution
    eo = meta.get("entry_observation") if isinstance(meta.get("entry_observation"), dict) else {}
    if eo:
        out["entry_overextension_atr"] = eo.get("entry_overextension_atr")
        out["strong_symbol_bypass"] = eo.get("strong_symbol_bypass")
        out["bypass_reason"] = eo.get("bypass_reason")
        out["bypass_used"] = eo.get("bypass_used")
        out["entry_app_version"] = eo.get("app_version") or meta.get("app_version")
    out["close_app_version"] = APP_VERSION
    try:
        out["cross_version"] = bool(
            out.get("entry_app_version")
            and str(out.get("entry_app_version")) != str(APP_VERSION)
        )
    except Exception:
        out["cross_version"] = False
    meta["lifecycle_observation"] = out
    return out


def _unrealized_pct(direction: str, entry: float, price: float) -> float:
    if entry <= 0:
        return 0.0
    if direction == "long":
        return (price - entry) / entry * 100
    return (entry - price) / entry * 100


# V.2.10.39 — قفل بستن به ازای نماد (جلوگیری از double-close)
_close_locks: dict[str, asyncio.Lock] = {}


def _close_lock_for(key: str) -> asyncio.Lock:
    k = _norm_symbol(key)
    if k not in _close_locks:
        _close_locks[k] = asyncio.Lock()
    return _close_locks[k]


def _infer_exit_reason_from_levels(
    direction: str,
    entry: float,
    exit_price: float,
    stop_loss: float | None,
    target: float | None,
    meta: dict | None = None,
) -> str:
    """تخمین دلیل خروج وقتی صرافی بسته — نزدیک‌ترین سطح SL/TP + هم‌خوانی با PnL."""
    meta = meta or {}
    if not entry or not exit_price:
        return "external_or_unknown"
    d = (direction or "long").lower()

    def near(a: float, b: float) -> bool:
        if a <= 0 or b <= 0:
            return False
        return abs(a - b) / max(abs(a), abs(b)) <= 0.0035

    sl = float(stop_loss or 0) or float(meta.get("stop_loss") or 0)
    tp = float(target or 0) or float(meta.get("target") or 0)
    orig_sl = float(meta.get("original_stop_loss") or 0)
    pnl = _unrealized_pct(d, entry, exit_price)

    # نزدیک سطح TP — فقط اگر PnL منفی نباشد
    if tp and near(exit_price, tp):
        if pnl >= -0.02:
            return "exchange_take_profit"
        return "exchange_stop_loss_approx"
    # نزدیک سطح SL
    if sl and near(exit_price, sl):
        if meta.get("regime_sl_tightened") and orig_sl and not near(sl, orig_sl):
            return "regime_tightened_sl"
        if meta.get("profit_floor_set") and near(sl, float(meta.get("profit_floor_set") or 0)):
            return "profit_floor_sl"  # V.2.11.12
        if meta.get("breakeven_set") and near(sl, entry):
            return "breakeven_sl"
        if str(meta.get("exit_mode") or "").startswith("trail") and pnl > 0:   # V.2.18.6 — SL متحرک در سود
            return "rs_trail_stop"
        return "exchange_stop_loss"
    if orig_sl and near(exit_price, orig_sl):
        return "exchange_stop_loss"
    # V.2.18.5 — خروج «داخل» بازهٔ SL..TP و دور از هر دو ⇒ بستن دستی/خارج از ربات (قبلاً «SL/TP تقریبی» می‌شد).
    # خروج آن‌طرف SL (مثلاً SL با لغزش) همچنان SL حساب می‌شود تا قفل‌های پس از SL کار کنند.
    _sl_ref = sl or orig_sl
    if _sl_ref and tp and abs(pnl) >= 0.05:
        _inside = (_sl_ref < exit_price < tp) if d == "long" else (tp < exit_price < _sl_ref)
        if _inside:
            return "manual_or_external_close"
    if pnl >= 0.05:
        return "exchange_take_profit_approx"
    if pnl <= -0.05:
        return "exchange_stop_loss_approx"
    return "external_or_unknown"


def _outcome_class(exit_reason: str | None, pnl: float | None, scratch_abs: float = 0.10) -> str:
    """V.2.10.74.1 — WIN/LOSS/SCRATCH فقط از net PnL (بعد از fee اگر موجود).

    exit_reason دیگر کلاس را تعیین نمی‌کند (جلوگیری از WIN با PnL منفی /
    SCRATCH روی زیان بزرگ مثل stale_profit با −0.67).
    پارامتر exit_reason برای سازگاری امضا نگه داشته شده و نادیده گرفته می‌شود.
    """
    try:
        p = float(pnl) if pnl is not None else None
    except (TypeError, ValueError):
        p = None
    if p is None:
        return "UNKNOWN"
    if abs(p) <= float(scratch_abs):
        return "SCRATCH"
    if p > 0:
        return "WIN"
    return "LOSS"


def _reconcile_exit_reason_with_pnl(reason: str | None, pnl: float | None) -> tuple[str, str]:
    """
    V.2.10.54 — جلوگیری از برچسب TP روی باخت و SL روی برد.
    V.2.10.74 — خروج‌های داخلی ربات همیشه certain (نه unknown/soft مبهم).
    برمی‌گرداند (reason, confidence) با confidence در {certain, soft, approx, unknown}.
    """
    r = str(reason or "external_or_unknown")
    try:
        p = float(pnl) if pnl is not None else None
    except (TypeError, ValueError):
        p = None

    # خروج‌های تولیدشده توسط ربات — attribution قطعی
    internal_certain = {
        "profit_lock", "profit_lock_regime", "timeout", "float_profit_slot",
        "regime_soft_exit", "regime_adverse_loss_exit", "emergency_loss_cap", "manual_close", "manual_ui",
        "breakeven_sl", "regime_tightened_sl", "force_close_no_sl",
        "undersized_margin", "fallback_profit_close", "bot_close_unspecified",
        "stale_neutral_exit", "stale_flat_exit", "max_hold_force", "stale_profit_exit", "fill_invalidated_trade",
        "range_time_stop", "range_invalidated", "range_fail_exit", "range_small_tp", "range_profit_floor",
        "rs_time_stop", "tsmom_time_stop", "tsmom_trend_exit", "rsi_time_stop",
        "rs_trail_close", "rs_trail_stop", "sl_breach_no_exchange_sl",   # V.2.18.6
    }
    if r in internal_certain:
        # soft با PnL منفی فقط برای emergency/undersized/manual مجاز است؛
        # سود قفل‌شده با PnL منفی مشکوک → تخمین صرافی
        if p is not None and p < -0.01 and r in (
            "profit_lock", "profit_lock_regime", "float_profit_slot", "timeout", "regime_soft_exit",
        ):
            return "exchange_stop_loss_approx", "approx"
        return r, "certain"

    if r in ("exchange_take_profit", "exchange_take_profit_approx"):
        if p is not None and p < -0.01:
            return "exchange_stop_loss_approx", "approx"
        conf = "certain" if r == "exchange_take_profit" else "approx"
        return r, conf

    if r in ("exchange_stop_loss", "exchange_stop_loss_approx"):
        if p is not None and p > 0.05:
            return "exchange_take_profit_approx", "approx"
        conf = "certain" if r == "exchange_stop_loss" else "approx"
        return r, conf

    if r in ("exchange", ""):
        if p is not None and p < -0.01:
            return "exchange_stop_loss_approx", "approx"
        if p is not None and p > 0.05:
            return "exchange_take_profit_approx", "approx"
        return "external_or_unknown", "unknown"

    return r, "unknown"


def _exit_reason_from_client_order_id(client_order_id: str | None) -> str | None:
    """V.2.10.41 — اگر سفارش بستن با sd_c_<reason>_ ساخته شده باشد، دلیل قطعی است."""
    if not client_order_id:
        return None
    cid = str(client_order_id)
    if not cid.startswith("sd_c_"):
        # بستن ربات قدیمی بدون برچسب
        if cid.startswith("sd_"):
            return "bot_close_unspecified"
        return None
    body = cid[len("sd_c_"):]
    # reason_tag_hex
    tag = body.rsplit("_", 1)[0] if "_" in body else body
    mapping = {
        "profit_lock": "profit_lock",
        "profit_lock_regime": "profit_lock_regime",
        "regime_soft_exit": "regime_soft_exit",
        "float_profit_slot": "float_profit_slot",
        "emergency_loss_cap": "emergency_loss_cap",
        "timeout": "timeout",
        "manual_ui": "manual_close",
        "manual_close": "manual_close",
        "no_exchange_sl": "force_close_no_sl",
        "undersized_margin": "undersized_margin",
        "fallback_profit_close": "fallback_profit_close",
        "stale_neutral_exit": "stale_neutral_exit",
        "stale_profit_exit": "stale_profit_exit",
        "stale_flat_exit": "stale_flat_exit",
        "max_hold_force": "max_hold_force",
        "fill_invalidated_trade": "fill_invalidated_trade",
    }
    return mapping.get(tag, tag or None)



def _build_trade_autopsy(meta: dict | None, exit_reason: str | None, pnl: float | None, pnl_pct: float | None = None) -> dict:
    """V.2.10.88 — Trade Autopsy: چرا برد/باخت؟ فقط observation، بدون گیت.

    از فیلدهای ذخیره‌شده هنگام ورود/خروج می‌سازد؛ اگر داده نبود UNKNOWN/None.
    """
    m = meta if isinstance(meta, dict) else {}
    reason = str(exit_reason or m.get("exit_reason") or "")
    try:
        p = float(pnl) if pnl is not None else None
    except (TypeError, ValueError):
        p = None
    try:
        pp = float(pnl_pct) if pnl_pct is not None else (
            float(m["approx_pnl_pct"]) if m.get("approx_pnl_pct") is not None else None
        )
    except (TypeError, ValueError, KeyError):
        pp = None

    oc = str(m.get("outcome_class") or "")
    if not oc and p is not None:
        oc = _outcome_class(reason, p)

    direction = str(m.get("direction") or m.get("side") or "").lower()
    if direction in ("buy", "buy_open"):
        direction = "long"
    elif direction in ("sell", "sell_open"):
        direction = "short"

    # --- Trend at entry ---
    stack = str(m.get("entry_stack") or m.get("ema_stack_1h") or m.get("stack") or "").lower()
    regime = str(m.get("entry_regime") or m.get("regime_label") or m.get("regime") or "").upper()
    try:
        adx = float(m["entry_adx"] if m.get("entry_adx") is not None else m.get("regime_adx") or m.get("adx_1h") or 0)
    except (TypeError, ValueError):
        adx = 0.0
    try:
        er = float(m["entry_er"] if m.get("entry_er") is not None else m.get("regime_er") or m.get("er") or 0)
    except (TypeError, ValueError):
        er = 0.0
    try:
        score = float(m.get("score") or m.get("confluence_score") or 0)
    except (TypeError, ValueError):
        score = 0.0

    trend_aligned = None
    if direction in ("long", "short") and (stack or regime):
        bullish = ("bull" in stack) or ("TREND" in regime and "BEAR" not in regime) or regime in ("TREND_OK", "TREND")
        bearish = ("bear" in stack) or ("BEAR" in regime)
        if direction == "long":
            trend_aligned = bool(bullish and not bearish) if (bullish or bearish) else None
        else:
            trend_aligned = bool(bearish) if (bullish or bearish) else None
    if trend_aligned is None and adx >= 25 and score >= 90:
        trend_aligned = True  # soft: strong structure without stack

    # --- Entry late / chase ---
    entry_late = False
    over_flag = m.get("overextension") or m.get("overextension_flag") or m.get("entry_overextension")
    try:
        oe_atr = float(m.get("overextension_atr") or m.get("entry_overextension_atr") or 0)
    except (TypeError, ValueError):
        oe_atr = 0.0
    if over_flag in (True, "true", "1", 1) or oe_atr >= 1.25:
        entry_late = True

    # --- SL tightness ---
    sl_tight = None
    try:
        entry = float(m.get("entry") or m.get("fill_entry") or m.get("avg_entry") or 0)
        sl = float(m.get("stop_loss") or m.get("sl") or 0)
        if entry > 0 and sl > 0:
            sl_dist = abs(entry - sl) / entry * 100.0
            sl_tight = sl_dist < 0.45  # نزدیک کف min_sl
            sl_dist_pct = round(sl_dist, 3)
        else:
            sl_dist_pct = None
    except (TypeError, ValueError):
        sl_dist_pct = None

    # --- Exit family ---
    soft_exit = reason in (
        "float_profit_slot", "profit_lock", "profit_lock_regime", "stale_profit_exit",
        "stale_neutral_exit", "stale_flat_exit", "timeout", "max_hold_force", "regime_soft_exit",
    )
    hard_sl = "stop_loss" in reason or reason in ("sl", "breakeven_sl", "emergency_loss_cap", "regime_tightened_sl")
    hard_tp = "take_profit" in reason

    # --- Regime change (if both entry and close snapshots exist) ---
    regime_changed = None
    entry_reg = str(m.get("entry_regime") or "").upper()
    close_reg = str(m.get("close_regime") or m.get("regime_at_close") or "").upper()
    if entry_reg and close_reg and entry_reg != close_reg:
        regime_changed = True
    elif entry_reg and close_reg:
        regime_changed = False

    # --- Primary factors ---
    factors: list[str] = []
    if oc == "WIN":
        if soft_exit:
            factors.append("exit_soft_profit")
        if hard_tp:
            factors.append("hit_tp")
        if trend_aligned is True:
            factors.append("trend_aligned")
        if not entry_late:
            factors.append("entry_not_chased")
        if not factors:
            factors.append("net_positive")
    elif oc == "LOSS":
        if hard_sl:
            factors.append("hit_sl")
        if entry_late:
            factors.append("entry_late_chase")
        if trend_aligned is False:
            factors.append("trend_misaligned")
        if regime_changed:
            factors.append("regime_changed")
        if sl_tight is True:
            factors.append("sl_relatively_tight")
        if not factors:
            factors.append("net_negative")
    else:
        factors.append("scratch_or_near_zero")

    # --- Persian summary ---
    parts: list[str] = []
    if oc == "WIN":
        parts.append("برد")
        if soft_exit:
            parts.append("خروج نرم/قفل‌سود")
        elif hard_tp:
            parts.append("رسیدن به TP")
        if trend_aligned is True:
            parts.append("روند هم‌جهت ورود")
        if entry_late:
            parts.append("ولی ورود نسبتاً دیر/کشیده بود")
    elif oc == "LOSS":
        parts.append("باخت")
        if hard_sl:
            parts.append("اصابت SL")
        if entry_late:
            parts.append("ورود دیر/تعقیب")
        if trend_aligned is False:
            parts.append("روند با جهت هم‌خوان نبود")
        if regime_changed:
            parts.append("رژیم نسبت به ورود عوض شد")
        if sl_tight is True:
            parts.append("فاصله SL نسبتاً تنگ")
    else:
        parts.append("تقریباً صفر/اسکرچ")
        if soft_exit:
            parts.append("خروج نرم نزدیک صفر")

    summary_fa = " · ".join(parts) if parts else "داده ناکافی برای تشریح"

    return {
        "version": "V.2.10.88",
        "outcome": oc or "UNKNOWN",
        "trend_aligned": trend_aligned,
        "entry_late": entry_late,
        "sl_tight": sl_tight,
        "sl_dist_pct": sl_dist_pct,
        "regime_changed": regime_changed,
        "exit_family": (
            "soft" if soft_exit else
            "hard_sl" if hard_sl else
            "hard_tp" if hard_tp else
            "other"
        ),
        "entry_score": score or None,
        "entry_adx": adx or None,
        "entry_er": er or None,
        "overextension_atr": oe_atr or None,
        "factors": factors,
        "summary_fa": summary_fa,
        "note": "observation_only — not an entry gate",
    }


async def _close_tracked(key: str, reason: str, price: float | None = None) -> dict[str, Any]:
    """بستن مارکت یک پوزیشن ردیابی‌شده و ثبت PnL تقریبی (idempotent + lock)."""
    key = _norm_symbol(key)
    lock = _close_lock_for(key)
    async with lock:
        meta = _tracked.get(key)
        if not meta or meta.get("status") != "open":
            return {"ok": False, "reason": "not open", "idempotent": True}
        if meta.get("closing"):
            return {"ok": False, "reason": "already closing", "idempotent": True}
        meta["closing"] = True

        direction = meta["direction"]
        qty = str(meta.get("quantity") or "0")
        entry = float(meta["entry"])

        if price is None:
            try:
                info = await toobit_market.get_live_price(key)
                price = float(info.get("price") or entry)
            except Exception:
                price = entry

        # V.2.10.41 — clientOrderId با برچسب دلیل برای طبقه‌بندی قطعی بعد از ری‌استارت
        reason_tag = str(reason or "unknown").replace(" ", "_")[:24]
        close_cid = f"sd_c_{reason_tag}_{uuid.uuid4().hex[:10]}"
        meta["close_client_order_id"] = close_cid
        # V.2.18.4 — اول limitهای بستن (maker TP) لغو شوند؛ وگرنه مقدار قفل است و بستن مارکت رد می‌شود
        try:
            _rl = await _release_close_limits(key, meta)
            if _rl.get("canceled"):
                await asyncio.sleep(0.4)
        except Exception as _rle:
            logger.debug("release close limits %s: %s", key, _rle)
        try:
            result = await toobit_private.close_position_market(
                key, direction, qty, client_order_id=close_cid
            )
        except Exception as _cpe:   # V.2.18.5 — بدون این، closing=True می‌ماند و هیچ بستن بعدی انجام نمی‌شد
            result = {"error": f"exception: {str(_cpe)[:160]}"}
        if not isinstance(result, dict):
            result = {"error": "bad response"}
        if result.get("error"):
            meta["closing"] = False
            logger.warning("REAL CLOSE failed %s: %s", key, result)
            return {"ok": False, "reason": "exchange close failed", "exchange": result}

        # V.2.10.55 — ترجیح Fill واقعی entry برای PnL تقریبی
        entry_for_pnl = float(meta.get("fill_entry") or meta.get("entry") or entry)
        pnl_pct = _unrealized_pct(direction, entry_for_pnl, price)
        await _cancel_maker_tp(meta)  # V.2.12.3
        _sample_price_path(meta, price)  # V.2.10.100 — نقطهٔ خروج
        meta["close_reason_requested"] = str(reason)
        margin = float(meta.get("margin_usdt") or 0)
        approx_pnl = margin * LEVERAGE * (pnl_pct / 100)

        # تلاش برای خواندن Realized PnL واقعی از تاریخچه صرافی
        realized_pnl = None
        realized_fees = None
        exit_fill = None
        try:
            await asyncio.sleep(0.6)
            hist = await toobit_private.get_history_positions(limit=15)
            rows = []
            if isinstance(hist, dict):
                raw = hist.get("data") or hist.get("list") or hist.get("positions") or hist
                if isinstance(raw, list):
                    rows = raw
                elif isinstance(raw, dict):
                    for k in ("data", "list", "positions"):
                        if isinstance(raw.get(k), list):
                            rows = raw[k]
                            break
            # V.2.10.56 — Match دقیق با price/qty/time (نه فقط اولین CLOSED هم‌نماد)
            try:
                qty_f = float(meta.get("quantity") or 0)
            except (TypeError, ValueError):
                qty_f = 0.0
            fill_e = None
            try:
                fill_e = float(meta.get("fill_entry") or meta.get("entry") or 0) or None
            except (TypeError, ValueError):
                fill_e = None
            opened_at = None
            try:
                opened_at = float(meta.get("opened_at") or 0) or None
            except (TypeError, ValueError):
                opened_at = None
            closed_after = time.time() - 120  # پنجره نزدیک به close
            matched = _match_history_row(
                rows,
                key,
                fill_entry=fill_e,
                qty=qty_f if qty_f > 0 else None,
                opened_at=opened_at,
                closed_after=closed_after,
            )
            if matched:
                r = matched
                try:
                    rp = r.get("realizedPnL")
                    if rp is None or rp == "":
                        rp = r.get("realizedPnl")
                    if rp is not None and rp != "":
                        realized_pnl = float(rp)
                    fo = abs(float(r.get("openFee") or 0))
                    fc = abs(float(r.get("closeFee") or 0))
                    realized_fees = fo + fc
                    exit_fill = float(
                        r.get("closeAvgPrice") or r.get("closePrice") or 0
                    ) or None
                    meta["history_match"] = {
                        "openAvgPrice": r.get("openAvgPrice"),
                        "closeAvgPrice": r.get("closeAvgPrice"),
                        "closeTotalQty": r.get("closeTotalQty"),
                        "id": r.get("id"),
                    }
                except (TypeError, ValueError):
                    pass
        except Exception as e:
            logger.warning("close realized fetch failed %s: %s", key, e)

        final_pnl = float(realized_pnl) if realized_pnl is not None else float(approx_pnl)
        record_realized_pnl(final_pnl)
        meta["approx_pnl"] = round(approx_pnl, 6)
        meta["realized_pnl"] = round(final_pnl, 6) if realized_pnl is not None else None
        meta["pnl_source"] = "exchange" if realized_pnl is not None else "approx"
        if realized_fees is not None:
            meta["fees"] = round(realized_fees, 6)
        if exit_fill:
            meta["exit_fill"] = exit_fill
            price = exit_fill

        # نرمال‌سازی نام دلیل خروج برای آمار
        reason_norm = str(reason or "unknown")
        _reason_map = {
            "profit_lock": "profit_lock",
            "profit_lock_regime": "profit_lock_regime",
            "regime_soft_exit": "regime_soft_exit",
            "float_profit_slot": "float_profit_slot",
            "emergency_loss_cap": "emergency_loss_cap",
            "timeout": "timeout",
            "stale_profit_exit": "stale_profit_exit",
        "stale_flat_exit": "stale_flat_exit",
        "max_hold_force": "max_hold_force",
            "stale_neutral_exit": "stale_neutral_exit",
            "manual_ui": "manual_close",
            "no_exchange_sl": "force_close_no_sl",
            "undersized_margin": "undersized_margin",
        }
        reason_norm = _reason_map.get(reason_norm, reason_norm)

        meta["status"] = "closed"
        meta["exit_reason"] = reason_norm
        meta["exit_price"] = price
        meta["closed_at"] = time.time()
        meta["closing"] = False
        # V.2.10.74 — خروج داخلی ربات: confidence قطعی + کلاس نتیجه
        meta["reason_confidence"] = "certain"
        try:
            meta["outcome_class"] = _outcome_class(
                reason_norm,
                float(meta.get("realized_pnl") if meta.get("realized_pnl") is not None else meta.get("approx_pnl") or 0),
            )
        except Exception:
            meta["outcome_class"] = "UNKNOWN"
        try:
            _pnl_a = float(
                meta.get("realized_pnl")
                if meta.get("realized_pnl") is not None
                else meta.get("approx_pnl")
                if meta.get("approx_pnl") is not None
                else approx_pnl
            )
            meta["autopsy"] = _build_trade_autopsy(meta, reason_norm, _pnl_a, None)
        except Exception as _ae:
            meta["autopsy"] = {"error": str(_ae)[:80], "note": "observation_only"}
        # V.2.10.77 — قفل observation چرخه عمر روی بستن
        try:
            _finalize_lifecycle_observation(
                meta,
                float(meta.get("realized_pnl") if meta.get("realized_pnl") is not None else meta.get("approx_pnl") or 0),
            )
        except Exception:
            pass
        # V.2.10.62 — attribution: نسخهٔ باز اگر نبود، نسخهٔ بستن؛ همیشه app_version_close
        if not meta.get("app_version"):
            meta["app_version"] = APP_VERSION
        meta["app_version_close"] = APP_VERSION
        if not meta.get("settings_snapshot"):
            meta["settings_snapshot"] = {
                "app_version": APP_VERSION,
                "min_confluence": MIN_CONFLUENCE_REAL,
                "min_rr": MIN_RR_REAL,
                "max_hold_seconds": MAX_HOLD_SECONDS,
                "stale_profit_min_pct": STALE_PROFIT_MIN_PCT,
                "leverage": LEVERAGE,
            }
        _snap = {}
        try:
            if meta.get("regime_er") is not None:
                _snap["er"] = float(meta["regime_er"])
            if meta.get("regime_adx") is not None:
                _snap["adx"] = float(meta["regime_adx"])
        except Exception:
            _snap = {}
        _pnl_for_cd = None
        try:
            _pnl_for_cd = float(
                meta.get("realized_pnl")
                if meta.get("realized_pnl") is not None
                else meta.get("approx_pnl")
                if meta.get("approx_pnl") is not None
                else approx_pnl
            )
        except Exception:
            _pnl_for_cd = None
        _mark_symbol_closed(key, reason_norm, regime_snapshot=_snap or None, pnl=_pnl_for_cd)
        try:
            _record_attempt(key, False, "بسته شد — کول‌داون پس از بستن",
                            direction=direction, exit_reason=reason_norm)
        except Exception:
            pass
        if meta.get("approx_pnl") is None:
            meta["approx_pnl"] = round(approx_pnl, 4)
        try:
            _register_closed_trade(
                key,
                float(meta.get("realized_pnl") if meta.get("realized_pnl") is not None else meta.get("approx_pnl") or 0),
                str(reason_norm or ""),
            )
        except Exception:
            pass
        meta["approx_pnl_pct"] = round(pnl_pct, 4)

        _history.insert(0, dict(meta))
        if len(_history) > 300:
            del _history[300:]

        logger.info(
            "REAL CLOSED %s reason=%s price=%.6f pnl≈%.4f (%.2f%%) ver=%s",
            key, reason_norm, price, approx_pnl, pnl_pct, meta.get("app_version"),
        )
        print(
            f"[real_trade] CLOSED {key} reason={reason_norm} price={price} "
            f"pnl≈{approx_pnl:.4f} ({pnl_pct:.2f}%) ver={meta.get('app_version')}",
            flush=True,
        )

        try:
            _save_tracked()
        except Exception as e:
            logger.warning("save tracked after close failed: %s", e)

        try:
            from database.supabase_client import update_real_trade
            tid = meta.get("trade_id")
            if tid:
                await update_real_trade(tid, meta)
        except Exception as e:
            logger.warning("persist close real trade failed: %s", e)

        return {
            "ok": True,
            "symbol": key,
            "reason": reason_norm,
            "approx_pnl": approx_pnl,
            "price": price,
            "app_version": meta.get("app_version"),
        }




async def close_real_position(symbol: str) -> dict[str, Any]:
    """بستن دستی از UI — market close + کول‌داون پس از بستن."""
    key = _norm_symbol(symbol)
    meta = _tracked.get(key)
    if meta and meta.get("status") == "open":
        return await _close_tracked(key, "manual_ui")
    # پوزیشن روی صرافی هست ولی tracked نیست (بعد از ریستارت)
    try:
        positions = await toobit_private.get_positions()
    except Exception as e:
        return {"ok": False, "reason": f"positions fetch failed: {e}"}
    rows = positions if isinstance(positions, list) else (positions.get("data") or positions.get("positions") or [])
    if not isinstance(rows, list):
        rows = []
    target = None
    for p in rows:
        sym = _norm_symbol(str(p.get("symbol") or ""))
        if sym != key:
            continue
        qty = abs(float(p.get("position") or p.get("positionAmt") or p.get("available") or 0))
        if qty <= 0:
            continue
        side = str(p.get("side") or "").upper()
        direction = "long" if ("LONG" in side or float(p.get("position") or 0) > 0) else "short"
        if "SHORT" in side:
            direction = "short"
        target = {"qty": qty, "direction": direction, "entry": float(p.get("avgPrice") or 0)}
        break
    if not target:
        return {"ok": False, "reason": "no open position on exchange"}
    # V.2.10.56: seed tracked موقت تا close از ledger واحد رد شود
    if key not in _tracked or _tracked.get(key, {}).get("status") != "open":
        _tracked[key] = {
            "trade_id": f"recover_manual_{key}_{uuid.uuid4().hex[:8]}",
            "symbol": key,
            "direction": target["direction"],
            "entry": float(target.get("entry") or 0),
            "fill_entry": float(target.get("entry") or 0) or None,
            "signal_entry": float(target.get("entry") or 0) or None,
            "stop_loss": 0.0,
            "target": 0.0,
            "quantity": str(target["qty"]),
            "margin_usdt": 0.0,
            "opened_at": time.time(),
            "status": "open",
            "age_unknown": True,
            "app_version": APP_VERSION,
        }
    return await _close_tracked(key, "manual_ui")


MFE_SAVE_INTERVAL_SEC = 180


async def _rs_exit_manage(key: str, meta: dict, direction: str, price: float, entry_px: float,
                          sl_pct0: float) -> dict | None:
    """V.2.18.6 — be1r / trail50*: با بیشترین سود دیده‌شده (نمونهٔ هر دور مدیر) SL هدف را حساب کن؛
    اگر سفت‌تر از SL فعلی است ⇒ روی صرافی (attach_tpsl_and_verify، فقط سفت‌تر). اگر قیمت از SL هدف گذشته ⇒ بستن."""
    import backtest_exits as _bx
    if not meta.get("exit_mode"):   # V.2.18.8 — پوزیشن بازیابی‌شده بعد از دیپلوی (قبلاً exit_mode ذخیره نمی‌شد)
        _fam = str(meta.get("strategy_id") or "")
        meta["exit_mode"] = _exit_mode(_fam, str(direction).lower()) if _fam in ("rel_strength", "rs_intraday_50") else "base"
        meta["exit_mode_restored"] = True
    mode_name = str(meta.get("exit_mode") or "base")
    mode = _bx.EXIT_MODES.get(mode_name) or {}
    if mode.get("be_r") is None and mode.get("trail_from_r") is None:
        return None
    long_ = str(direction).lower() != "short"
    sign = 1.0 if long_ else -1.0
    move = sign * (float(price) / float(entry_px) - 1.0) * 100.0
    _mfe_prev = float(meta.get("mfe_live_pct") or 0.0)
    meta["mfe_live_pct"] = round(max(_mfe_prev, move), 4)
    # V.2.18.10 — بیشترین سود هر ۳ دقیقه (اگر بیشتر شده) در Supabase ⇒ بعد از دیپلوی صفر نمی‌شود
    if meta["mfe_live_pct"] > float(meta.get("mfe_saved_pct") or 0.0) + 0.05 \
            and time.time() - float(meta.get("mfe_saved_ts") or 0) >= MFE_SAVE_INTERVAL_SEC:
        meta["mfe_saved_pct"] = meta["mfe_live_pct"]
        meta["mfe_saved_ts"] = time.time()
        try:
            _save_tracked()
            from database.supabase_client import upsert_open_real_trade
            await upsert_open_real_trade(meta)
        except Exception:
            pass
    fee = abs(float(ROUND_TRIP_FRICTION_PCT))
    tgt = _bx.mode_sl_target(direction, float(entry_px), float(sl_pct0), float(meta["mfe_live_pct"]), mode, fee)
    if tgt is None:
        return None
    try:
        cur = float(meta.get("stop_loss") or 0)
    except (TypeError, ValueError):
        cur = 0.0
    tighter = (tgt > cur * 1.0005) if long_ else (cur <= 0 or tgt < cur * 0.9995)
    if not tighter:
        return None
    if (long_ and price <= tgt) or ((not long_) and price >= tgt):   # قیمت همین حالا از SL هدف گذشته
        meta["exit_decision"] = {"reason": "rs_trail_close", "mode": mode_name, "sl_target": tgt,
                                 "mfe_pct": meta["mfe_live_pct"], "pnl_pct": round(move, 4)}
        res = await _close_tracked(key, "rs_trail_close", price)
        return {"action": "rs_trail_close", "closed": bool((res or {}).get("ok")), "mode": mode_name, "sl_target": tgt}
    if time.time() - float(meta.get("rs_exit_move_ts") or 0) < 60:
        return None
    meta["rs_exit_move_ts"] = time.time()
    r = await toobit_private.attach_tpsl_and_verify(key, direction, str(meta.get("target") or "") or None, str(tgt),
                                                    str(meta.get("quantity") or "") or None)
    ok_ = bool((r or {}).get("verified"))
    if ok_:
        _log_sl_change(meta, cur, float(r.get("exchange_sl") or tgt), f"rs_{mode_name}", price=price, verified=True,
                       extra={"mfe_pct": meta["mfe_live_pct"]})
        meta["stop_loss"] = float(r.get("exchange_sl") or tgt)
        meta["sl_on_exchange"] = True
        if mode.get("be_r") is not None:
            meta["breakeven_set"] = True
        try:
            _save_tracked()
        except Exception:
            pass
        try:   # V.2.18.8 — بعد از دیپلوی هم بماند
            from database.supabase_client import upsert_open_real_trade
            await upsert_open_real_trade(meta)
        except Exception:
            pass
    return {"action": f"rs_sl_{mode_name}", "ok": ok_, "sl": tgt, "mfe_pct": meta["mfe_live_pct"]}


SL_GUARD_MAX_REATTACH = 1   # V.2.18.5 — یک تلاش؛ نشد ⇒ بستن (نگهبان‌های دیگر هم همین را می‌کنند)
SL_MISSING_CONFIRM_SEC = 90   # V.2.18.5


async def _exchange_sl_guard(key: str, meta: dict, direction: str, price: float, elapsed: float) -> dict | None:
    """V.2.18.4 — SL صرافی برای این نماد پیدا نشد (sl_missing_since):
    قیمت به SL رسیده/گذشته ⇒ بستن فوری؛ وگرنه limitهای بستن آزاد و SL دوباره ثبت (حداکثر ۳ بار)؛ نشد ⇒ بستن."""
    since = meta.get("sl_missing_since")
    if not since or elapsed < float(MAX_SECONDS_WITHOUT_EXCHANGE_SL) or time.time() - float(since) < SL_MISSING_CONFIRM_SEC:
        return None
    try:
        sl_px = float(meta.get("stop_loss") or meta.get("initial_sl") or 0)
    except (TypeError, ValueError):
        sl_px = 0.0
    long_ = str(direction).lower() != "short"
    beyond = sl_px > 0 and ((long_ and price <= sl_px) or ((not long_) and price >= sl_px))
    if beyond:
        res = await _close_tracked(key, "sl_breach_no_exchange_sl", price)
        return {"action": "sl_breach_no_exchange_sl", "closed": bool((res or {}).get("ok")), "sl": sl_px, "price": price}
    n = int(meta.get("sl_reattach_n") or 0)
    if n >= SL_GUARD_MAX_REATTACH:
        res = await _close_tracked(key, "no_exchange_sl", price)
        return {"action": "force_close_no_sl", "closed": bool((res or {}).get("ok")), "reattach_tries": n}
    meta["sl_reattach_n"] = n + 1
    meta["sl_reattach_ts"] = time.time()
    try:
        await _release_close_limits(key, meta)
        tp = meta.get("target")
        r = await toobit_private.attach_tpsl_and_verify(key, direction, str(tp) if tp else None, str(sl_px) if sl_px else None,
                                                        str(meta.get("quantity") or "") or None)
        ok_ = bool((r or {}).get("verified") or (r or {}).get("sl_on_exchange"))
        if ok_:
            meta["sl_on_exchange"] = True
            meta.pop("sl_missing_since", None)
            meta["sl_reattach_n"] = 0
            meta["sl_reattach_ok_total"] = int(meta.get("sl_reattach_ok_total") or 0) + 1
            return {"action": "sl_reattach", "ok": True, "sl": sl_px}
        res = await _close_tracked(key, "no_exchange_sl", price)
        return {"action": "force_close_no_sl", "closed": bool((res or {}).get("ok")), "reattach_failed": True}
    except Exception as e:
        return {"action": "sl_reattach", "ok": False, "try": n + 1, "error": str(e)[:120]}


TPSL_DEDUPE_MIN_INTERVAL_SEC = 120
TPSL_DEDUPE_MAX_FAILS = 3   # V.2.18.8


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def _dedupe_tpsl(key: str, meta: dict, orders: list[dict]) -> dict | None:
    """V.2.18.7 — اگر برای یک نماد بیش از یک SL یا TP شرطی هست: سخت‌ترین SL (لانگ: بالاترین) و TP نزدیک‌ترین به هدف
    نگه داشته و بقیه لغو می‌شوند. ایمنی: فقط اگر سفارشِ نگه‌داشته کل مقدار پوزیشن را پوشش دهد؛ بعد از لغو دوباره خوانده
    می‌شود و اگر SL نماند فوراً دوباره ثبت می‌شود."""
    now = time.time()
    if now - float(meta.get("tpsl_dedupe_ts") or 0) < TPSL_DEDUPE_MIN_INTERVAL_SEC:
        return None
    meta["tpsl_dedupe_ts"] = now
    long_ = str(meta.get("direction") or "long").lower() != "short"
    pos_qty = _f(meta.get("quantity")) or 0.0
    sls = [o for o in orders if str(o.get("kind")) == "sl" and _f(o.get("stopPrice")) and o.get("orderId")]
    tps = [o for o in orders if str(o.get("kind")) == "tp" and _f(o.get("stopPrice")) and o.get("orderId")]
    out: dict[str, Any] = {"ts": now, "canceled": [], "kept": {}}

    def covers(o):
        q = _f(o.get("origQty"))
        return q is None or pos_qty <= 0 or q + 1e-12 >= pos_qty

    drop: list[dict] = []
    if len(sls) > 1:
        keep = (max if long_ else min)(sls, key=lambda o: _f(o.get("stopPrice")))
        if not covers(keep):
            out["skip_sl"] = "سخت‌ترین SL کل مقدار را پوشش نمی‌دهد — لغو نشد"
        else:
            out["kept"]["sl"] = keep.get("stopPrice")
            drop += [o for o in sls if o is not keep]
    if len(tps) > 1:
        tgt = _f(meta.get("target"))
        keep_t = min(tps, key=lambda o: abs(_f(o.get("stopPrice")) - tgt)) if tgt else \
            (min if long_ else max)(tps, key=lambda o: _f(o.get("stopPrice")))
        if covers(keep_t):
            out["kept"]["tp"] = keep_t.get("stopPrice")
            drop += [o for o in tps if o is not keep_t]
    if not drop:
        meta["tpsl_dedupe"] = out
        return out
    if int(meta.get("tpsl_dedupe_fail_n") or 0) >= TPSL_DEDUPE_MAX_FAILS:
        out["skip"] = "لغو روی صرافی چند بار بی‌اثر بود — دیگر تلاش نمی‌شود (تکراری‌ها بی‌خطرند: سخت‌ترین SL زودتر فعال می‌شود)"
        meta["tpsl_dedupe"] = out
        return out
    # V.2.18.8 — اول DELETE /futures/order با type=STOP؛ بعد cancelOrderByIds؛ نتیجه فقط با خواندن دوباره تأیید می‌شود
    resp: dict[str, Any] = {}
    for o in drop:
        oid = str(o.get("orderId"))
        try:
            resp[oid] = await toobit_private.cancel_stop_order(key, oid)
        except Exception as e:
            resp[oid] = {"error": str(e)[:120]}
    out["responses"] = {k: str(v)[:160] for k, v in resp.items()}
    out["canceled"] = []
    try:
        await asyncio.sleep(2.0)   # V.2.18.9 — لغو روی توبیت با تأخیر اعمال می‌شود
        chk = toobit_private.parse_tpsl_orders(await toobit_private.get_open_orders(key, "STOP_PROFIT_LOSS"), key)
        still = {str(o.get("orderId")) for o in (chk.get("orders") or [])} & {str(o.get("orderId")) for o in drop}
        if still:
            r2 = await toobit_private.cancel_orders_by_ids(sorted(still))
            out["responses_by_ids"] = str(r2)[:160]
            await asyncio.sleep(0.6)
            chk = toobit_private.parse_tpsl_orders(await toobit_private.get_open_orders(key, "STOP_PROFIT_LOSS"), key)
            still = {str(o.get("orderId")) for o in (chk.get("orders") or [])} & still
        out["canceled"] = [{"orderId": o.get("orderId"), "kind": o.get("kind"), "stopPrice": o.get("stopPrice")}
                           for o in drop if str(o.get("orderId")) not in still]
        if still:
            out["cancel_failed"] = sorted(still)
            meta["tpsl_dedupe_fail_n"] = int(meta.get("tpsl_dedupe_fail_n") or 0) + 1
        out["sl_after"] = bool(chk.get("sl_on_exchange"))
        if not chk.get("sl_on_exchange") and out["kept"].get("sl"):
            rr = await toobit_private.attach_tpsl_and_verify(key, str(meta.get("direction") or "long"),
                                                             str(out["kept"].get("tp") or meta.get("target") or "") or None,
                                                             str(out["kept"]["sl"]), str(meta.get("quantity") or "") or None)
            out["sl_reattached"] = bool((rr or {}).get("verified") or (rr or {}).get("sl_on_exchange"))
    except Exception as e:
        out["check_error"] = str(e)[:120]
    meta["tpsl_dedupe"] = out
    return out


async def _sync_levels_from_exchange(key: str, meta: dict[str, Any]) -> None:
    """هم‌سان‌سازی stop_loss/target نمایشی با سفارش‌های واقعی صرافی."""
    if not meta or meta.get("status") != "open":
        return
    try:
        insp = await toobit_private.inspect_account()
    except Exception as e:
        logger.debug("inspect for SL sync failed: %s", e)
        return
    _tp_block = (insp or {}).get("tpsl_orders") or {}
    orders = _tp_block.get("orders") or []
    if not isinstance(orders, list) or _tp_block.get("error"):
        return
    key_u = _norm_symbol(key)
    is_long = str(meta.get("direction") or "long").lower() != "short"
    sls: list[float] = []
    tps: list[float] = []
    for o in orders:
        try:
            sym = _norm_symbol(str(o.get("symbol") or ""))
            if sym != key_u:
                continue
            sp = o.get("stopPrice")
            if sp in (None, ""):
                continue
            price = float(sp)
            kind = str(o.get("kind") or o.get("orderType") or "").lower()
            if "loss" in kind or kind == "sl":
                sls.append(price)
            elif "profit" in kind or kind == "tp":
                tps.append(price)
        except Exception:
            continue
    # V.2.11.0: چند SL هم‌زمان (مثلاً SL دستی کنار SL ربات) → سخت‌ترین؛ لاگ فقط با تغییر واقعی (بدون رفت‌وبرگشت)
    if len(sls) > 1 or len(tps) > 1:   # V.2.18.7 — TP/SL تکراری روی صرافی (مثلاً بعد از تنظیم دوباره بعد از fill)
        try:
            _dd = await _dedupe_tpsl(key_u, meta, [o for o in orders if _norm_symbol(str(o.get("symbol") or "")) == key_u])
            if _dd and _dd.get("canceled"):
                return   # دور بعد با سفارش‌های تمیزشده دوباره هم‌سان می‌شود
        except Exception as _dde:
            logger.debug("tpsl dedupe %s: %s", key_u, _dde)
    if sls:
        price = max(sls) if is_long else min(sls)
        try:
            _prev = float(meta.get("stop_loss") or 0)
            if _prev > 0 and abs(_prev - price) / _prev > 0.0008:
                _log_sl_change(meta, _prev, price, "exchange_sync", verified=True,
                               extra={"n_sl_orders": len(sls)} if len(sls) > 1 else None)
        except (TypeError, ValueError):
            pass
        meta["stop_loss"] = price
        meta["sl_on_exchange"] = True
        meta.pop("sl_missing_since", None)
        if len(sls) > 1:
            meta["sl_orders_on_exchange"] = sorted(sls)
    else:
        # V.2.18.4 — قبلاً اینجا هیچ کاری نمی‌شد و پرچم «SL روی صرافی» از قبل True می‌ماند (OP بدون SL ماند)
        # V.2.18.5 — فقط اگر ≥ ۹۰ ثانیه پشت‌سرهم نبود (یک خواندن خالی/گذرا ⇒ بستن نه)
        meta.setdefault("sl_missing_since", time.time())
        if time.time() - float(meta.get("sl_missing_since") or time.time()) >= SL_MISSING_CONFIRM_SEC:
            meta["sl_on_exchange"] = False
    if tps:
        meta["target"] = min(tps) if is_long else max(tps)
        meta["tp_on_exchange"] = True



_regime_cache: dict[str, tuple[float, dict]] = {}


async def _get_regime_snapshot(symbol: str) -> dict:
    """اسنپ‌شات سبک رژیم با کش کوتاه — برای soft-exit مدیر."""
    import indicators
    now = time.time()
    key = _norm_symbol(symbol)
    hit = _regime_cache.get(key)
    if hit and (now - hit[0]) < REGIME_EXIT_CACHE_SEC:
        return hit[1]
    out = {
        "regime_label": None,
        "regime_confidence": None,
        "ema_stack_1h": None,
        "adverse": False,
        "detail": "",
    }
    try:
        cand = await indicators.generate_candidate_signal(key)
        block = (cand or {}).get("relaxed") or (cand or {}).get("strict") or {}
        diag = block.get("diagnostics") or {}
        out["regime_label"] = diag.get("regime_label")
        out["regime_confidence"] = diag.get("regime_confidence")
        out["ema_stack_1h"] = diag.get("ema_stack_1h")
        out["detail"] = str(diag.get("regime_detail") or "")[:120]
    except Exception as e:
        out["error"] = str(e)[:100]
    _regime_cache[key] = (now, out)
    return out


def _regime_adverse_to_position(direction: str, snap: dict) -> bool:
    """آیا رژیم خلاف جهت پوزیشن است؟ (برای soft-exit سود — فقط stack مخالف)"""
    if not snap or snap.get("error"):
        return False
    conf = snap.get("regime_confidence")
    try:
        conf_f = float(conf) if conf is not None else 0.0
    except (TypeError, ValueError):
        conf_f = 0.0
    if conf_f < REGIME_EXIT_MIN_CONF:
        return False
    stack = str(snap.get("ema_stack_1h") or "").lower()
    d = (direction or "").lower()
    if d == "long" and stack == "bear":
        return True
    if d == "short" and stack == "bull":
        return True
    return False


def _btc_hostile_to_direction(direction: str) -> bool:
    """V.2.10.89 — BTC WEAK/CHOP یا stack مخالف."""
    if not REGIME_ADVERSE_BTC_HOSTILE:
        return False
    d = (direction or "").lower()
    label = stack = conf = None
    try:
        label, conf, stack = _fetch_btc_regime_for_gate(None)
    except Exception:
        try:
            from indicators import get_btc_regime_snapshot
            snap = get_btc_regime_snapshot() or {}
            label = snap.get("label") or snap.get("regime_label")
            stack = snap.get("ema_stack_1h") or snap.get("stack")
            conf = snap.get("confidence")
        except Exception:
            return False
    lab = str(label or "").upper()
    st = str(stack or "").lower()
    try:
        cf = float(conf) if conf is not None else 0.0
    except (TypeError, ValueError):
        cf = 0.0
    if d == "long":
        if st == "bear":
            return True
        if lab in ("WEAK", "CHOP") and cf >= 40:
            return True
    if d == "short":
        if st == "bull":
            return True
        if lab in ("WEAK", "CHOP") and cf >= 40:
            return True
    return False


def _should_cut_loss_on_regime_flip(
    direction: str,
    snap: dict,
    pnl_pct: float,
    elapsed: float,
) -> tuple[bool, str]:
    """V.2.10.89 — زیان‌ده + برگشت جهت → بستن زودتر از SL کامل."""
    if not ENABLE_REGIME_ADVERSE_LOSS_EXIT:
        return False, ""
    if elapsed < float(REGIME_ADVERSE_LOSS_MIN_ELAPSED_SEC):
        return False, ""
    try:
        p = float(pnl_pct)
    except (TypeError, ValueError):
        return False, ""
    if p > float(REGIME_ADVERSE_LOSS_PNL_PCT):
        return False, ""

    conf = 0.0
    if snap and not snap.get("error"):
        try:
            conf = float(snap.get("regime_confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
    stack = str((snap or {}).get("ema_stack_1h") or "").lower()
    label = str((snap or {}).get("regime_label") or "").upper()
    d = (direction or "").lower()
    reasons: list[str] = []

    if d == "long" and stack == "bear" and conf >= float(REGIME_ADVERSE_LOSS_MIN_CONF):
        reasons.append("stack_bear")
    if d == "short" and stack == "bull" and conf >= float(REGIME_ADVERSE_LOSS_MIN_CONF):
        reasons.append("stack_bull")
    if label in ("WEAK", "CHOP") and conf >= float(REGIME_ADVERSE_LOSS_MIN_CONF):
        reasons.append(f"symbol_{label.lower()}")
    if _btc_hostile_to_direction(d):
        reasons.append("btc_hostile")

    if not reasons:
        return False, ""
    # فقط btc_hostile و نماد هنوز TREND_OK+bull قوی → فقط اگر ضرر عمیق‌تر
    if reasons == ["btc_hostile"] and d == "long" and stack == "bull" and label == "TREND_OK" and conf >= 70:
        if p > -0.45:
            return False, ""
        reasons.append("deep_loss")
    return True, "+".join(reasons)

async def _lookup_exchange_close(meta: dict) -> dict | None:
    """تاریخچهٔ صرافی را با entry/qty/زمان باز شدن تطبیق می‌دهد. تطبیق سست برنمی‌گردد."""
    key = _norm_symbol(str(meta.get("symbol") or ""))
    if not key:
        return None
    try:
        hp = await toobit_private.get_history_positions(key, limit=40)
    except Exception:
        return None
    rows: list = []
    if isinstance(hp, dict):
        raw = hp.get("data") if hp.get("data") is not None else hp.get("list") or hp.get("positions") or []
        if isinstance(raw, dict):
            raw = raw.get("list") or raw.get("data") or []
        rows = raw if isinstance(raw, list) else []
    elif isinstance(hp, list):
        rows = hp
    try:
        fill = float(meta.get("fill_entry") or meta.get("entry") or 0) or None
    except (TypeError, ValueError):
        fill = None
    try:
        qty = abs(float(meta.get("quantity") or 0)) or None
    except (TypeError, ValueError):
        qty = None
    try:
        opened = float(meta.get("opened_at") or 0) or None
    except (TypeError, ValueError):
        opened = None
    hit = _match_history_row(
        rows, key, fill_entry=fill, qty=qty, opened_at=opened, closed_after=opened,
    )
    if not isinstance(hit, dict):
        return None
    try:
        ct = float(hit.get("closeTime") or 0)
        if ct > 1e12:
            ct = ct / 1000.0
    except (TypeError, ValueError):
        ct = 0.0
    if opened and ct and ct < float(opened) - 180:
        return None
    return hit


def _history_row_pnl(row: dict) -> float | None:
    for k in ("realizedPnL", "realizedPnl", "pnl"):
        if row.get(k) not in (None, ""):
            try:
                return float(row[k])
            except (TypeError, ValueError):
                continue
    return None


def _history_row_close_ts(row: dict) -> float:
    try:
        ct = float(row.get("closeTime") or 0)
    except (TypeError, ValueError):
        return 0.0
    if ct > 1e12:
        ct = ct / 1000.0
    return ct


def _book_exchange_confirmed_close(key: str, meta: dict, row: dict) -> None:
    """بستن تأییدشده با زمان و PnL خود صرافی. کشف‌شدن الان جای closeTime نمی‌نشیند."""
    pnl = _history_row_pnl(row)
    ct = _history_row_close_ts(row) or time.time()
    try:
        exit_px = float(row.get("closeAvgPrice") or row.get("exitPrice") or meta.get("entry") or 0)
    except (TypeError, ValueError):
        exit_px = float(meta.get("entry") or 0)
    inferred = _infer_exit_reason_from_levels(
        str(meta.get("direction") or "long"),
        float(meta.get("entry") or 0),
        exit_px,
        float(meta.get("stop_loss") or 0),
        float(meta.get("target") or 0),
        meta,
    )
    inferred, conf = _reconcile_exit_reason_with_pnl(inferred, pnl)
    meta["status"] = "closed"
    meta["closed_at"] = ct
    meta["exit_price"] = exit_px
    meta["exit_reason"] = inferred
    meta["reason_confidence"] = conf
    if pnl is not None:
        meta["approx_pnl"] = round(pnl, 6)
        meta["realized_pnl"] = round(pnl, 6)
        meta["pnl_source"] = "exchange"
    # V.2.10.100: بستن قبل از بوت زیر نسخهٔ نامعلوم رخ داده — نسخهٔ زنده را روی آن ننویس
    meta["app_version_close"] = None
    meta["booked_by_version"] = APP_VERSION
    meta["exchange_close_id"] = row.get("id")
    meta["exchange_position_id"] = row.get("id") or meta.get("exchange_position_id")
    meta["exchange_closed_at"] = ct
    tid = str(meta.get("trade_id") or "")
    if tid and not any(str(h.get("trade_id") or "") == tid for h in _history):
        _history.insert(0, dict(meta))
        if len(_history) > 300:
            del _history[300:]
    # V.2.10.99: گاردها با زمان واقعی بستن صرافی. بستن چندروزه → هیچ کول‌داون/قفلی.
    # (در .98 کول‌داون از «الان» شروع می‌شد → بعد از هر دیپلوی ۱۴ نماد ۴ ساعت قفل)
    try:
        _mark_symbol_closed(key, inferred, pnl=pnl, at=ct)
    except Exception:
        pass
    try:
        _register_closed_trade(key, float(pnl or 0), str(inferred or ""), at=ct)
    except Exception:
        pass
    meta["guards_backdated_to"] = ct
    try:
        _save_tracked()
    except Exception:
        pass


async def _persist_close_to_db(meta: dict) -> None:
    """V.2.10.99 — وضعیت بستن را در Supabase هم بنویس تا بعد از ری‌استارت دوباره «open» بازیابی نشود."""
    try:
        from database.supabase_client import update_real_trade
        tid = meta.get("trade_id")
        if tid:
            await update_real_trade(tid, meta)
    except Exception as e:
        logger.warning("persist close to db failed %s: %s", meta.get("symbol"), e)


def _ghost_disposition(meta: dict, *, seen: bool, boot_ts: float, history_match: bool, on_exchange: bool) -> str:
    if on_exchange:
        return "live"
    if history_match:
        return "exchange_closed"
    try:
        opened = float(meta.get("opened_at") or 0)
    except (TypeError, ValueError):
        opened = 0.0
    st = str(meta.get("status") or "")
    if st == "open" and opened > 0 and opened < float(boot_ts) and not seen:
        return "reconciliation_pending"
    if st == "reconciliation_pending":
        return "still_pending"
    return "closed_external"


async def manage_open_real_positions() -> dict[str, Any]:
    """
    یک دور مدیریت: چک پوزیشن‌های باز صرافی + ردیاب داخلی.
    - پیشرفت کافی به سمت TP → بستن مارکت (قفل سود)
    - گذشت از MAX_HOLD → بستن
    - پوزیشن‌هایی که روی صرافی بسته شده‌اند از ردیاب پاک می‌شوند
    """
    try:
        apply_runtime_settings()
    except Exception:
        pass
    if not REAL_TRADING_ENABLED or not toobit_private.keys_configured():
        return {"skipped": True, "actions": []}

    actions: list[dict] = []
    _need_daily_refresh = False  # V.2.10.100
    try:
        await _load_remote_state_once()  # V.2.11.5 — فقط بار اول بعد از بوت I/O دارد
    except Exception as _rse:
        logger.debug("remote state load failed: %s", _rse)
    n_open, exchange_rows = await _open_positions_count()
    if exchange_rows is None:
        logger.warning("manage_open: positions API error — skip reconciliation this cycle")
        return {"skipped": True, "reason": "positions_api_error", "actions": []}
    try:
        _bal_for_slots = await _equity_balance()
    except Exception:
        _bal_for_slots = 0.0
    _max_pos_for_float = _effective_max_positions(_bal_for_slots)

    # نقشه پوزیشن‌های زنده صرافی
    live: dict[str, dict] = {}
    for r in exchange_rows:
        qty = toobit_private.parse_position_qty(r) if isinstance(r, dict) else 0.0
        if qty < 1e-12:
            continue
        raw_sym = str(r.get("symbol") or r.get("contract") or "")
        key = _norm_symbol(raw_sym)
        direction = toobit_private.parse_position_side(r)
        try:
            entry = float(r.get("avgPrice") or r.get("entryPrice") or r.get("openPrice") or 0)
        except (TypeError, ValueError):
            entry = 0.0
        live[key] = {
            "direction": direction,
            "qty": qty,
            "entry": entry,
            "raw": r,
        }

    # V.2.10.23b: پوزیشن‌های باز با مارجین زیر کف → بستن اجباری (شامل باز شده‌های قبلی)
    for key, live_info in list(live.items()):
        raw = live_info.get("raw") or {}
        try:
            ex_margin = float(raw.get("margin") or 0)
        except (TypeError, ValueError):
            ex_margin = 0.0
        if ex_margin <= 0 or ex_margin >= MIN_MARGIN_USDT * 0.98:
            continue
        direction = live_info["direction"]
        qty = live_info["qty"]
        logger.error(
            "REAL %s live margin %.4f < floor %.1f — force close (manager)",
            key, ex_margin, MIN_MARGIN_USDT,
        )
        # V.2.10.56: close از ledger واحد
        if key not in _tracked or _tracked.get(key, {}).get("status") != "open":
            _tracked[key] = {
                "trade_id": f"under_{key}_{uuid.uuid4().hex[:8]}",
                "symbol": key,
                "direction": direction,
                "entry": float(live_info.get("entry") or 0),
                "fill_entry": float(live_info.get("entry") or 0) or None,
                "quantity": str(qty),
                "margin_usdt": ex_margin,
                "stop_loss": 0.0,
                "target": 0.0,
                "opened_at": time.time(),
                "status": "open",
                "age_unknown": True,
                "app_version": APP_VERSION,
            }
        result = await _close_tracked(key, "undersized_margin")
        if not result.get("ok"):
            logger.warning("undersized force close failed %s: %s", key, result)
            actions.append({"symbol": key, "action": "undersized_close_failed", "margin": ex_margin, "exchange": result})
            continue
        _mark_symbol_closed(key, "undersized_margin")
        try:
            _record_attempt(key, False, f"مارجین {ex_margin:.2f}$ < کف {MIN_MARGIN_USDT:.1f}$ — بسته شد", direction=direction)
        except Exception:
            pass
        actions.append({"symbol": key, "action": "closed_undersized_margin", "margin": ex_margin})
        live.pop(key, None)

    # پوزیشن‌هایی که در ردیاب هستند ولی روی صرافی دیگر باز نیستند
    _seen_on_exchange.update(live.keys())
    for key in list(_tracked.keys()):
        _st_miss = str(_tracked[key].get("status") or "")
        if _st_miss not in ("open", "reconciliation_pending"):
            continue
        if key in live:
            if _st_miss == "reconciliation_pending":
                _tracked[key]["status"] = "open"
                _tracked[key].pop("reconciliation_note", None)
                logger.info("REAL %s back on exchange — reconciliation cleared", key)
            continue
        if key not in live:
            meta_x = _tracked[key]
            # V.2.12.3 — پوزیشن دیگر روی صرافی نیست ⇒ سفارش limit TP باقی‌مانده (اگر بود) لغو شود
            try:
                await _cancel_maker_tp(meta_x)
            except Exception:
                pass
            _ev = None
            try:
                _ev = await _lookup_exchange_close(meta_x)
            except Exception as _ge:
                logger.warning("ghost history lookup %s: %s", key, _ge)
            _disp = _ghost_disposition(
                meta_x,
                seen=key in _seen_on_exchange,
                boot_ts=_BOOT_TS,
                history_match=bool(_ev),
                on_exchange=False,
            )
            if _disp == "exchange_closed" and _ev:
                _book_exchange_confirmed_close(key, meta_x, _ev)
                await _persist_close_to_db(meta_x)
                actions.append({
                    "symbol": key,
                    "action": "exchange_confirmed_close",
                    "exit_reason": meta_x.get("exit_reason"),
                    "pnl": meta_x.get("realized_pnl"),
                })
                _need_daily_refresh = True
                logger.info(
                    "REAL %s exchange-confirmed close pnl=%s reason=%s",
                    key, meta_x.get("realized_pnl"), meta_x.get("exit_reason"),
                )
                continue
            if _disp == "reconciliation_pending":
                meta_x["status"] = "reconciliation_pending"
                meta_x["reconciliation_note"] = "pre-boot unseen; history unmatched — no cooldown, no fake pnl"
                try:
                    _save_tracked()
                except Exception:
                    pass
                actions.append({"symbol": key, "action": "reconciliation_pending"})
                logger.warning("REAL %s reconciliation_pending (pre-boot, unseen, no history)", key)
                continue
            if _disp == "still_pending":
                continue
            # قیمت خروج تقریبی از last live price — فقط پوزیشنی که این سشن دیده شده
            try:
                px_info = await toobit_market.get_live_price(key)
                exit_px = float(px_info.get("price") or meta_x.get("entry") or 0)
            except Exception:
                exit_px = float(meta_x.get("current_price") or meta_x.get("entry") or 0)
            inferred = None
            # V.2.10.46 — فقط سفارش بستنِ همین پوزیشن (بعد از opened_at)؛
            # جلوگیری از نسبت‌دادن sd_c_profit_lock معاملهٔ قبلی همان نماد
            inferred = _exit_reason_from_client_order_id(meta_x.get("close_client_order_id"))
            opened_ms = 0.0
            try:
                opened_ms = float(meta_x.get("opened_at") or 0) * 1000.0
            except Exception:
                opened_ms = 0.0
            if not inferred:
                try:
                    ho = await toobit_private.get_history_orders(key, limit=30)
                    rows = ho.get("data") if isinstance(ho, dict) else None
                    if rows is None and isinstance(ho, dict):
                        rows = ho.get("list") or ho.get("orders") or []
                    if not isinstance(rows, list):
                        rows = []
                    # جدیدترین سفارش بستنِ مربوط به این پوزیشن
                    best = None  # (time_ms, cid, reason_or_none, is_exchange_native)
                    for o in rows:
                        if not isinstance(o, dict):
                            continue
                        cid = str(o.get("clientOrderId") or "")
                        side = str(o.get("side") or "").upper()
                        otype = str(o.get("type") or o.get("orderType") or "").upper()
                        is_close = (
                            "CLOSE" in side
                            or "STOP" in otype
                            or "PROFIT" in otype
                            or "LOSS" in otype
                            or cid.startswith("sd_c_")
                        )
                        if not is_close:
                            continue
                        try:
                            tms = float(o.get("time") or o.get("updateTime") or 0)
                        except Exception:
                            tms = 0.0
                        # فقط بعد از باز شدن این پوزیشن (حاشیه ۵ثانیه)
                        if opened_ms > 0 and tms > 0 and tms < (opened_ms - 5000):
                            continue
                        r = _exit_reason_from_client_order_id(cid)
                        is_native = (not cid.startswith("sd_c_")) and (not cid.startswith("sd_"))
                        cand = (tms, cid, r, is_native)
                        if best is None or tms >= best[0]:
                            best = cand
                    if best is not None:
                        _tms, cid, r, is_native = best
                        meta_x["close_client_order_id"] = cid
                        if r:
                            inferred = r
                        elif cid.startswith("sd_"):
                            inferred = "bot_close_unspecified"
                        elif is_native:
                            # بستن بومی صرافی (استاپ/تی‌پی) — هرگز profit_lock نگذار
                            inferred = _infer_exit_reason_from_levels(
                                str(meta_x.get("direction") or "long"),
                                float(meta_x.get("entry") or 0),
                                exit_px,
                                float(meta_x.get("stop_loss") or 0),
                                float(meta_x.get("target") or 0),
                                meta_x,
                            )
                            if inferred in (None, "external_or_unknown"):
                                pnl_tmp = _unrealized_pct(
                                    str(meta_x.get("direction") or "long"),
                                    float(meta_x.get("entry") or 0),
                                    float(exit_px or 0),
                                )
                                inferred = (
                                    "exchange_stop_loss"
                                    if pnl_tmp < 0
                                    else "exchange_take_profit_approx"
                                )
                except Exception as e:
                    logger.warning("history_orders exit_reason lookup failed %s: %s", key, e)
            if not inferred:
                inferred = _infer_exit_reason_from_levels(
                    str(meta_x.get("direction") or "long"),
                    float(meta_x.get("entry") or 0),
                    exit_px,
                    float(meta_x.get("stop_loss") or 0),
                    float(meta_x.get("target") or 0),
                    meta_x,
                )
            # V.2.10.54 — reconciliation با PnL + confidence
            try:
                entry_x = float(meta_x.get("entry") or 0)
                pnl_chk = _unrealized_pct(
                    str(meta_x.get("direction") or "long"),
                    entry_x,
                    float(exit_px or 0),
                )
                margin_x = float(meta_x.get("margin_usdt") or 0)
                approx_pnl_x = margin_x * LEVERAGE * (pnl_chk / 100) if entry_x > 0 else 0.0
                inferred, conf = _reconcile_exit_reason_with_pnl(inferred, approx_pnl_x)
                meta_x["reason_confidence"] = conf
                meta_x["approx_pnl"] = round(approx_pnl_x, 4)
                meta_x["approx_pnl_pct"] = round(pnl_chk, 4)
            except Exception:
                pass
            meta_x["status"] = "closed_external"
            meta_x["closed_at"] = time.time()
            meta_x["exit_reason"] = inferred
            meta_x["exit_price"] = exit_px
            # V.2.10.74
            if not meta_x.get("reason_confidence"):
                meta_x["reason_confidence"] = "approx"
            try:
                meta_x["outcome_class"] = _outcome_class(
                    inferred, float(meta_x.get("approx_pnl") or 0)
                )
            except Exception:
                meta_x["outcome_class"] = "UNKNOWN"
            try:
                meta_x["autopsy"] = _build_trade_autopsy(
                    meta_x, inferred,
                    float(meta_x.get("approx_pnl") or 0),
                    None,
                )
            except Exception as _ae:
                meta_x["autopsy"] = {"error": str(_ae)[:80], "note": "observation_only"}
            meta_x["app_version_close"] = APP_VERSION
            # V.2.10.100: نسخهٔ باز شدن نامعلوم بماند؛ نسخهٔ زنده جعل نشود (منشأ برچسب «.99» روی معاملات قدیمی)
            _history.insert(0, dict(meta_x))
            if len(_history) > 300:
                del _history[300:]
            _mark_symbol_closed(key, inferred)
            try:
                _register_closed_trade(
                    key, float(meta_x.get("approx_pnl") or 0), str(inferred or ""),
                )
            except Exception:
                pass
            try:
                _record_attempt(
                    key, False, f"بسته شد خارجی — {inferred}",
                    direction=meta_x.get("direction"), exit_reason=inferred,
                )
            except Exception:
                pass
            logger.info("REAL %s closed externally reason=%s", key, inferred)
            try:
                _save_tracked()
            except Exception:
                pass
            await _persist_close_to_db(meta_x)  # V.2.10.99
            actions.append({"symbol": key, "action": "sync_closed_external", "exit_reason": inferred})
            _need_daily_refresh = True

    # V.2.10.100 — PnL روزانه از صرافی: فوری بعد از هر بستن سمت صرافی، وگرنه حداکثر هر ۶۰ ثانیه
    try:
        await _refresh_daily_pnl_from_exchange(force=_need_daily_refresh)
    except Exception as _dpe:
        logger.warning("daily pnl refresh in manager failed: %s", _dpe)
    # V.2.11.0 — معاملات کاغذی + مسیر ۱m معاملات بسته
    try:
        for _pc in await _paper_update():
            actions.append({"symbol": _pc.get("symbol"), "action": "paper_closed",
                            "exit_reason": _pc.get("exit_reason"), "net_pct": _pc.get("net_pct")})
    except Exception as _pe:
        logger.debug("paper update failed: %s", _pe)
    try:
        await _queue_recent_path_captures()
        await _process_path_captures()
    except Exception as _pce:
        logger.debug("path capture failed: %s", _pce)
    # V.2.12.3 — self-test سفارش maker (یک بار در هر بوت، فقط اگر روشن شده)
    if MAKER_TP_SELFTEST and not _MAKER_SELFTEST.get("ts_this_boot") and not _MAKER_SELFTEST.get("ok") \
            and _REMOTE_STATE_LOADED.get("maker"):
        try:
            _r = await _run_maker_selftest()
            _MAKER_SELFTEST.clear()
            _MAKER_SELFTEST.update(_r)
            _MAKER_SELFTEST["ts_this_boot"] = time.time()
            _kv_save_async("maker_selftest", {k: v for k, v in _MAKER_SELFTEST.items() if k != "ts_this_boot"})
            actions.append({"action": "maker_tp_selftest", "ok": _r.get("ok"), "reason": _r.get("reason")})
        except Exception as _mte:
            _MAKER_SELFTEST.update({"ts_this_boot": time.time(), "ok": False, "reason": f"خطا: {str(_mte)[:120]}"})
    # V.2.11.3 — self-test ورود محافظت‌شده (یک بار در هر بوت، فقط اگر روشن شده)
    if ENTRY_PROTECTED_SELFTEST and not _PROTECTED_SELFTEST.get("ts"):
        try:
            _PROTECTED_SELFTEST.update(await _run_protected_selftest())
            actions.append({"action": "protected_ioc_selftest", "ok": _PROTECTED_SELFTEST.get("ok"),
                            "reason": _PROTECTED_SELFTEST.get("reason")})
        except Exception as _ste:
            _PROTECTED_SELFTEST.update({"ts": time.time(), "ok": False, "reason": f"خطا: {str(_ste)[:120]}"})
    # V.2.18.1 — اسکن rs_intraday_50 (هر ۴ ساعت)
    try:
        if AUTO_MATRIX and _MATRIX.get("policy"):
            _rir = await _rs_intraday_scan()
            if _rir:
                _save_scan_last()
            if _rir.get("opened"):
                actions.append({"action": "rs_intraday_scan", "opened": _rir.get("opened")})
    except Exception as _rie:
        logger.debug("rs_intraday scan failed: %s", _rie)
    # V.2.17.0 — اسکن tsmom_daily (روزی یک بار)
    try:
        if AUTO_MATRIX and _MATRIX.get("policy"):
            _tsr = await _tsmom_scan()
            if _tsr:
                _save_scan_last()
            if _tsr.get("opened"):
                actions.append({"action": "tsmom_scan", "opened": _tsr.get("opened")})
    except Exception as _tse:
        logger.debug("tsmom scan failed: %s", _tse)
    # V.2.22.1 — زندهٔ استراتژی‌های گیت‌هاب قبول‌شده (هر ساعت) + تنزل خودکار
    try:
        if GH_LIVE_ENABLED and _REMOTE_STATE_LOADED.get("scan_slots"):
            await _gh_live_check()
            _ghr = await _gh_live_scan()
            if _ghr.get("opened"):
                actions.append({"action": "gh_live_scan", "opened": _ghr.get("opened")})
    except Exception as _gle:
        logger.debug("gh live failed: %s", _gle)
    # V.2.22.0 — کاغذی رو به جلوی استراتژی‌های گیت‌هاب (هر ساعت، پس‌زمینه)
    try:
        global _GH_TASK
        if GH_PAPER_ENABLED and _REMOTE_STATE_LOADED.get("scan_slots"):
            import backtest_github as _bgx
            if (_GH_TASK is None or _GH_TASK.done()) and time.time() - float(_bgx.FWD.get("last_run") or 0) >= GH_FORWARD_EVERY_SEC:
                _GH_TASK = asyncio.create_task(_gh_forward_cycle())
    except Exception as _ghe:
        logger.debug("gh forward failed: %s", _ghe)
    # V.2.20.0 — اسکن trend_atr_daily (روزی یک بار)
    try:
        if AUTO_MATRIX and _MATRIX.get("policy"):
            _tar = await _trend_atr_scan()
            if _tar:
                _save_scan_last()
            if _tar.get("opened"):
                actions.append({"action": "trend_atr_scan", "opened": _tar.get("opened")})
    except Exception as _tae:
        logger.debug("trend_atr scan failed: %s", _tae)
    # V.2.15.0 — اسکن rel_strength (هر ۴ ساعت)
    try:
        if AUTO_MATRIX and _MATRIX.get("policy"):
            _rsr = await _rel_strength_scan()
            if _rsr:
                _save_scan_last()
            if _rsr.get("opened"):
                actions.append({"action": "rel_strength_scan", "opened": _rsr.get("opened")})
    except Exception as _rse3:
        logger.debug("rel_strength scan failed: %s", _rse3)
    # V.2.19.0 — آزمون رو به جلو: ارتقا/تنزل
    try:
        await _fwd_check()
    except Exception as _fwe:
        logger.debug("forward check failed: %s", _fwe)
    # V.2.13.0 — تنزل خودکار خانه‌های جدول با نتیجهٔ زنده
    try:
        await _matrix_live_check()
    except Exception as _mle:
        logger.debug("matrix live check failed: %s", _mle)
    # V.2.12.0 — بک‌تست خودکار (۲ دقیقه بعد از بوت، بعد هر ۲۴ ساعت)
    try:
        _backtest_maybe_start()
    except Exception as _bte:
        logger.debug("backtest start failed: %s", _bte)
    # V.2.11.9 — ارزیابی/تصمیم «سود کوچک» رنج (هر ۵ دقیقه)
    try:
        await _small_tp_refresh()
    except Exception as _ste2:
        logger.debug("small tp refresh failed: %s", _ste2)
    # V.2.11.2 — اثر واقعی خبرها روی BTC (هر ۵ دقیقه، سبک)
    try:
        await _measure_news_impact()
    except Exception as _nie:
        logger.debug("news impact failed: %s", _nie)
    _MANAGER_HEARTBEAT["ts"] = time.time()
    _MANAGER_HEARTBEAT["cycles"] = int(_MANAGER_HEARTBEAT.get("cycles") or 0) + 1
    # V.2.11.1 — رانش BTC هر دور (کش ۶۰ث) تا گزارش/چیپ همیشه وضعیت فعلی را نشان دهد،
    # حتی وقتی خبر یا pause جلوی رسیدن کاندید به گیت ورود را گرفته است
    try:
        await _btc_drift_state()
    except Exception as _bde:
        logger.debug("btc drift refresh failed: %s", _bde)

    # مدیریت پوزیشن‌های زنده
    now = time.time()
    for key, live_info in live.items():
        meta = _tracked.get(key)
        direction = live_info["direction"]
        entry = float(meta["entry"]) if meta else float(live_info["entry"] or 0)
        if entry <= 0:
            continue

        # قیمت لحظه‌ای
        try:
            price_info = await toobit_market.get_live_price(key)
            price = float(price_info.get("price") or entry)
        except Exception as e:
            logger.warning("live price failed for %s: %s", key, e)
            continue

        # اگر خودمان باز کرده‌ایم و متادیتا داریم
        if meta and meta.get("status") == "open":
            # هم‌سان‌سازی SL/TP نمایشی با صرافی (هر دور مدیریت)
            try:
                await _sync_levels_from_exchange(key, meta)
            except Exception:
                pass
            target = float(meta.get("target") or 0) or entry
            progress = _progress(direction, entry, target, price)
            pnl_pct = _unrealized_pct(direction, entry, price)
            elapsed = now - float(meta.get("opened_at") or now)
            # V.2.18.4 — یک بار در هر راه‌اندازی: limitهای بستن قدیمی (maker TP) آزاد شوند
            if meta.get("_limits_released_session") != _SESSION_START_TS:
                meta["_limits_released_session"] = _SESSION_START_TS
                try:
                    _rl0 = await _release_close_limits(key, meta)
                    if _rl0.get("canceled"):
                        actions.append({"symbol": key, "action": "release_close_limits", "canceled": _rl0.get("canceled")})
                except Exception:
                    pass
            # V.2.18.4 — نگهبان SL برای همهٔ استراتژی‌ها: SL روی صرافی نیست ⇒ قیمت از SL گذشته؟ ببند؛ وگرنه دوباره بگذار
            _sl_guard = await _exchange_sl_guard(key, meta, direction, price, elapsed)
            if _sl_guard:
                actions.append({"symbol": key, **_sl_guard})
                if _sl_guard.get("closed"):
                    continue
            _is_range = str(meta.get("strategy_id") or "") == "range_scalp"
            if _is_range:
                try:
                    _deadline = float(meta.get("time_stop_deadline") or 0)
                except (TypeError, ValueError):
                    _deadline = 0.0
                if _deadline <= 0:
                    _deadline = float(meta.get("opened_at") or now) + float(RANGE_TIME_STOP_SEC)
                    meta["time_stop_deadline"] = _deadline
                try:
                    _rh = float(meta.get("range_high") or 0)
                    _rl = float(meta.get("range_low") or 0)
                except (TypeError, ValueError):
                    _rh = _rl = 0.0
                _broke = False
                if _rl > 0 and _rh > _rl:
                    if direction == "long" and price < _rl * 0.9985:
                        _broke = True
                    elif direction == "short" and price > _rh * 1.0015:
                        _broke = True
                if _broke:
                    res = await _close_tracked(key, "range_invalidated", price)
                    actions.append({
                        "symbol": key, "action": "range_invalidated",
                        "ok": bool((res or {}).get("ok")),
                    })
                    continue
                if now >= _deadline:
                    res = await _close_tracked(key, "range_time_stop", price)
                    actions.append({
                        "symbol": key, "action": "range_time_stop",
                        "ok": bool((res or {}).get("ok")),
                        "elapsed_sec": int(elapsed),
                    })
                    continue
            # V.2.10.77 — MAE/MFE lifecycle observation
            try:
                _update_lifecycle_observation(meta, price)
            except Exception:
                pass
            _sample_price_path(meta, price, now)  # V.2.10.100

            # V.2.17.0 — tsmom_daily: خروج روند روزانه/۱۴ روز + همان ایمنی‌ها؛ بدون سربه‌سر/قفل/خروج‌های کوتاه‌مدت
            if str(meta.get("strategy_id") or "") in ("tsmom_daily", "trend_atr_daily") + GH_LIVE_STRATEGIES:
                _sidx = str(meta.get("strategy_id"))
                if _sidx in GH_LIVE_STRATEGIES:   # V.2.24.0 — ROI زمانی + تریلینگ خود استراتژی (همان بک‌تست)
                    try:
                        _act_g = await _gh_live_manage(key, meta, direction, price)
                        if _act_g:
                            actions.append({"symbol": key, **_act_g})
                            if _act_g.get("closed"):
                                continue
                    except Exception as _ge:
                        logger.debug("gh manage failed %s: %s", key, _ge)
                _why_t = (await _tsmom_exit_check(meta, key) if _sidx == "tsmom_daily"
                          else await _gh_exit_check(meta, key) if _sidx in GH_LIVE_STRATEGIES   # V.2.22.1
                          else await _trend_atr_exit_check(meta, key))   # V.2.20.0
                if _why_t:
                    res = await _close_tracked(key, _why_t, price)
                    actions.append({"symbol": key, "action": _why_t, "ok": bool((res or {}).get("ok")),
                                    "pnl_pct": round(float(pnl_pct), 4)})
                    continue
                try:
                    _e_t = float(meta.get("fill_entry") or meta.get("entry") or entry)
                    _sl_t = float(meta.get("initial_sl") or meta.get("original_stop_loss") or meta.get("stop_loss") or 0)
                    _slp_t = abs(_e_t - _sl_t) / _e_t * 100.0 if _e_t > 0 and _sl_t > 0 else float(TREND_ATR_SL_CAP_PCT)
                except (TypeError, ValueError, ZeroDivisionError):
                    _slp_t = float(TREND_ATR_SL_CAP_PCT)
                if (ENABLE_EMERGENCY_LOSS_EXIT and elapsed >= EMERGENCY_LOSS_MIN_ELAPSED_SEC
                        and pnl_pct <= -(max(abs(MAX_UNREALIZED_LOSS_PCT), _slp_t + 1.0))):
                    res = await _close_tracked(key, "emergency_loss_cap", price)
                    actions.append({"symbol": key, "action": "emergency_loss_cap", "pnl_pct": round(pnl_pct, 4)})
                    continue
                if not meta.get("sl_on_exchange") and elapsed >= MAX_SECONDS_WITHOUT_EXCHANGE_SL:
                    res = await _close_tracked(key, "no_exchange_sl", price)
                    actions.append({"symbol": key, "action": "force_close_no_sl", "elapsed_sec": int(elapsed)})
                    continue
                continue

            # V.2.15.0 — rel_strength: فقط SL/TP صرافی + حداکثر ۲۴ ساعت (همان بک‌تست؛ بدون سربه‌سر/قفل/خروج‌های روند)
            if str(meta.get("strategy_id") or "") in ("rel_strength", "rs_intraday_50"):
                _fam_x = str(meta.get("strategy_id"))
                _ts_label = "rsi_time_stop" if _fam_x == "rs_intraday_50" else "rs_time_stop"
                try:
                    _dl = float(meta.get("time_stop_deadline") or 0)
                except (TypeError, ValueError):
                    _dl = 0.0
                # V.2.18.3 — مهلت = کمترِ (مهلت ذخیره‌شده، باز شدن + سقف فعلی) ⇒ پوزیشن‌های قبلی هم با سقف ۵ ساعت بسته می‌شوند
                _dl_cap = float(meta.get("opened_at") or now) + float(_family_max_hold(_fam_x))
                if _dl <= 0 or _dl_cap < _dl:
                    _dl = _dl_cap
                    meta["time_stop_deadline"] = _dl
                if now >= _dl:
                    meta["exit_decision"] = {"reason": _ts_label, "max_hold_h": round(_family_max_hold(_fam_x) / 3600.0, 2),
                                             "pnl_pct": round(float(pnl_pct), 4)}
                    res = await _close_tracked(key, _ts_label, price)
                    actions.append({"symbol": key, "action": _ts_label, "ok": bool((res or {}).get("ok")),
                                    "elapsed_sec": int(elapsed), "pnl_pct": round(float(pnl_pct), 4)})
                    continue
                try:
                    _e_rs = float(meta.get("fill_entry") or meta.get("entry") or entry)
                    _sl_rs = float(meta.get("initial_sl") or meta.get("original_stop_loss") or meta.get("stop_loss") or 0)
                    _slp_rs = abs(_e_rs - _sl_rs) / _e_rs * 100.0 if _e_rs > 0 and _sl_rs > 0 else float(RS_SL_MAX_PCT)
                except (TypeError, ValueError, ZeroDivisionError):
                    _slp_rs = float(RS_SL_MAX_PCT)
                # V.2.18.6 — خروج انتخاب‌شده با داده: سربه‌سر / SL متحرک (همان قاعدهٔ بک‌تست؛ فقط سفت‌تر)
                try:
                    _ex_act = await _rs_exit_manage(key, meta, direction, price, _e_rs, _slp_rs)
                except Exception as _exe:
                    _ex_act = {"action": "rs_exit_manage_error", "error": str(_exe)[:120]}
                if _ex_act:
                    actions.append({"symbol": key, **_ex_act})
                    if _ex_act.get("closed"):
                        continue
                if (ENABLE_EMERGENCY_LOSS_EXIT and elapsed >= EMERGENCY_LOSS_MIN_ELAPSED_SEC
                        and pnl_pct <= -(max(abs(MAX_UNREALIZED_LOSS_PCT), _slp_rs + 1.0))):
                    res = await _close_tracked(key, "emergency_loss_cap", price)
                    actions.append({"symbol": key, "action": "emergency_loss_cap", "pnl_pct": round(pnl_pct, 4)})
                    continue
                if not meta.get("sl_on_exchange") and elapsed >= MAX_SECONDS_WITHOUT_EXCHANGE_SL:
                    res = await _close_tracked(key, "no_exchange_sl", price)
                    actions.append({"symbol": key, "action": "force_close_no_sl", "elapsed_sec": int(elapsed)})
                    continue
                continue

            # V.2.11.9 — رنج: «سود کوچک» فقط وقتی داده خودکار روشنش کرده باشد
            _stp_rule = _SMALL_TP_STATE.get("enabled_rule") if (_is_range and RANGE_SMALL_TP_AUTO) else None
            try:
                _tp_pct_live = abs(float(meta.get("target") or 0) - float(meta.get("fill_entry") or entry)) / float(meta.get("fill_entry") or entry) * 100.0
            except (TypeError, ValueError, ZeroDivisionError):
                _tp_pct_live = None
            _stp_lvl = _small_tp_level(_stp_rule, _tp_pct_live)
            if _stp_lvl is not None and float(pnl_pct) >= float(_stp_lvl):
                meta["exit_decision"] = {"reason": "range_small_tp", "rule": _stp_rule,
                                         "pnl_pct": round(float(pnl_pct), 4), "level_pct": _stp_lvl,
                                         "decision": _SMALL_TP_STATE.get("decision")}
                res = await _close_tracked(key, "range_small_tp", price)
                actions.append({"symbol": key, "action": "range_small_tp", "rule": _stp_rule,
                                "ok": bool((res or {}).get("ok")), "pnl_pct": round(float(pnl_pct), 4)})
                continue

            # V.2.11.8 — رنج: «ورود ناموفق» — بعد از ۱۰ دقیقه، اگر عملاً هیچ سودی نگرفته و ≥۰٫۳R خلاف رفته، زودتر از SL ببند
            if _is_range and RANGE_FAIL_EXIT and not meta.get("breakeven_set"):
                try:
                    _life = meta.get("lifecycle_observation") or {}
                    _mfe = float(_life.get("max_favorable_excursion_pct") or 0)
                    _e0 = float(meta.get("fill_entry") or meta.get("entry") or entry or 0)
                    _sl0 = float(meta.get("initial_sl") or meta.get("original_stop_loss") or meta.get("stop_loss") or 0)
                    _r_pct = abs(_e0 - _sl0) / _e0 * 100.0 if _e0 > 0 and _sl0 > 0 else 0.0
                except (TypeError, ValueError):
                    _mfe, _r_pct = 999.0, 0.0
                if (
                    _r_pct > 0
                    and elapsed >= float(RANGE_FAIL_EXIT_MIN_SEC)
                    and _mfe < float(RANGE_FAIL_EXIT_MFE_MAX_PCT)
                    and pnl_pct <= -float(RANGE_FAIL_EXIT_ADVERSE_R) * _r_pct
                ):
                    meta["exit_decision"] = {
                        "reason": "range_fail_exit", "elapsed": int(elapsed), "mfe_pct": round(_mfe, 4),
                        "pnl_pct": round(float(pnl_pct), 4), "r_pct": round(_r_pct, 4),
                        "rule": f"≥{int(RANGE_FAIL_EXIT_MIN_SEC)}s & mfe<{RANGE_FAIL_EXIT_MFE_MAX_PCT}% & ≤−{RANGE_FAIL_EXIT_ADVERSE_R}R",
                    }
                    res = await _close_tracked(key, "range_fail_exit", price)
                    actions.append({
                        "symbol": key, "action": "range_fail_exit", "ok": bool((res or {}).get("ok")),
                        "pnl_pct": round(float(pnl_pct), 4), "elapsed_sec": int(elapsed),
                    })
                    continue

            # ۰-regime) اسنپ‌شات رژیم برای soft-exit (نه reverse)
            regime_adverse = False
            regime_snap = {}
            if ENABLE_REGIME_SOFT_EXIT:
                try:
                    regime_snap = await _get_regime_snapshot(key)
                    regime_adverse = _regime_adverse_to_position(direction, regime_snap)
                    meta["regime_label"] = regime_snap.get("regime_label")
                    meta["regime_confidence"] = regime_snap.get("regime_confidence")
                    meta["regime_adverse"] = regime_adverse
                except Exception as _re:
                    logger.debug("regime soft-exit snapshot failed %s: %s", key, _re)

            
            # V.2.10.89 — قطع ضرر روی برگشت جهت (قبل از SL کامل / قبل از soft سود)
            if ENABLE_REGIME_ADVERSE_LOSS_EXIT and not _is_range:
                try:
                    _rs = regime_snap if isinstance(regime_snap, dict) and regime_snap else {}
                    if not _rs:
                        try:
                            _rs = await _get_regime_snapshot(key)
                            regime_snap = _rs or {}
                        except Exception:
                            _rs = {}
                    _cut, _cut_why = _should_cut_loss_on_regime_flip(
                        direction, _rs or {}, float(pnl_pct), float(elapsed),
                    )
                    if _cut:
                        res = await _close_tracked(key, "regime_adverse_loss_exit", price)
                        actions.append({
                            "symbol": key,
                            "action": "regime_adverse_loss_exit",
                            "why": _cut_why,
                            "pnl_pct": round(float(pnl_pct), 4),
                            "elapsed_sec": int(elapsed),
                            "ok": bool((res or {}).get("ok")),
                        })
                        print(
                            f"[regime-adverse-loss] {key} {direction} pnl={float(pnl_pct):.3f}% "
                            f"why={_cut_why} elapsed={int(elapsed)}s",
                            flush=True,
                        )
                        continue
                except Exception as _rae:
                    logger.warning("regime adverse loss exit failed %s: %s", key, _rae)

            # V.2.10.100 — range_exit_ignore_regime=true → آستانهٔ BE/قفل رنج مستقل از رژیم (پیش‌فرض خاموش = رفتار .99)
            _regime_for_exits = bool(regime_adverse) and not (_is_range and RANGE_EXIT_IGNORE_REGIME)
            be_trigger = REGIME_EXIT_BE_PCT if _regime_for_exits else BREAKEVEN_TRIGGER_PCT
            lock_progress = REGIME_EXIT_LOCK_PROGRESS if _regime_for_exits else PROFIT_LOCK_TRIGGER_RATIO
            lock_min_profit = REGIME_EXIT_LOCK_MIN_PROFIT if _regime_for_exits else MIN_PROFIT_PCT_TO_LOCK
            meta["exit_thresholds"] = {
                "regime_adverse": bool(regime_adverse),
                "regime_applied": _regime_for_exits,
                "be_trigger": be_trigger,
                "lock_progress": lock_progress,
                "lock_min_profit": lock_min_profit,
            }

            # ۰b) بستن نرم فقط اگر کمی سود و زمان کافی (V.2.10.34: نه صفرِ بعدازفی)
            if (
                regime_adverse
                and not _is_range
                and elapsed >= REGIME_EXIT_FLAT_MIN_ELAPSED
                and pnl_pct >= REGIME_EXIT_FLAT_MIN_PNL_PCT
                and not meta.get("regime_flat_closed")
            ):
                res = await _close_tracked(key, "regime_soft_exit", price)
                meta["regime_flat_closed"] = True
                actions.append({
                    "symbol": key,
                    "action": "regime_soft_exit",
                    "regime": regime_snap.get("regime_label"),
                    "conf": regime_snap.get("regime_confidence"),
                    "stack": regime_snap.get("ema_stack_1h"),
                    "pnl_pct": round(pnl_pct, 4),
                    "result": res,
                })
                print(
                    f"[regime-exit] soft close {key} {direction} pnl={pnl_pct:.3f}% "
                    f"label={regime_snap.get('regime_label')} stack={regime_snap.get('ema_stack_1h')}",
                    flush=True,
                )
                continue

            # ۰bt) V.2.10.38 — رژیم مخالف + ضرر → تنگ کردن SL (کاهش زیان باقی‌مانده، نه بستن اجباری)
            if (
                ENABLE_REGIME_TIGHTEN_SL
                and not _is_range
                and regime_adverse
                and elapsed >= REGIME_TIGHTEN_MIN_ELAPSED_SEC
                and not meta.get("regime_sl_tightened")
                and (not REGIME_TIGHTEN_ONLY_IF_LOSS or pnl_pct < 0)
            ):
                try:
                    old_sl = float(meta.get("stop_loss") or 0)
                    buf = abs(REGIME_TIGHTEN_BUFFER_PCT) / 100.0
                    if direction == "long":
                        # SL کمی زیر قیمت جاری — فقط اگر از SL قبلی بالاتر (تنگ‌تر) باشد
                        cand = price * (1.0 - buf)
                        new_sl = max(old_sl, cand) if old_sl > 0 else cand
                        # نباید بالای قیمت باشد (وگرنه فوری تریگر)
                        if new_sl >= price:
                            new_sl = price * (1.0 - buf)
                        improved = old_sl <= 0 or new_sl > old_sl * 1.0001
                    else:
                        cand = price * (1.0 + buf)
                        new_sl = min(old_sl, cand) if old_sl > 0 else cand
                        if new_sl <= price:
                            new_sl = price * (1.0 + buf)
                        improved = old_sl <= 0 or new_sl < old_sl * 0.9999
                    if improved and new_sl > 0:
                        tpsl = await toobit_private.attach_tpsl_and_verify(
                            symbol=key,
                            direction=direction,
                            take_profit=str(meta.get("target")),
                            stop_loss=str(round(new_sl, 8)),
                            quantity=str(meta.get("quantity") or live_info.get("qty") or ""),
                        )
                        if not tpsl.get("verified"):
                            logger.warning(
                                "regime tighten SL not verified %s req=%s got=%s",
                                key, new_sl, tpsl.get("exchange_sl"),
                            )
                        else:
                            _log_sl_change(meta, old_sl, float(tpsl.get("exchange_sl") or new_sl), "regime_tighten",
                                           price=price, verified=True, extra={"pnl_pct": round(float(pnl_pct), 4)})
                            meta["regime_sl_tightened"] = True
                            meta["stop_loss"] = float(tpsl.get("exchange_sl") or new_sl)
                            meta["sl_on_exchange"] = bool(tpsl.get("sl_on_exchange"))
                            try:
                                from database.supabase_client import upsert_open_real_trade
                                await upsert_open_real_trade(meta)
                            except Exception as _ue:
                                logger.warning("upsert after tighten failed: %s", _ue)
                            try:
                                _save_tracked()
                            except Exception:
                                pass
                            actions.append({
                                "symbol": key,
                                "action": "regime_tighten_sl",
                                "old_sl": old_sl,
                                "new_sl": meta["stop_loss"],
                                "pnl_pct": round(pnl_pct, 4),
                                "stack": regime_snap.get("ema_stack_1h"),
                            })
                            print(
                                f"[regime-tighten] {key} {direction} SL {old_sl} → {meta['stop_loss']} "
                                f"pnl={pnl_pct:.3f}% price={price}",
                                flush=True,
                            )
                except Exception as e:
                    logger.warning("regime tighten SL failed %s: %s", key, e)

            # ۰) انتقال SL به سربه‌سر (V.2.10.94: آستانه R + کارمزد + فقط بعد از verified صرافی)
            _sl0 = float(meta.get("initial_sl") or meta.get("stop_loss") or 0)
            _sl_dist_pct = abs(entry - _sl0) / entry * 100 if entry > 0 and _sl0 > 0 else 0.0
            _be_need = max(float(be_trigger), float(BREAKEVEN_MIN_R) * _sl_dist_pct) if _sl_dist_pct > 0 else float(be_trigger)
            if (
                pnl_pct >= _be_need
                and not meta.get("breakeven_set")
            ):
                try:
                    fr = abs(float(ROUND_TRIP_FRICTION_PCT)) / 100.0
                    if direction == "long":
                        be_sl = entry * (1.0 + fr)  # سربه‌سر بعد از کارمزد
                    else:
                        be_sl = entry * (1.0 - fr)
                    tpsl = await toobit_private.attach_tpsl_and_verify(
                        symbol=key,
                        direction=direction,
                        take_profit=str(meta.get("target")),
                        stop_loss=str(be_sl),
                        quantity=str(meta.get("quantity") or live_info.get("qty") or ""),
                    )
                    if not tpsl.get("verified"):
                        logger.warning(
                            "breakeven SL not verified on exchange %s req=%s got=%s",
                            key, be_sl, tpsl.get("exchange_sl"),
                        )
                        # retry next cycle — do NOT set breakeven_set
                        raise RuntimeError("be_sl_not_verified")
                    _log_sl_change(
                        meta, meta.get("stop_loss"), float(tpsl.get("exchange_sl") or be_sl), "breakeven",
                        price=price, verified=True,
                        extra={"pnl_pct": round(float(pnl_pct), 4), "be_need_pct": round(float(_be_need), 4),
                               "regime_applied": _regime_for_exits},
                    )
                    meta["breakeven_set"] = True
                    meta["stop_loss"] = float(tpsl.get("exchange_sl") or be_sl)
                    meta["sl_on_exchange"] = bool(tpsl.get("sl_on_exchange"))
                    try:
                        from database.supabase_client import upsert_open_real_trade
                        await upsert_open_real_trade(meta)
                    except Exception as _ue:
                        logger.warning("upsert after BE failed: %s", _ue)
                    try:
                        _save_tracked()
                    except Exception:
                        pass
                    actions.append({"symbol": key, "action": "breakeven_sl", "sl": be_sl})
                    print(f"[real_trade] BE SL {key} @ {be_sl}", flush=True)
                except Exception as e:
                    logger.warning("breakeven SL failed %s: %s", key, e)

            # V.2.11.12 — کف سود پله‌ای/دنبال‌کننده برای رنج (فقط وقتی داده خودکار روشنش کرده)
            _pf_rule = _SMALL_TP_STATE.get("enabled_rule") if (_is_range and RANGE_SMALL_TP_AUTO) else None
            _pf = EXIT_CANDIDATES.get(str(_pf_rule or ""))
            if _pf and _pf.get("kind") in ("lock", "trail", "prog_floor"):
                try:
                    _life2 = meta.get("lifecycle_observation") or {}
                    _mfe2 = float(_life2.get("max_favorable_excursion_pct") or 0)
                    _e2 = float(meta.get("fill_entry") or meta.get("entry") or entry)
                    _tpp2 = abs(float(meta.get("target") or 0) - _e2) / _e2 * 100.0 if _e2 > 0 else 0.0
                    _trig2 = (float(_pf["progress"]) * _tpp2) if _pf["kind"] == "prog_floor" else float(_pf["trigger"])
                    if _mfe2 >= _trig2 and _e2 > 0 and _trig2 > 0:
                        if _pf["kind"] == "lock":
                            _lk = float(_pf["lock"])
                        elif _pf["kind"] == "prog_floor":
                            _lk = float(_pf["floor_frac"]) * _tpp2
                        else:
                            _lk = float(_pf["frac"]) * _mfe2
                        _sgn = 1.0 if direction == "long" else -1.0
                        _floor = _e2 * (1.0 + _sgn * _lk / 100.0)
                        _cur = float(meta.get("stop_loss") or 0)
                        _better = (_floor > _cur * 1.0003) if direction == "long" else (_cur <= 0 or _floor < _cur * 0.9997)
                        _crossed = (price <= _floor) if direction == "long" else (price >= _floor)
                        if _better and _crossed:
                            meta["exit_decision"] = {"reason": "range_profit_floor", "rule": _pf_rule,
                                                     "floor": _floor, "mfe_pct": round(_mfe2, 4),
                                                     "pnl_pct": round(float(pnl_pct), 4)}
                            res = await _close_tracked(key, "range_profit_floor", price)
                            actions.append({"symbol": key, "action": "range_profit_floor", "rule": _pf_rule,
                                            "ok": bool((res or {}).get("ok"))})
                            continue
                        if _better:
                            tpsl = await toobit_private.attach_tpsl_and_verify(
                                symbol=key, direction=direction, take_profit=str(meta.get("target")),
                                stop_loss=str(_floor),
                                quantity=str(meta.get("quantity") or live_info.get("qty") or ""),
                            )
                            if tpsl.get("verified"):
                                _log_sl_change(meta, _cur, float(tpsl.get("exchange_sl") or _floor), "profit_floor",
                                               price=price, verified=True,
                                               extra={"rule": _pf_rule, "mfe_pct": round(_mfe2, 4), "lock_pct": round(_lk, 4)})
                                meta["stop_loss"] = float(tpsl.get("exchange_sl") or _floor)
                                meta["profit_floor_set"] = meta["stop_loss"]
                                meta["profit_floor_rule"] = _pf_rule
                                meta["breakeven_set"] = True
                                try:
                                    from database.supabase_client import upsert_open_real_trade
                                    await upsert_open_real_trade(meta)
                                except Exception:
                                    pass
                                try:
                                    _save_tracked()
                                except Exception:
                                    pass
                                actions.append({"symbol": key, "action": "profit_floor", "rule": _pf_rule,
                                                "sl": meta["stop_loss"]})
                except Exception as _pfe:
                    logger.warning("profit floor failed %s: %s", key, _pfe)

            # ۰c) V.2.10.37 — سقف زیان تحقق‌نیافته (ضد گپ/اسلیپیج مثل ARB)
            # اگر قیمت بیش از MAX_UNREALIZED_LOSS_PCT خلاف رفته، حتی با SL صرافی، مارکت ببند
            if (
                ENABLE_EMERGENCY_LOSS_EXIT
                and elapsed >= EMERGENCY_LOSS_MIN_ELAPSED_SEC
                and pnl_pct <= -abs(MAX_UNREALIZED_LOSS_PCT)
            ):
                logger.error(
                    "REAL EMERGENCY LOSS %s pnl=%.3f%% <= -%.2f%% elapsed=%.0fs",
                    key, pnl_pct, MAX_UNREALIZED_LOSS_PCT, elapsed,
                )
                res = await _close_tracked(key, "emergency_loss_cap", price)
                actions.append({
                    "symbol": key,
                    "action": "emergency_loss_cap",
                    "pnl_pct": round(pnl_pct, 4),
                    "cap": MAX_UNREALIZED_LOSS_PCT,
                    "elapsed_sec": int(elapsed),
                    "result": res,
                })
                print(
                    f"[real_trade] EMERGENCY loss close {key} pnl={pnl_pct:.3f}% "
                    f"cap=-{MAX_UNREALIZED_LOSS_PCT}%",
                    flush=True,
                )
                continue

            # V.2.10.13/37: بدون SL صرافی بیش از حد مجاز → بستن اجباری
            if (
                not meta.get("sl_on_exchange")
                and elapsed >= MAX_SECONDS_WITHOUT_EXCHANGE_SL
            ):
                logger.error(
                    "REAL FORCE CLOSE %s — no exchange SL after %.0fs",
                    key, elapsed,
                )
                res = await _close_tracked(key, "no_exchange_sl", price)
                actions.append({
                    "symbol": key,
                    "action": "force_close_no_sl",
                    "elapsed_sec": int(elapsed),
                    "result": res,
                })
                continue

            if (
                progress >= lock_progress
                and pnl_pct >= lock_min_profit
                and not meta.get("profit_locked")
                and not (_is_range and not RANGE_PROFIT_LOCK)  # V.2.11.8: رنج تا TP (میانه)
            ):
                reason = "profit_lock_regime" if _regime_for_exits else "profit_lock"
                meta["exit_decision"] = {
                    "reason": reason, "progress": round(float(progress), 4), "pnl_pct": round(float(pnl_pct), 4),
                    "lock_progress": lock_progress, "lock_min_profit": lock_min_profit,
                    "regime_adverse": bool(regime_adverse), "regime_applied": _regime_for_exits,
                }
                res = await _close_tracked(key, reason, price)
                actions.append({
                    "symbol": key,
                    "action": reason,
                    "regime_adverse": regime_adverse,
                    "result": res,
                })
                continue

            # ۱b) V.2.10.36 — بستن شناور سود برای آزاد کردن اسلات
            # فقط وقتی سقف پر است (یا فلگ only_if_slots_full خاموش باشد)
            if ENABLE_FLOAT_PROFIT_EXIT and not meta.get("profit_locked") and not (_is_range and not RANGE_PROFIT_LOCK):
                try:
                    raw_live = live_info.get("raw") or {}
                    u_usdt = float(raw_live.get("unrealizedPnL") or 0)
                except (TypeError, ValueError):
                    u_usdt = 0.0
                slots_full = n_open >= max(1, _max_pos_for_float)
                if not FLOAT_ONLY_IF_SLOTS_FULL:
                    slots_full = True
                # V.2.10.40: حداقل FLOAT_MIN_R برابر فاصله SL اولیه
                try:
                    _sl0 = float(meta.get("original_stop_loss") or meta.get("stop_loss") or 0)
                    _en0 = float(meta.get("entry") or entry or 0)
                    _sl_dist = abs(_en0 - _sl0) / _en0 * 100 if _en0 > 0 and _sl0 > 0 else 0.0
                except Exception:
                    _sl_dist = 0.0
                _min_pct_r = max(FLOAT_MIN_PROFIT_PCT, FLOAT_MIN_R * _sl_dist) if _sl_dist > 0 else FLOAT_MIN_PROFIT_PCT
                if (
                    slots_full
                    and not meta.get("age_unknown")
                    and elapsed >= FLOAT_MIN_ELAPSED_SEC
                    and pnl_pct >= _min_pct_r
                    and u_usdt >= FLOAT_MIN_PROFIT_USDT
                ):
                    res = await _close_tracked(key, "float_profit_slot", price)
                    actions.append({
                        "symbol": key,
                        "action": "float_profit_slot",
                        "pnl_pct": round(pnl_pct, 4),
                        "u_usdt": round(u_usdt, 4),
                        "elapsed_sec": int(elapsed),
                        "n_open": n_open,
                        "result": res,
                    })
                    print(
                        f"[real_trade] FLOAT profit close {key} pnl={pnl_pct:.3f}% "
                        f"u={u_usdt:.3f}$ elapsed={int(elapsed)}s n_open={n_open}",
                        flush=True,
                    )
                    continue

            # ۲) V.2.10.60 — خروج کهنه پس از max_hold (سشن بعدی / رنج طولانی)
            try:
                _prev_min = meta.get("min_unrealized_pct")
                if _prev_min is None or float(pnl_pct) < float(_prev_min):
                    meta["min_unrealized_pct"] = round(float(pnl_pct), 4)
            except Exception:
                pass

            if (
                ENABLE_STALE_SESSION_EXIT
                and not meta.get("age_unknown")
                and elapsed >= MAX_HOLD_SECONDS
            ):
                try:
                    _min_u = float(meta.get("min_unrealized_pct")) if meta.get("min_unrealized_pct") is not None else float(pnl_pct)
                except (TypeError, ValueError):
                    _min_u = float(pnl_pct)

                # ۲a) سود جاری بعد از ۲h → بستن با سود (کف خالص‌محور ≥0.15 از .61)
                if pnl_pct >= STALE_PROFIT_MIN_PCT:
                    res = await _close_tracked(key, "stale_profit_exit", price)
                    actions.append({
                        "symbol": key,
                        "action": "stale_profit_exit",
                        "pnl_pct": round(pnl_pct, 4),
                        "elapsed_sec": int(elapsed),
                        "result": res,
                    })
                    print(
                        f"[real_trade] STALE profit exit {key} pnl={pnl_pct:.3f}% "
                        f"elapsed={int(elapsed)}s",
                        flush=True,
                    )
                    continue

                # ۲b) برگشت از ضرر به باند خنثی → بستن نزدیک BE (نیاز به had_loss)
                if (
                    pnl_pct >= STALE_NEUTRAL_MIN_PCT
                    and pnl_pct < STALE_PROFIT_MIN_PCT
                    and _min_u <= STALE_NEUTRAL_HAD_LOSS_PCT
                ):
                    res = await _close_tracked(key, "stale_neutral_exit", price)
                    actions.append({
                        "symbol": key,
                        "action": "stale_neutral_exit",
                        "pnl_pct": round(pnl_pct, 4),
                        "min_unrealized_pct": round(_min_u, 4),
                        "elapsed_sec": int(elapsed),
                        "result": res,
                    })
                    print(
                        f"[real_trade] STALE neutral exit {key} pnl={pnl_pct:.3f}% "
                        f"min_u={_min_u:.3f}% elapsed={int(elapsed)}s",
                        flush=True,
                    )
                    continue

                # ۲b2) V.2.10.74.3 — فقط وقتی بعد از تخمین کارمزد پایانی نزدیک صفر است
                # هدف: جلوگیری از بستن اجباری مثل XLM (−0.08$ ≈ یک RT fee)
                try:
                    _fee_est = float(STALE_FLAT_EXIT_FEE_EST)
                    # اگر notional داریم، ~0.04٪ یک طرف به‌عنوان کف تخمین
                    _notional = abs(float(meta.get("entry") or entry or 0) * float(meta.get("quantity") or 0))
                    if _notional > 0:
                        _fee_est = max(_fee_est, _notional * 0.0004)
                except Exception:
                    _fee_est = float(STALE_FLAT_EXIT_FEE_EST)
                try:
                    _u = float(u_usdt)
                except Exception:
                    _u = 0.0
                _net_after_fee = _u - abs(_fee_est)
                if (
                    pnl_pct >= STALE_FLAT_MIN_PCT
                    and pnl_pct < STALE_PROFIT_MIN_PCT
                    and _net_after_fee >= -abs(STALE_FLAT_MAX_LOSS_USDT)
                ):
                    res = await _close_tracked(key, "stale_flat_exit", price)
                    actions.append({
                        "symbol": key,
                        "action": "stale_flat_exit",
                        "pnl_pct": round(pnl_pct, 4),
                        "u_usdt": round(_u, 4),
                        "net_after_fee_est": round(_net_after_fee, 4),
                        "fee_est": round(_fee_est, 4),
                        "elapsed_sec": int(elapsed),
                        "result": res,
                    })
                    print(
                        f"[real_trade] STALE flat exit {key} pnl={pnl_pct:.3f}% "
                        f"u={_u:.3f}$ net_est={_net_after_fee:.3f}$ fee≈{_fee_est:.3f}$ "
                        f"elapsed={int(elapsed)}s",
                        flush=True,
                    )
                    continue

            # ۲c/۲d) V.2.10.83 — سقف ۲h هوشمند:
            # اگر هنوز مثبت است و قیمت سمت سود (بالای ورود برای long / زیر ورود برای short)،
            # اجباری نبند؛ صبر تا برگشت نزدیک صفر خنثی یا SL/TP/float.
            # peak سود در meta برای تشخیص «داشته سود».
            try:
                _peak = float(meta.get("peak_unrealized_pct") or 0)
                if pnl_pct > _peak:
                    meta["peak_unrealized_pct"] = float(pnl_pct)
                    _peak = float(pnl_pct)
            except Exception:
                _peak = 0.0

            def _still_favorable_side() -> bool:
                try:
                    e0 = float(entry or 0)
                    px = float(price or 0)
                    if e0 <= 0 or px <= 0:
                        return pnl_pct > 0.05
                    if direction == "long":
                        return px >= e0 and pnl_pct > 0.05
                    return px <= e0 and pnl_pct > 0.05
                except Exception:
                    return pnl_pct > 0.05

            # برگشت به خنثی بعد از ۲h (اگر قبلاً سود داشته)
            if (
                not meta.get("age_unknown")
                and elapsed >= MAX_HOLD_SECONDS
                and _peak >= 0.20
                and abs(float(pnl_pct)) <= max(0.12, float(MIN_NET_CLOSE_PNL_PCT))
            ):
                res = await _close_tracked(key, "max_hold_return_flat", price)
                actions.append({
                    "symbol": key,
                    "action": "max_hold_return_flat",
                    "pnl_pct": round(pnl_pct, 4),
                    "peak_unrealized_pct": round(_peak, 4),
                    "elapsed_sec": int(elapsed),
                    "result": res,
                })
                print(
                    f"[real_trade] MAX_HOLD return_flat {key} pnl={pnl_pct:.3f}% peak={_peak:.3f}% "
                    f"elapsed={int(elapsed)}s",
                    flush=True,
                )
                continue

            # تایم‌اوت کلاسیک فقط اگر دیگر روند مثبت مطلوب نیست
            if (
                not meta.get("age_unknown")
                and elapsed >= MAX_HOLD_SECONDS
                and pnl_pct >= MIN_NET_CLOSE_PNL_PCT
                and not _still_favorable_side()
            ):
                res = await _close_tracked(key, "timeout", price)
                actions.append({"symbol": key, "action": "timeout", "result": res})
                continue

            # اگر بعد از ۲h هنوز مثبت و مطلوب است → ادامه بده (لاگ یک‌بار هر چند دقیقه)
            if (
                not meta.get("age_unknown")
                and elapsed >= MAX_HOLD_SECONDS
                and _still_favorable_side()
            ):
                _last_ext = float(meta.get("_last_extend_log_ts") or 0)
                if time.time() - _last_ext > 300:
                    meta["_last_extend_log_ts"] = time.time()
                    print(
                        f"[real_trade] MAX_HOLD extend {key} pnl={pnl_pct:.3f}% "
                        f"elapsed={int(elapsed)}s (positive trend — wait flat/SL/TP)",
                        flush=True,
                    )
                # سخت‌گیرانه: بعد از ۴h حتی اگر مثبت، فقط اگر نزدیک TP نیست ببند با timeout
                if elapsed >= int(MAX_HOLD_SECONDS * 2) and pnl_pct < float(STALE_PROFIT_MIN_PCT):
                    res = await _close_tracked(key, "timeout_extended", price)
                    actions.append({
                        "symbol": key,
                        "action": "timeout_extended",
                        "pnl_pct": round(pnl_pct, 4),
                        "elapsed_sec": int(elapsed),
                        "result": res,
                    })
                    continue
                # وگرنه skip force
                pass
            elif (
                not meta.get("age_unknown")
                and elapsed >= int(MAX_HOLD_SECONDS * 1.5)
                and pnl_pct >= -1.0
                and pnl_pct < STALE_PROFIT_MIN_PCT
            ):
                try:
                    _u2 = float(u_usdt)
                except Exception:
                    _u2 = 0.0
                if _u2 >= -abs(STALE_FLAT_MAX_LOSS_USDT) * 2 or elapsed >= int(MAX_HOLD_SECONDS * 2):
                    res = await _close_tracked(key, "max_hold_force", price)
                    actions.append({
                        "symbol": key,
                        "action": "max_hold_force",
                        "pnl_pct": round(pnl_pct, 4),
                        "u_usdt": round(_u2, 4),
                        "elapsed_sec": int(elapsed),
                        "result": res,
                    })
                    print(
                        f"[real_trade] MAX_HOLD_FORCE {key} pnl={pnl_pct:.3f}% "
                        f"u={_u2:.3f}$ elapsed={int(elapsed)}s",
                        flush=True,
                    )
                    continue

            # ۳) اگر SL روی صرافی تأیید نشده، دوباره ثبت کن
            if not meta.get("sl_on_exchange"):
                try:
                    tpsl = await toobit_private.attach_tpsl_and_verify(
                        symbol=key,
                        direction=direction,
                        take_profit=str(meta.get("target")),
                        stop_loss=str(meta.get("stop_loss")),
                        quantity=str(meta.get("quantity") or live_info.get("qty") or ""),
                    )
                    meta["sl_on_exchange"] = bool(tpsl.get("sl_on_exchange"))
                    meta["tp_on_exchange"] = bool(tpsl.get("tp_on_exchange"))
                    meta["tpsl_source"] = tpsl.get("source")
                    actions.append({
                        "symbol": key,
                        "action": "tpsl_retry",
                        "sl_on_exchange": meta["sl_on_exchange"],
                    })
                    print(
                        f"[real_trade] TPSL retry {key} sl={meta['sl_on_exchange']}",
                        flush=True,
                    )
                except Exception as e:
                    logger.warning("TPSL retry failed %s: %s", key, e)

            # به‌روزرسانی وضعیت لحظه‌ای برای پنل
            meta["current_price"] = price
            meta["progress"] = round(progress, 3)
            meta["unrealized_pct"] = round(pnl_pct, 3)
            meta["elapsed_sec"] = int(elapsed)

        else:
            # V.2.10.41 — پوزیشن باز روی صرافی بدون meta حافظه (بعد از ری‌استارت)
            # اولویت: دیسک → TPSL واقعی صرافی → openTime صرافی → حدس محافظه‌کار
            if key not in _tracked:
                rec = {
                    "trade_id": f"recovered_{key}_{int(now)}",
                    "symbol": key,
                    "direction": direction,
                    "signal_entry": entry,
                    "fill_entry": entry if entry else None,
                    "entry": entry,  # از avgPrice صرافی — Fill واقعی
                    "stop_loss": entry * (0.99 if direction == "long" else 1.01),
                    "original_stop_loss": entry * (0.99 if direction == "long" else 1.01),
                    "target": entry * (1.01 if direction == "long" else 0.99),
                    "quantity": str(live_info.get("qty") or ""),
                    "opened_at": now,  # fallback؛ پایین‌تر از openTime واقعی پر می‌شود
                    "age_unknown": True,  # V.2.10.55: تا openTime پیدا نشود
                    "profit_locked": False,
                    "status": "open",
                    "recovered": True,
                    "sl_on_exchange": False,
                    "tp_on_exchange": False,
                    "app_version": APP_VERSION,
                    "current_price": price,
                    "unrealized_pct": round(_unrealized_pct(direction, entry, price), 3),
                }
                # ۱) SL/TP واقعی از سفارش‌های باز صرافی
                try:
                    insp = await toobit_private.inspect_account()
                    tpsl_block = (insp or {}).get("tpsl_orders") or {}
                    orders = tpsl_block.get("orders") or []
                    sl_px = tp_px = None
                    sl_cid = tp_cid = None
                    for o in orders:
                        if not isinstance(o, dict):
                            continue
                        osym = _norm_symbol(str(o.get("symbol") or ""))
                        if osym and osym != key:
                            continue
                        kind = str(o.get("kind") or "").lower()
                        sp = o.get("stopPrice")
                        try:
                            spf = float(sp) if sp is not None else None
                        except Exception:
                            spf = None
                        cid = o.get("clientOrderId")
                        if kind == "sl" and spf:
                            sl_px = spf
                            sl_cid = cid
                        elif kind == "tp" and spf:
                            tp_px = spf
                            tp_cid = cid
                    if sl_px:
                        rec["stop_loss"] = sl_px
                        rec["original_stop_loss"] = sl_px
                        rec["sl_on_exchange"] = True
                        if sl_cid:
                            rec["sl_client_order_id"] = str(sl_cid)
                    if tp_px:
                        rec["target"] = tp_px
                        rec["tp_on_exchange"] = True
                        if tp_cid:
                            rec["tp_client_order_id"] = str(tp_cid)
                except Exception as e:
                    logger.warning("recover TPSL read failed %s: %s", key, e)

                # ۲) opened_at واقعی از openTime صرافی (اگر در live_info یا history باشد)
                try:
                    ot = live_info.get("openTime") or live_info.get("opened") or live_info.get("ctime")
                    if ot is None:
                        # بعضی پاسخ‌ها timestamp میلی‌ثانیه دارند
                        raw_row = live_info.get("raw") or {}
                        ot = raw_row.get("openTime") or raw_row.get("ctime")
                    if ot is not None:
                        ots = float(ot)
                        if ots > 1e12:  # ms → s
                            ots = ots / 1000.0
                        if ots > 1e9:  # sanity unix
                            rec["opened_at"] = ots
                            rec["opened_at_source"] = "exchange_openTime"
                except Exception as e:
                    logger.warning("recover openTime failed %s: %s", key, e)

                # ۳) V.2.10.55: سن مصنوعی نساز — age_unknown بگذار
                #    float/timeout وابسته به زمان روی پوزیشن ناشناس اعمال نشود
                #    (emergency و SL صرافی همچنان فعال‌اند)
                if rec.get("opened_at_source") != "exchange_openTime":
                    rec["opened_at_uncertain"] = True
                    rec["age_unknown"] = True
                    # opened_at = now می‌ماند؛ elapsed کوچک است تا time-based soft-exit زود نزند
                else:
                    rec["age_unknown"] = False
                    rec["opened_at_uncertain"] = False

                _tracked[key] = rec
                try:
                    _save_tracked()
                except Exception:
                    pass
                print(
                    f"[real_trade] RECOVERED {key} opened_at={rec.get('opened_at')} "
                    f"src={rec.get('opened_at_source')} sl={rec.get('stop_loss')} tp={rec.get('target')}",
                    flush=True,
                )
                try:
                    from database.supabase_client import upsert_open_real_trade
                    await upsert_open_real_trade(rec)
                except Exception as _re:
                    logger.warning("upsert recovered to supabase failed: %s", _re)
            pnl_pct = _unrealized_pct(direction, entry, price)
            if pnl_pct >= FALLBACK_PROFIT_PCT:
                # V.2.10.56: از ledger واحد استفاده کن (نه close مستقیم + PnL=0)
                if key not in _tracked or _tracked.get(key, {}).get("status") != "open":
                    _tracked[key] = {
                        "trade_id": f"recover_fb_{key}_{uuid.uuid4().hex[:8]}",
                        "symbol": key,
                        "direction": direction,
                        "entry": float(entry or 0),
                        "fill_entry": float(entry or 0) or None,
                        "signal_entry": float(entry or 0) or None,
                        "stop_loss": 0.0,
                        "target": 0.0,
                        "quantity": f"{live_info['qty']:.8f}".rstrip("0").rstrip("."),
                        "margin_usdt": float((live_info.get("raw") or {}).get("margin") or 0) or 0.0,
                        "opened_at": time.time(),
                        "status": "open",
                        "age_unknown": True,
                        "app_version": APP_VERSION,
                    }
                close_res = await _close_tracked(key, "fallback_profit_close", price)
                actions.append({
                    "symbol": key,
                    "action": "fallback_profit_close",
                    "pnl_pct": pnl_pct,
                    "result": close_res,
                })
                if close_res.get("ok"):
                    logger.info(
                        "REAL FALLBACK CLOSE %s pnl≈%.2f%% realized=%s source=%s",
                        key, pnl_pct,
                        close_res.get("approx_pnl"),
                        (_tracked.get(key) or {}).get("pnl_source"),
                    )

    # پاک‌سازی ردیاب بسته‌شده‌های قدیمی (بیش از ۱ ساعت)
    for key in list(_tracked.keys()):
        if _tracked[key].get("status") != "open":
            closed_at = _tracked[key].get("closed_at") or 0
            if now - closed_at > 3600:
                del _tracked[key]

    try:
        _save_tracked()
    except Exception:
        pass
    return {"open_exchange": n_open, "tracked_open": sum(1 for t in _tracked.values() if t.get("status") == "open"), "actions": actions}


async def background_real_manager_loop() -> None:
    """حلقه مادام‌العمر مدیریت پوزیشن‌های ریل — بدون نیاز به فرانت یا کاربر."""
    global _supabase_restored
    logger.info("REAL manager loop started (interval=%ss)", MANAGER_INTERVAL_SECONDS)
    # V.2.10.42 — یک‌بار بازیابی open از Supabase
    if not _supabase_restored:
        try:
            n = await restore_tracked_from_supabase()
            _supabase_restored = True
            logger.info("supabase restore on manager start: %s positions", n)
        except Exception as e:
            logger.warning("supabase restore on start failed: %s", e)
            _supabase_restored = True  # دوباره هر ۴۵ث اسپم نکن
    while True:
        try:
            if REAL_TRADING_ENABLED and toobit_private.keys_configured():
                summary = await manage_open_real_positions()
                if summary.get("actions"):
                    logger.info("REAL manager actions: %s", summary["actions"])
        except Exception:
            logger.exception("REAL manager loop error")
        await asyncio.sleep(MANAGER_INTERVAL_SECONDS)




def _build_symbol_performance(closed: list[dict], min_n: int = 1) -> list[dict]:
    """
    V.2.10.53 — آمار دائمی هر نماد از تاریخچهٔ بسته:
    WR · میانگین برد/باخت · PnL · تفکیک exit_reason.
    فقط مشاهده‌ای است؛ روی منطق ورود اثر ندارد.
    """
    by_sym: dict[str, list[dict]] = {}
    for r in closed or []:
        sym = str(r.get("symbol") or "").replace("-SWAP-USDT", "").replace("USDT", "").upper().strip()
        if not sym:
            continue
        by_sym.setdefault(sym, []).append(r)

    rows_out: list[dict] = []
    for sym, items in by_sym.items():
        n = len(items)
        if n < min_n:
            continue
        # V.2.10.74 — WIN/LOSS/SCRATCH جدا (SCRATCH از مخرج WR خام خارج می‌شود)
        classified = []
        for x in items:
            pnl_x = float(x.get("approx_pnl") or 0)
            # V.2.10.74.1 — همیشه از net PnL؛ برچسب ذخیره‌شدهٔ اشتباه را بازنویسی نکن در آمار
            oc = _outcome_class(None, pnl_x)
            classified.append((x, pnl_x, oc))
        wins = [pnl for _, pnl, oc in classified if oc == "WIN"]
        losses = [pnl for _, pnl, oc in classified if oc == "LOSS"]
        scratches = [pnl for _, pnl, oc in classified if oc == "SCRATCH"]
        flats = n - len(wins) - len(losses) - len(scratches)
        total_pnl = sum(float(x.get("approx_pnl") or 0) for x in items)
        by_reason: dict[str, int] = {}
        by_class: dict[str, int] = {}
        for x, pnl_x, oc in classified:
            reason = str(x.get("exit_reason") or "unknown")
            by_reason[reason] = by_reason.get(reason, 0) + 1
            by_class[oc] = by_class.get(oc, 0) + 1
        soft_wins = sum(
            1 for x in items
            if float(x.get("approx_pnl") or 0) > 0
            and str(x.get("exit_reason") or "") in (
                "profit_lock", "profit_lock_regime", "float_profit_slot",
                "timeout", "regime_soft_exit", "breakeven_sl",
                "exchange_take_profit", "exchange_take_profit_approx",
            )
        )
        hard_sl = sum(
            1 for x in items
            if str(x.get("exit_reason") or "") in (
                "exchange_stop_loss", "exchange_stop_loss_approx", "exchange",
            )
            and float(x.get("approx_pnl") or 0) < 0
        )
        avg_win = (sum(wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(losses) / len(losses)) if losses else 0.0
        decisive = len(wins) + len(losses)
        wr = (100.0 * len(wins) / decisive) if decisive else 0.0
        wr_raw = (100.0 * len(wins) / n) if n else 0.0
        rows_out.append({
            "symbol": sym,
            "n": n,
            "wins": len(wins),
            "losses": len(losses),
            "scratches": len(scratches),
            "flats": flats,
            "wr_pct": round(wr, 1),
            "wr_raw_pct": round(wr_raw, 1),
            "total_pnl": round(total_pnl, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "payoff": round(abs(avg_win / avg_loss), 3) if avg_loss else None,
            "soft_wins": soft_wins,
            "hard_sl_losses": hard_sl,
            "by_exit_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
            "by_outcome_class": dict(sorted(by_class.items(), key=lambda kv: -kv[1])),
        })
    rows_out.sort(key=lambda x: (x["n"], x["total_pnl"]), reverse=True)
    return rows_out


# ─────────────────────────────────────────────────────────────
# V.2.10.100 — تطبیق یک‌به‌یک تاریخچهٔ صرافی با حافظه
# در .99 کافی بود قیمت ورود نزدیک (۰٫۵٪)، یا زمان بستن نزدیک، یا شناسهٔ بستن «sd_c_» باشد تا
# برچسب نسخه/دلیل یک معاملهٔ دیگر روی ردیف صرافی بنشیند (بدون چک جهت). نتیجه: معاملات ماه قبل
# با برچسب .99 و علت fill_invalidated_trade.
# قاعدهٔ جدید: (۱) شناسهٔ صرافی ذخیره‌شده، (۲) هم‌نماد + هم‌جهت + زمان باز شدن ≤ ۱۸۰ ثانیه،
# (۳) هم‌نماد + هم‌جهت + زمان بستن ≤ ۱۸۰ ثانیه و قیمت ورود ≤ ۰٫۳٪. هر ردیف حافظه حداکثر یک‌بار.
# بدون تطبیق: نسخه و دلیل «نامعلوم» می‌ماند — هرگز نسخهٔ زنده جعل نمی‌شود.
# ─────────────────────────────────────────────────────────────
MATCH_OPEN_TOL_SEC = 180.0
MATCH_CLOSE_TOL_SEC = 180.0
MATCH_PRICE_TOL = 0.003


def _mem_f(h: dict, *keys: str) -> float | None:
    for k in keys:
        try:
            v = h.get(k)
            if v is None or v == "":
                continue
            x = float(v)
            if x > 1e12:
                x = x / 1000.0
            if x > 0:
                return x
        except (TypeError, ValueError):
            continue
    return None


def _match_exchange_rows_to_memory(rows: list[dict], memory: list[dict]) -> dict[str, dict]:
    """rows = toobit_private.normalize_history_rows(...) ؛ خروجی: exchange_row_id → ردیف حافظه."""
    out: dict[str, dict] = {}
    used: set[int] = set()
    by_key: dict[str, list[dict]] = {}
    for h in memory or []:
        if not isinstance(h, dict):
            continue
        k = _norm_symbol(str(h.get("symbol") or ""))
        if k:
            by_key.setdefault(k, []).append(h)

    def _dir(h: dict) -> str:
        return "short" if str(h.get("direction") or "").lower() == "short" else "long"

    # (۱) شناسهٔ صرافی که قبلاً روی ردیف حافظه نشسته
    for r in rows:
        if not r.get("id_is_exchange"):
            continue
        for h in by_key.get(_norm_symbol(r["key"]), []):
            if id(h) in used:
                continue
            if str(h.get("exchange_position_id") or "") == str(r["id"]):
                out[r["id"]] = h
                used.add(id(h))
                break

    def _greedy(cands: list[tuple[float, str, dict]]) -> None:
        cands.sort(key=lambda c: c[0])
        for _d, rid, h in cands:
            if rid in out or id(h) in used:
                continue
            out[rid] = h
            used.add(id(h))

    # (۲) زمان باز شدن
    cands: list[tuple[float, str, dict]] = []
    for r in rows:
        if r["id"] in out or not r.get("opened_ts"):
            continue
        for h in by_key.get(_norm_symbol(r["key"]), []):
            if id(h) in used or _dir(h) != r["direction"]:
                continue
            ho = _mem_f(h, "opened_at")
            if ho is None:
                continue
            d = abs(float(r["opened_ts"]) - ho)
            if d <= MATCH_OPEN_TOL_SEC:
                cands.append((d, r["id"], h))
    _greedy(cands)

    # (۳) زمان بستن + قیمت ورود
    cands = []
    for r in rows:
        if r["id"] in out:
            continue
        for h in by_key.get(_norm_symbol(r["key"]), []):
            if id(h) in used or _dir(h) != r["direction"]:
                continue
            hc = _mem_f(h, "exchange_closed_at", "closed_at")
            he = _mem_f(h, "fill_entry", "entry")
            if hc is None or he is None or not r.get("entry"):
                continue
            dt = abs(float(r["closed_ts"]) - hc)
            dp = abs(float(r["entry"]) - he) / he
            if dt <= MATCH_CLOSE_TOL_SEC and dp <= MATCH_PRICE_TOL:
                cands.append((dt + dp * 1e4, r["id"], h))
    _greedy(cands)
    return out


_HIST_CACHE: dict[str, Any] = {"ts": 0.0, "limit": 0, "rows": None}
HIST_CACHE_TTL_SEC = 20.0


async def _exchange_history_rows(limit: int = 100, max_age: float | None = None) -> list[dict] | None:
    """V.2.10.101: کش کوتاه (۲۰ ثانیه) تا status/آمار/دفتر/PnL روزانه در یک دور چند بار صرافی را صدا نزنند.
    max_age=0 → حتماً تازه."""
    ttl = HIST_CACHE_TTL_SEC if max_age is None else float(max_age)
    now = time.time()
    if (
        ttl > 0
        and _HIST_CACHE["rows"] is not None
        and now - float(_HIST_CACHE["ts"]) < ttl
        and int(_HIST_CACHE["limit"]) >= int(limit)
    ):
        return list(_HIST_CACHE["rows"])
    try:
        raw = await toobit_private.get_history_positions(limit=limit)
    except Exception as e:
        logger.warning("history positions fetch failed: %s", e)
        return None
    if isinstance(raw, dict) and raw.get("error"):
        return None
    try:
        rows = toobit_private.normalize_history_rows(raw)
    except Exception as e:
        logger.warning("normalize history failed: %s", e)
        return None
    _HIST_CACHE.update({"ts": now, "limit": int(limit), "rows": list(rows)})
    return rows


_DB_CTX_CACHE: dict[str, Any] = {"ts": 0.0, "rows": []}
DB_CTX_TTL_SEC = 120.0


async def _db_context_rows() -> list[dict]:
    """V.2.10.101 — ردیف‌های real_trades از Supabase به شکل حافظه (کش ۱۲۰ ثانیه)."""
    now = time.time()
    if _DB_CTX_CACHE["rows"] and now - float(_DB_CTX_CACHE["ts"]) < DB_CTX_TTL_SEC:
        return list(_DB_CTX_CACHE["rows"])
    out: list[dict] = []
    try:
        from database.supabase_client import get_real_trades
        for row in (await get_real_trades(limit=300)) or []:
            h = _db_row_to_memory(row)
            if h:
                out.append(h)
    except Exception as e:
        logger.debug("db context fetch failed: %s", e)
        return list(_DB_CTX_CACHE["rows"] or [])
    _DB_CTX_CACHE.update({"ts": now, "rows": out})
    return list(out)


async def _memory_context() -> list[dict]:
    """حافظهٔ این سشن + زمینهٔ Supabase (برای اینکه بعد از هر دیپلوی نسخه/استراتژی/دلیل خروج گم نشود)."""
    mem = list(_history)
    known = {str(h.get("trade_id") or "") for h in mem if h.get("trade_id")}
    for h in await _db_context_rows():
        tid = str(h.get("trade_id") or "")
        if tid and tid in known:
            continue
        mem.append(h)
        if tid:
            known.add(tid)
    return mem


_SOFT_REASONS_V100 = {
    "profit_lock", "profit_lock_regime", "timeout", "float_profit_slot",
    "stale_profit_exit", "stale_neutral_exit", "stale_flat_exit", "max_hold_force",
    "regime_soft_exit", "regime_adverse_loss_exit", "emergency_loss_cap", "manual_close", "manual_ui",
    "breakeven_sl", "regime_tightened_sl", "force_close_no_sl",
    "undersized_margin", "fallback_profit_close", "bot_close_unspecified",
    "fill_invalidated_trade", "range_time_stop", "range_invalidated", "range_fail_exit", "range_small_tp",
    "range_profit_floor", "profit_floor_sl", "rs_time_stop", "tsmom_time_stop", "tsmom_trend_exit", "rsi_time_stop",
    "rs_trail_close", "rs_trail_stop",
}


async def _exchange_recent_closed(limit: int = 15) -> list[dict]:
    """پوزیشن‌های بستهٔ اخیر از خود صرافی + غنی‌سازی با حافظه فقط از راه تطبیق یک‌به‌یک (V.2.10.100)."""
    try:
        rows = await _exchange_history_rows(limit=max(limit, 40))
        if rows is None:
            return []
        rows = [r for r in rows if str(r.get("leverage") or "") in ("", "5", "5.0")]
        rows.sort(key=lambda r: float(r.get("closed_ts") or 0), reverse=True)
        rows = rows[: max(1, int(limit))]
        mapping = _match_exchange_rows_to_memory(rows, await _memory_context())
        out: list[dict] = []
        for r in rows:
            h = mapping.get(r["id"])
            pnl_val = float(r.get("pnl") or 0)
            if h is not None:
                mem_reason = str(h.get("exit_reason") or "")
                matched_soft = mem_reason in _SOFT_REASONS_V100 or mem_reason not in ("", "exchange", "external_or_unknown")
                exit_reason = mem_reason if matched_soft else "exchange"
                app_ver = h.get("app_version")  # نسخهٔ باز شدن؛ app_version_close هرگز جایگزین نمی‌شود
                settings_snap = h.get("settings_snapshot")
                strategy = h.get("strategy_id") or (settings_snap or {}).get("strategy_id")
                trade_id = h.get("trade_id")
                if r.get("id_is_exchange") and not h.get("exchange_position_id"):
                    h["exchange_position_id"] = r["id"]
            else:
                matched_soft = False
                exit_reason = "exchange"
                app_ver = None
                settings_snap = None
                strategy = None
                trade_id = None
            if exit_reason in ("exchange", "external_or_unknown", "") and r.get("entry") and r.get("exit"):
                exit_reason = _infer_exit_reason_from_levels(
                    r["direction"], float(r["entry"]), float(r["exit"]), None, None, None,
                )
            exit_reason, reason_conf = _reconcile_exit_reason_with_pnl(exit_reason, pnl_val)
            if matched_soft and h is not None and h.get("reason_confidence") in ("certain", "soft", "approx"):
                reason_conf = h.get("reason_confidence")
            try:
                outcome_cls = _outcome_class(exit_reason, pnl_val)
            except Exception:
                outcome_cls = "UNKNOWN"
            out.append({
                "symbol": r["key"],
                "direction": r["direction"],
                "entry": r.get("entry"),
                "exit_price": r.get("exit"),
                "approx_pnl": r.get("pnl"),
                "fees": r.get("fees"),
                "exit_reason": exit_reason,
                "reason_confidence": reason_conf,
                "outcome_class": outcome_cls,
                "status": "closed",
                "source": "toobit",
                "leverage": r.get("leverage"),
                "app_version": app_ver,
                "app_version_close": (h or {}).get("app_version_close") if h is not None else None,
                "strategy_id": strategy,
                "trade_id": trade_id,
                "exchange_position_id": r["id"] if r.get("id_is_exchange") else None,
                "match": "memory" if h is not None else "exchange_only",
                "settings_snapshot": settings_snap,
                "opened_at": r.get("opened_ts"),
                "closed_at": r.get("closed_ts"),
            })
        return out
    except Exception as e:
        logger.warning("exchange recent closed failed: %s", e)
        return []


def _iso_to_ts(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _db_row_to_memory(row: dict) -> dict | None:
    """ردیف real_trades Supabase → شکل ردیف حافظه (meta_json روی ستون‌ها)."""
    if not isinstance(row, dict) or not row.get("trade_id"):
        return None
    h = dict(row)
    mj = row.get("meta_json") if isinstance(row.get("meta_json"), dict) else {}
    for k, v in mj.items():
        if v is not None and h.get(k) in (None, ""):
            h[k] = v
    h["opened_at"] = _iso_to_ts(mj.get("opened_at_unix")) or _iso_to_ts(row.get("opened_at"))
    h["closed_at"] = _iso_to_ts(row.get("closed_at"))
    h["source_db"] = True
    return h


def _ledger_row(h: dict | None, x: dict | None) -> dict:
    """یک ردیف دفتر: حقیقت مالی از صرافی (x)، زمینه از حافظه (h)."""
    h = h or {}
    x = x or {}
    life = h.get("lifecycle_observation") if isinstance(h.get("lifecycle_observation"), dict) else {}
    snap = h.get("settings_snapshot") if isinstance(h.get("settings_snapshot"), dict) else {}
    pnl = x.get("pnl") if x else h.get("realized_pnl", h.get("approx_pnl"))
    return {
        "trade_id": h.get("trade_id"),
        "exchange_position_id": (x.get("id") if x.get("id_is_exchange") else None) or h.get("exchange_position_id"),
        "symbol": x.get("key") or _norm_symbol(str(h.get("symbol") or "")),
        "direction": x.get("direction") or h.get("direction"),
        "strategy_id": h.get("strategy_id") or snap.get("strategy_id"),
        "app_version": h.get("app_version"),
        "opened_at": x.get("opened_ts") or h.get("opened_at"),
        "closed_at": x.get("closed_ts") or h.get("exchange_closed_at") or h.get("closed_at"),
        "entry_signal": h.get("signal_entry") or h.get("entry"),
        "entry_fill": x.get("entry") or h.get("fill_entry"),
        "exit_price": x.get("exit") or h.get("exit_price"),
        "pnl_usdt": pnl,
        "pnl_source": "exchange" if x else (h.get("pnl_source") or "memory"),
        "fees_usdt": x.get("fees") if x else h.get("fees"),
        "exit_reason": h.get("exit_reason"),
        "close_reason_requested": h.get("close_reason_requested"),
        "signal_geom": h.get("signal_geom"),
        "notional_actual": h.get("notional_actual"),
        "risk_usdt_est": h.get("risk_usdt_est"),
        "mfe_pct": life.get("max_favorable_excursion_pct"),
        "mae_pct": life.get("max_adverse_excursion_pct"),
        "mfe_r": life.get("mfe_r"),
        "mae_r": life.get("mae_r"),
        "sl_changes": h.get("sl_changes") or [],
        "exit_thresholds": h.get("exit_thresholds"),
        "exit_decision": h.get("exit_decision"),
        "fill_invalidation": h.get("fill_invalidation"),
        "pre_order": h.get("pre_order"),
        "price_path": h.get("price_path") or [],
        "matched": bool(h) and bool(x),
        # V.2.11.0
        "btc_ctx": h.get("btc_ctx"),
        "drift_follow": h.get("drift_follow"),
        "range_source": h.get("range_source"),
        "entry_mode": h.get("entry_mode"),
        "entry_limit_price": h.get("entry_limit_price"),
        "partial_fill": h.get("partial_fill"),
        "exit_whatif": h.get("exit_whatif"),
        "path_interval": h.get("path_interval"),
        "path_bars": len(h.get("path_1m") or []),
    }


async def real_ledger(version: str | None = None, strategy: str | None = None, limit: int = 100) -> dict[str, Any]:
    """V.2.10.100 — دفتر معاملات برای تحلیل: هر ردیف صرافی یک‌بار، با زمینهٔ تطبیق‌شدهٔ حافظه.

    فیلتر نسخه/استراتژی فقط روی ردیف‌های تطبیق‌شده معنا دارد؛ ردیف بدون تطبیق «unknown» است و
    در فیلتر نسخه حذف می‌شود (هیچ برچسبی جعل نمی‌شود).
    """
    rows = await _exchange_history_rows(limit=100)
    # بعد از ری‌استارت، زمینهٔ معاملات (MFE/MAE، تغییرات SL، مسیر قیمت) از meta_json Supabase برمی‌گردد
    mem = await _memory_context()
    mapping = _match_exchange_rows_to_memory(rows or [], mem) if rows else {}
    used = {id(h) for h in mapping.values()}
    out: list[dict] = []
    for x in rows or []:
        out.append(_ledger_row(mapping.get(x["id"]), x))
    for h in mem:  # حافظه‌ای که در ۱۰۰ ردیف اخیر صرافی نبود (مثلاً قدیمی‌تر)
        if id(h) not in used and str(h.get("status") or "") in ("closed", "closed_external"):
            out.append(_ledger_row(h, None))
    if version:
        out = [r for r in out if str(r.get("app_version") or "") == str(version)]
    if strategy:
        out = [r for r in out if str(r.get("strategy_id") or "") == str(strategy)]
    out.sort(key=lambda r: float(r.get("closed_at") or 0), reverse=True)
    out = out[: max(1, min(int(limit or 100), 300))]
    pnl_vals = [float(r["pnl_usdt"]) for r in out if r.get("pnl_usdt") is not None]
    fee_vals = [float(r["fees_usdt"]) for r in out if r.get("fees_usdt") is not None]
    return {
        "app_version": APP_VERSION,
        "filter": {"version": version, "strategy": strategy},
        "count": len(out),
        "net_pnl_usdt": round(sum(pnl_vals), 6),
        "fees_usdt": round(sum(fee_vals), 6),
        "wins": sum(1 for v in pnl_vals if v > 0.05),
        "losses": sum(1 for v in pnl_vals if v < -0.05),
        "scratches": sum(1 for v in pnl_vals if -0.05 <= v <= 0.05),
        "exchange_rows_available": rows is not None,
        "note": "win/loss با آستانهٔ ±0.05$ (اسکرچ جدا)؛ PnL از صرافی. score احتمال برد نیست.",
        "items": out,
    }


def _settings_for_report() -> dict[str, Any]:
    """V.2.10.101 — همهٔ تنظیمات زنده (همان صفحهٔ Settings) برای گزارش .md. کلید حساس هرگز."""
    out: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    try:
        import runtime_settings as _rs
        cfg = _rs.load() or {}
        defaults = getattr(_rs, "DEFAULTS", {}) or {}
        for k in sorted(cfg):
            lk = str(k).lower()
            if any(x in lk for x in ("password", "secret", "token", "api_key", "apikey", "private")):
                continue
            out[k] = cfg[k]
        changed = sorted(k for k in out if k in defaults and out[k] != defaults[k])
        path = getattr(_rs, "_SETTINGS_FILE", None)
        meta = {
            "n_keys": len(out),
            "saved_file_exists": bool(path and os.path.isfile(path)),
            "saved_file_mtime": (os.path.getmtime(path) if path and os.path.isfile(path) else None),
            "differs_from_defaults": changed,
        }
    except Exception as e:
        meta = {"error": str(e)[:160]}
    return {"values": out, "meta": meta}


def _ledger_compact(row: dict) -> dict:
    """ردیف دفتر برای گزارش وضعیت — بدون price_path کامل (حجم فایل)."""
    r = {k: v for k, v in row.items() if k not in ("price_path", "pre_order")}
    path = row.get("price_path") or []
    r["price_path_points"] = len(path)
    if path:
        step = max(1, len(path) // 12)
        r["price_path_sampled"] = path[::step][:13]
    ch = row.get("sl_changes") or []
    r["sl_changes"] = ch[-4:]
    return r


async def real_stats_summary() -> dict[str, Any]:
    """آمار ریل — اولویت با PnL واقعی صرافی، نه فقط حافظه نرم‌افزار."""
    rows: list[dict] = []
    try:
        from database.supabase_client import get_real_trades
        db_rows = await get_real_trades(limit=500)
        if db_rows:
            rows = db_rows
    except Exception:
        pass
    if not rows:
        rows = list(_history)

    exchange_closed = await _exchange_recent_closed(20)
    # آمار اصلی از صرافی (اهرم ۵)
    if exchange_closed:
        closed = exchange_closed
        wins = [r for r in closed if float(r.get("approx_pnl") or 0) > 0]
        losses = [r for r in closed if float(r.get("approx_pnl") or 0) < 0]
        flat = [r for r in closed if float(r.get("approx_pnl") or 0) == 0]
        total_pnl = sum(float(r.get("approx_pnl") or 0) for r in closed)
        source = "toobit_history"
        note = "آمار از تاریخچه واقعی Toobit (اهرم ۵). نرم‌افزار فقط کمکی است."
    else:
        closed = [r for r in rows if str(r.get("status") or "") not in ("open", "")]
        wins = [r for r in closed if float(r.get("approx_pnl") or 0) > 0]
        losses = [r for r in closed if float(r.get("approx_pnl") or 0) < 0]
        flat = [r for r in closed if float(r.get("approx_pnl") or 0) == 0]
        total_pnl = sum(float(r.get("approx_pnl") or 0) for r in closed)
        source = "memory"
        note = "صرافی در دسترس نبود — آمار از حافظه/سوپابیس (ممکن است با موجودی فرق کند)."

    n = len(closed)
    w = len(wins)
    by_reason: dict[str, int] = {}
    for r in closed:
        reason = str(r.get("exit_reason") or "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1

    open_n = sum(1 for t in _tracked.values() if t.get("status") == "open")
    # recent: اول صرافی، بعد نرم‌افزار openهای اشتباه را قاطی نکن
    recent = exchange_closed[:10] if exchange_closed else [
        {
            "symbol": r.get("symbol"),
            "direction": r.get("direction"),
            "entry": r.get("entry"),
            "exit_price": r.get("exit_price"),
            "approx_pnl": r.get("approx_pnl"),
            "exit_reason": r.get("exit_reason"),
            "score": r.get("score") or r.get("confluence_score"),
            "status": r.get("status"),
        }
        for r in rows[:15]
        if str(r.get("status") or "") != "open"
    ]
    return {
        "app_version": APP_VERSION,
        "open": open_n,
        "closed": n,
        "wins": w,
        "losses": len(losses),
        "flat": len(flat),
        "win_rate": round(100.0 * w / n, 1) if n else None,
        "total_pnl_usdt": round(total_pnl, 4),
        "by_exit_reason": by_reason,
        "recent": recent,
        "source": source,
        "note": note,
    }


def _watchlist_readiness_obs(symbol: str, score: float | None, diagnostics: dict | None = None) -> dict:
    """V.2.10.85 observation-only: Score vs Quality vs Readiness — بدون گیت معامله."""
    d = diagnostics if isinstance(diagnostics, dict) else {}
    try:
        sc = float(score) if score is not None else float(d.get("confluence_score") or 0)
    except Exception:
        sc = 0.0
    try:
        adx = float(d.get("adx_1h") or d.get("adx") or 0)
    except Exception:
        adx = 0.0
    try:
        er = float(d.get("efficiency_ratio_1h") or d.get("er") or 0)
    except Exception:
        er = 0.0
    try:
        ci = float(d.get("chop_index") or d.get("ci") or 50)
    except Exception:
        ci = 50.0
    # Quality 0..100 heuristic (not probability)
    q = 0.0
    q += min(40.0, sc * 0.40)
    q += min(25.0, max(0.0, adx - 15.0) * (25.0 / 25.0))  # ADX 15→40 maps toward 25
    if adx >= 25:
        q = min(40.0, sc * 0.40) + min(25.0, (adx - 15) * 1.0)
    q += min(20.0, er * 40.0)  # ER 0.5 → 20
    q += min(15.0, max(0.0, 70.0 - ci) * 0.3)  # lower CI better
    q = max(0.0, min(100.0, q))
    ready = "WAIT"
    reason = ""
    if sc >= float(MIN_CONFLUENCE_REAL) and adx >= float(globals().get("MIN_ADX_1H_FOR_ENTRY", 20) or 20):
        ready = "READY"
    elif sc < float(MIN_CONFLUENCE_REAL):
        ready = "BLOCKED"
        reason = "CONFLUENCE"
    elif adx < 20:
        ready = "BLOCKED"
        reason = "ADX"
    return {
        "symbol": _norm_symbol(symbol),
        "score": round(sc, 1),
        "quality_pct": round(q, 1),
        "win_probability_pct": None,  # فقط بعد از calibration
        "readiness": ready,
        "readiness_reason": reason,
        "note": "observation_only — not an entry gate",
    }


# V.2.29.0 — گزارش سبک برای فایل وضعیت (status viewer): فقط چیزهایی که برای بررسی لازم است.
_COMPACT_DROP = ("symbol_performance", "symbol_performance_note", "paper_trades", "range_small_tp", "strategy_matrix",
                 "news_impact", "news_impact_by_title", "path_capture_queue", "path_capture_log", "maker_tp",
                 "forward_test", "symbol_direction_tiers", "symbol_direction_policy", "tiers_pnl_unit", "income",
                 "exit_whatif", "watchlist_obs_note", "last_attempts")
_TRADE_KEYS = ("symbol", "direction", "strategy_id", "opened_at", "closed_at", "entry_fill", "exit_price", "pnl_usdt",
               "fees_usdt", "exit_reason", "app_version", "entry", "approx_pnl", "fees")


def compact_status(st: dict) -> dict:
    """status_summary کامل ⇒ نسخهٔ سبک (حدود ۱۰٪ حجم). فرانت/پنل‌ها همچنان نسخهٔ کامل را می‌گیرند."""
    if not isinstance(st, dict):
        return st
    out = {k: v for k, v in st.items() if k not in _COMPACT_DROP}
    try:
        lr = dict(out.get("ledger_recent") or {})
        lr["items"] = [{k: x.get(k) for k in _TRADE_KEYS if k in x} for x in (lr.get("items") or [])[:10]]
        out["ledger_recent"] = lr
        out["recent_closed"] = [{k: x.get(k) for k in _TRADE_KEYS if k in x} for x in (out.get("recent_closed") or [])[:5]]
        bt = dict(out.get("backtest") or {})
        keep = ("enabled", "state", "started_at", "finished_at", "result_app_version", "restored", "result_days",
                "progress", "error", "worker_errors", "fetch_problems")
        dr = {k: {"passes": (v or {}).get("passes"), "n": (v or {}).get("n"),
                  "net_avg_pct": ((v or {}).get("all") or {}).get("net_avg_pct")}
              for k, v in (bt.get("daily_research") or {}).items() if isinstance(v, dict)}
        out["backtest"] = {**{k: bt.get(k) for k in keep if k in bt}, "daily_research": dr}
        gh = dict(out.get("github_strategies") or {})
        gh.pop("repo", None)
        gh.pop("note", None)
        def _f(x, nd=2):
            return "—" if x is None else (f"{x:+.{nd}f}" if isinstance(x, (int, float)) else str(x))

        def _mcs(b):   # V.2.36.0 — Monte Carlo روی فهرست محدود به ۲ پوزیشن هم‌زمان (فقط گزارش)
            mc, cp, wf = b.get("mc") or {}, b.get("capped") or {}, b.get("wf") or []
            if not mc:
                return ""
            w = "/".join(f"{x.get('usd'):+.1f}" for x in wf) if wf else "—"
            if mc.get("flag") in ("insufficient", "error"):
                return f" | mc={mc.get('flag')} cap_n={cp.get('n')}"
            return (f" | mc[{mc.get('flag')}] dd95=${mc.get('dd95_usd')} ({mc.get('dd95_pct_eq')}%) r5=${mc.get('ret5_usd')} "
                    f"pL={mc.get('p_loss')} cap_n={cp.get('n')} cap=${cp.get('net_total_usd')} wf30d=${w}")

        def _exs(b):   # V.2.40.0 — نمادهای اضافه
            x = b.get("ext") or {}
            if not x or not x.get("n"):
                return ""
            return (f" | ext n={x.get('n')} avg={_f(x.get('net_avg_pct'))} pf={x.get('profit_factor')} "
                    f"tr={_f(x.get('train'))} va={_f(x.get('valid'))} ok={x.get('ext_ok')}")

        def _gts(b):   # V.2.42.0 — تک‌پوزیشنی ۹۰ روزه + کنترل ۳۶۵ روزه
            o, lg = b.get("one") or {}, b.get("long") or {}
            s_ = f" | one[{o.get('status')}] n={o.get('n')} avg={_f(o.get('net_avg_pct'))}" if o else ""
            if lg and lg.get("status") not in (None, "off"):
                s_ += (f" | 365d[{lg.get('status')}{'*' if lg.get('carried') else ''}] n={lg.get('n')} avg={_f(lg.get('net_avg_pct'))} "
                       f"h1={_f(lg.get('h1'))} h2={_f(lg.get('h2'))} one={_f(lg.get('one_avg'))}")
            return s_

        def _bt(b):
            if not b:
                return None
            return (f"{'PASS' if b.get('passes') else 'fail'} n={b.get('n')} avg={_f(b.get('net_avg_pct'))} "
                    f"tr={_f(b.get('train'))} va={_f(b.get('valid'))} pf={b.get('profit_factor')} "
                    f"dd={b.get('max_dd_pct')} worst={b.get('worst_trade_pct')}" + _gts(b) + _mcs(b) + _exs(b))

        def _fp(f_):
            f_ = f_ or {}
            return None if not f_.get("n") else f"n={f_.get('n')} avg={_f(f_.get('net_avg_pct'))} wr={f_.get('win_rate')}"
        lv = dict(gh.get("live") or {})
        modes = ((lv.get("last_scan") or {}).get("modes") or {})
        gh["strategies"] = {n: " | ".join(x for x in (v.get("timeframe"), _bt(v.get("backtest_90d")),
                                                       ("paper " + _fp(v.get("forward_paper"))) if _fp(v.get("forward_paper")) else None,
                                                       "mode: " + str(modes.get(n)) if n in modes else None) if x)
                            for n, v in (gh.get("strategies") or {}).items() if isinstance(v, dict)}
        lv.pop("strategies", None)
        _pp = gh.get("paper_portfolios") or {}   # V.2.39.2 — آزمون کاغذی سبد RF-4h-C2 در یک خط
        if isinstance(_pp, dict):
            gh["paper_portfolios"] = {k: (f"{v.get('verdict')} days={v.get('days')} n={v.get('n_final')}+{v.get('n_provisional')}prov "
                                          f"tpd={v.get('trades_per_day')} wr={v.get('win_rate')} pf={v.get('profit_factor')} "
                                          f"avg={_f(v.get('net_avg_pct'))} usd={_f(v.get('net_usd'))} dd$={v.get('max_dd_usd')} "
                                          f"skip={v.get('skipped')} late={v.get('late_n')}"
                                          if isinstance(v, dict) and "n_final" in v else v) for k, v in _pp.items()}
        if isinstance(lv.get("last_scan"), dict):
            lv["last_scan"] = {k: v for k, v in lv["last_scan"].items() if k != "modes"}
        lv["scans_recent"] = [" ".join(str(x) for x in (r.get("slot_utc"), f"ok={r.get('fetch_ok')}",
                                                         f"sig={r.get('signals')}", f"opened={r.get('opened')}" if r.get("opened") else "",
                                                         f"err={r.get('fetch_err')}" if r.get("fetch_err") else "") if x)
                              for r in (lv.get("scans_recent") or [])[-8:] if isinstance(r, dict)]
        lv["paper_since_live"] = {n: (x or [])[-3:] for n, x in (lv.get("paper_since_live") or {}).items() if x}
        lv["state"] = {n: f"{v.get('mode')} live_now={v.get('live_now')} live_n={(v.get('live') or {}).get('n')} "
                          f"avg={_f((v.get('live') or {}).get('avg_pct'))}"
                          + (f" reeval={v.get('reeval_diag')}" if v.get("reeval_diag") else "")
                       for n, v in (lv.get("state") or {}).items() if isinstance(v, dict) and (v.get("live_now") or v.get("reeval_diag") or (
                           (v.get("live") or {}).get("n") and n == v.get("family", n)))}   # V.2.36.1 — آمار خانواده یک بار
        gh["live"] = lv
        out["github_strategies"] = gh
        for k in ("trend_atr_daily", "tsmom_daily", "rs_intraday_50", "rel_strength"):
            x = dict(out.get(k) or {})
            x.pop("rules", None)
            last = dict(x.get("last") or {})
            for lk in ("skipped", "papered"):
                if isinstance(last.get(lk), list):
                    last[lk] = len(last[lk])
            if isinstance(last.get("checks"), list):
                last["checks"] = sorted(last["checks"], key=lambda c: -float(c.get("dist_to_high20_pct") if c.get("dist_to_high20_pct") is not None else -999))[:3]
            for lk in ("candidates", "why"):
                if isinstance(last.get(lk), list):
                    last[lk] = last[lk][:3]
            x["last"] = last
            out[k] = x
        eb = dict(out.get("entry_block_summary") or {})
        eb.pop("independent_strategies", None)
        out["entry_block_summary"] = eb
        out["compact"] = True
    except Exception as e:   # هرگز گزارش را خراب نکند
        out["compact_error"] = str(e)[:120]
    return out


def _gh_spec_of(sid: Any) -> dict | None:
    try:
        import backtest_github as _bg
        return _bg.STRATEGIES.get(str(sid or ""))
    except Exception:
        return None


def _gh_entry_summary(n_open: int, max_open: int, news_active: bool) -> dict:
    """V.2.35.0 — وضعیت ورود همان مسیری که واقعاً معامله می‌کند (GH)، برای فرانت و گزارش."""
    try:
        live = [n for n in GH_LIVE_STRATEGIES if _gh_live_mode(n)[0]]
        order = _gh_rank_order()[:GH_RESERVE_TOP_N]
    except Exception:
        live, order = [], []
    why = ("ورود دستی خاموش" if not ENABLE_NEW_ENTRIES else "سقف ضرر روزانه" if daily_loss_breached()
           else "بلک‌اوت خبر" if news_active else "قفل سراسری SL" if _global_sl_remaining() > 0 else "")
    line = (f"⛔ {why}" if why else f"آزاد · {len(live)} استراتژی زنده · اسلات {n_open}/{max_open}"
            + (f" · برترها: {', '.join(order)}" if order else ""))
    return {"live": live, "top": order, "open": n_open, "max": max_open, "blocked": bool(why), "why": why, "line": line}


async def status_summary() -> dict[str, Any]:
    n_open, rows = await _open_positions_count()
    if rows is None:
        n_open = 0
        rows = []
    bal = await _available_balance()
    try:
        equity = await _equity_balance()
    except Exception:
        equity = bal
    if not equity:
        equity = bal or 0.0
    recent_closed = await _exchange_recent_closed(30)
    try:
        await _btc_drift_state()  # V.2.11.1 — کش ۶۰ث
    except Exception:
        pass
    # V.2.10.101 — دفتر فشرده برای گزارش .md (همان داده‌های /real-trade/ledger)
    try:
        _led = await real_ledger(limit=20)
        _ledger_recent_payload = {
            "count": _led.get("count"),
            "net_pnl_usdt": _led.get("net_pnl_usdt"),
            "fees_usdt": _led.get("fees_usdt"),
            "wins": _led.get("wins"),
            "losses": _led.get("losses"),
            "scratches": _led.get("scratches"),
            "note": _led.get("note"),
            "items": [_ledger_compact(x) for x in (_led.get("items") or [])],
        }
    except Exception as _le:
        _ledger_recent_payload = {"error": str(_le)[:160]}
    # V.2.10.53 — آمار نمادی از پنجرهٔ بزرگ‌تر تاریخچه (فقط مشاهده)
    try:
        _closed_for_sym = await _exchange_recent_closed(40)
        symbol_performance = _build_symbol_performance(_closed_for_sym, min_n=1)
    except Exception:
        symbol_performance = []
    # بازسازی daily_pnl اگر بعد از ری‌استارت صفر شده
    try:
        await _hydrate_daily_pnl_from_exchange()
    except Exception:
        pass
    # یک‌بار SL/TP همهٔ پوزیشن‌های tracked را با صرافی هم‌خوان کن
    for _k, _m in list(_tracked.items()):
        if _m.get("status") == "open":
            try:
                await _sync_levels_from_exchange(_k, _m)
            except Exception:
                pass
    # نقشه قیمت/PnL زنده از پوزیشن‌های صرافی (هر بار status)
    live_by_sym: dict[str, dict[str, Any]] = {}
    for r in (rows or []):
        try:
            sk = _norm_symbol(str(r.get("symbol") or ""))
            if not sk:
                continue
            last = r.get("lastPrice") or r.get("markPrice") or r.get("avgPrice")
            upnl = r.get("unrealizedPnL")
            if upnl is None:
                upnl = r.get("unrealizedPnl")
            live_by_sym[sk] = {
                "last": float(last) if last not in (None, "") else None,
                "upnl": float(upnl) if upnl not in (None, "") else None,
                "margin": r.get("margin"),
                "leverage": r.get("leverage"),
            }
        except Exception:
            continue

    tracked_open = []
    for t in _tracked.values():
        if t.get("status") != "open":
            continue
        sk = _norm_symbol(str(t.get("symbol") or ""))
        live = live_by_sym.get(sk) or {}
        price = live.get("last") if live.get("last") is not None else t.get("current_price")
        # V.2.10.55: progress/PnL روی Fill واقعی
        try:
            entry = float(t.get("fill_entry") if t.get("fill_entry") is not None else t.get("entry") or 0)
        except (TypeError, ValueError):
            entry = float(t.get("entry") or 0)
        direction = t.get("direction") or "long"
        # درصد لحظه‌ای از قیمت زنده
        u_pct = t.get("unrealized_pct")
        if price is not None and entry:
            try:
                u_pct = _unrealized_pct(direction, entry, float(price))
            except Exception:
                pass
        # progress لحظه‌ای
        prog = t.get("progress")
        try:
            sl = float(t.get("stop_loss") or 0)
            tp = float(t.get("target") or 0)
            if price is not None and entry and tp and sl and abs(tp - entry) > 1e-12:
                if direction == "long":
                    prog = (float(price) - entry) / (tp - entry)
                else:
                    prog = (entry - float(price)) / (entry - tp)
        except Exception:
            pass
        _gsp = _gh_spec_of(t.get("strategy_id"))   # V.2.35.0 — سقف نگه‌داری واقعی GH (نه ۲h موتور قدیمی)
        tracked_open.append({
            "symbol": t["symbol"],
            "direction": direction,
            "max_hold_h": _gsp.get("max_hold_h") if _gsp else None,
            "time_stop_at": (float(t.get("opened_at") or 0) + float(_gsp["max_hold_h"]) * 3600) if _gsp and t.get("opened_at") else None,
            "entry": t.get("fill_entry") if t.get("fill_entry") is not None else t["entry"],
            "signal_entry": t.get("signal_entry"),
            "fill_entry": t.get("fill_entry"),
            "entry_slippage_pct": t.get("entry_slippage_pct"),
            "target": t["target"],
            "stop_loss": t["stop_loss"],
            "score": t.get("score"),
            "opened_at": t.get("opened_at"),
            "age_unknown": t.get("age_unknown"),
            "current_price": price,
            "progress": prog,
            "unrealized_pct": u_pct,
            "unrealized_usdt": live.get("upnl"),
            "elapsed_sec": (time.time() - float(t["opened_at"])) if t.get("opened_at") else t.get("elapsed_sec"),
            "profit_locked": t.get("profit_locked"),
            "sl_on_exchange": t.get("sl_on_exchange"),
            "tp_on_exchange": t.get("tp_on_exchange"),
            "status": t.get("status"),
            "margin": live.get("margin"),
            "leverage": live.get("leverage") or LEVERAGE,
            # V.2.10.101 — زمینهٔ معامله برای گزارش
            "strategy_id": t.get("strategy_id"),
            "app_version": t.get("app_version"),
            "breakeven_set": t.get("breakeven_set"),
            "range_low": t.get("range_low"),
            "range_high": t.get("range_high"),
            "time_stop_deadline": t.get("time_stop_deadline"),
            "exit_thresholds": t.get("exit_thresholds"),
            "sl_changes": (t.get("sl_changes") or [])[-4:],
            "price_path_points": len(t.get("price_path") or []),
            "notional_actual": t.get("notional_actual"),
            "risk_usdt_est": t.get("risk_usdt_est"),
            "matrix_cell": t.get("matrix_cell"),        # V.2.18.3
            "matrix_status": t.get("matrix_status"),
            "sl_missing_since": t.get("sl_missing_since"),   # V.2.18.4
            "exit_mode": t.get("exit_mode"),                 # V.2.18.6
            "tpsl_dedupe": t.get("tpsl_dedupe"),             # V.2.18.7
            "mfe_live_pct": t.get("mfe_live_pct"),
            "sl_reattach_n": t.get("sl_reattach_n"),
            "close_limits_released": t.get("close_limits_released"),
        })
    # V.2.10.68 — وضعیت blackout خبر
    _news_status = {"active": False, "enabled": ENABLE_NEWS_BLACKOUT, "reason": ""}
    try:
        from news_blackout import news_blackout_state
        _ns = news_blackout_state()
        _news_status = {
            "active": bool(_ns.get("active")),
            "reason": _ns.get("reason") or "",
            "event": _ns.get("event"),
            "event_title": _ns.get("event_title") or ((_ns.get("event") or {}).get("title") if isinstance(_ns.get("event"), dict) else None),
            "window_start_iso": _ns.get("window_start_iso"),
            "window_end_iso": _ns.get("window_end_iso"),
            "event_time_iso": _ns.get("event_time_iso"),
            "next_event": _ns.get("next_event"),
            "next_window": _ns.get("next_window"),
            "enabled": bool(_ns.get("enabled", True)),
            "source_error": _ns.get("source_error"),
            "minutes_before": NEWS_BLACKOUT_MINUTES_BEFORE,
            "minutes_after": NEWS_BLACKOUT_MINUTES_AFTER,
            "events_loaded": _ns.get("events_loaded"),
            "today_events": _ns.get("today_events") or [],
            "upcoming_events": _ns.get("upcoming_events") or [],
            "source": _ns.get("source"),
        }
    except Exception as _nse:
        _news_status = {"active": False, "enabled": ENABLE_NEWS_BLACKOUT, "reason": "", "error": str(_nse)[:120]}

    # V.2.10.52 — شفافیت pause ورود (مشاهده در status / فرانت / status-viewer)
    try:
        apply_runtime_settings()
    except Exception:
        pass
    _pause = False
    _pause_reason = ""
    if not ENABLE_NEW_ENTRIES:
        _pause = True
        _pause_reason = "ورود دستی از تنظیمات خاموش است (enable_new_entries=false)"
    else:
        _gleft = _global_sl_remaining()
        if _gleft > 0:
            _pause = True
            _pause_reason = f"قفل سراسری پس از چند SL ({_gleft}s باقی)"
        else:
            try:
                _ap, _ap_reason = btc_auto_entry_pause_state(None)
            except Exception:
                _ap, _ap_reason = False, ""
            if _ap:
                _pause = True
                _pause_reason = _ap_reason or "توقف خودکار رژیم BTC"

    return {
        "app_version": APP_VERSION,
        "real_trading_enabled": REAL_TRADING_ENABLED,
        "enable_new_entries": ENABLE_NEW_ENTRIES,
        # V.2.35.0 — pause BTC فقط موتور قدیمی را متوقف می‌کرد؛ GH آن را نمی‌بیند ⇒ وقتی موتور قدیمی خاموش است false
        "auto_entry_pause": _pause if LEGACY_LIVE_ENABLED else False,
        "auto_entry_pause_reason": _pause_reason if LEGACY_LIVE_ENABLED else "",
        "gh_entry": _gh_entry_summary(n_open, _effective_max_positions(float(equity or bal or 0)),
                                      bool((_news_status or {}).get("active"))),
        "watchlist_obs_note": "score≠win_prob; quality/readiness observation-only",
        "clear_global_entry_lock_on_boot": CLEAR_GLOBAL_ENTRY_LOCK_ON_BOOT,
        "news_blackout": _news_status,
        # V.2.10.79 — خلاصهٔ فشرده گیت‌ها برای فرانت (بدون شلوغی)
        "entry_block_summary": _build_entry_block_summary(
            pause=_pause,
            pause_reason=_pause_reason,
            news_active=bool((_news_status or {}).get("active")),
            n_open=n_open,
            max_open=_effective_max_positions(float(equity or bal or 0)),
        ),
        "entry_open_hint": {
            "enable_strong_adx_bypass_btc_pause": ENABLE_STRONG_ADX_BYPASS_BTC_PAUSE,
            "enable_news_blackout": ENABLE_NEWS_BLACKOUT,
            "news_blackout_minutes_before": NEWS_BLACKOUT_MINUTES_BEFORE,
            "news_blackout_minutes_after": NEWS_BLACKOUT_MINUTES_AFTER,
            "adx_strong_bypass_btc": ADX_STRONG_BYPASS_BTC,
            "note": "نماد با ADX≥آستانه از pause مربوط به BTC WEAK مستثنی است؛ لیست لحظه‌ای در فرانت از regime-status",
        },
        "available_usdt": bal,
        "open_positions": n_open,
        "max_open_positions": _effective_max_positions(float(equity or bal or 0)),
        "equity_usdt": equity,
        "sizing_basis": "equity",
        "max_open_positions_cap": MAX_OPEN_POSITIONS,
        "leverage": LEVERAGE,
        "min_confluence": MIN_CONFLUENCE_REAL,
        "daily_pnl": _daily_pnl,
        "daily_loss_limit": DAILY_LOSS_LIMIT_USDT,
        "positions": rows[:10],
        "tracked": tracked_open,
        "manager": {
            "profit_lock_trigger": PROFIT_LOCK_TRIGGER_RATIO,
            "min_profit_pct": MIN_PROFIT_PCT_TO_LOCK,
            "breakeven_trigger_pct": BREAKEVEN_TRIGGER_PCT,
            "max_hold_seconds": MAX_HOLD_SECONDS,
            "interval_seconds": MANAGER_INTERVAL_SECONDS,
            "stale_session_exit": ENABLE_STALE_SESSION_EXIT,
            "stale_profit_min_pct": STALE_PROFIT_MIN_PCT,
            "stale_neutral_min_pct": STALE_NEUTRAL_MIN_PCT,
            "stale_neutral_had_loss_pct": STALE_NEUTRAL_HAD_LOSS_PCT,
            "stale_flat_min_pct": STALE_FLAT_MIN_PCT,
            "stale_flat_max_loss_usdt": STALE_FLAT_MAX_LOSS_USDT,
            "stale_flat_exit_fee_est": STALE_FLAT_EXIT_FEE_EST,
            "max_hold_force_seconds": int(MAX_HOLD_SECONDS * 1.5),
            "regime_soft_exit": ENABLE_REGIME_SOFT_EXIT,
            "regime_adverse_loss_exit": ENABLE_REGIME_ADVERSE_LOSS_EXIT,
            "regime_adverse_loss_pnl_pct": REGIME_ADVERSE_LOSS_PNL_PCT,
            "regime_adverse_loss_min_elapsed_sec": REGIME_ADVERSE_LOSS_MIN_ELAPSED_SEC,
            "regime_exit_flat_min_elapsed": REGIME_EXIT_FLAT_MIN_ELAPSED,
            "regime_exit_flat_min_pnl_pct": REGIME_EXIT_FLAT_MIN_PNL_PCT,
            "min_net_close_pnl_pct": MIN_NET_CLOSE_PNL_PCT,
            "float_profit_exit": ENABLE_FLOAT_PROFIT_EXIT,
            "float_min_profit_usdt": FLOAT_MIN_PROFIT_USDT,
            "float_min_profit_pct": FLOAT_MIN_PROFIT_PCT,
            "float_min_elapsed_sec": FLOAT_MIN_ELAPSED_SEC,
            "float_only_if_slots_full": FLOAT_ONLY_IF_SLOTS_FULL,
            "emergency_loss_exit": ENABLE_EMERGENCY_LOSS_EXIT,
            "max_unrealized_loss_pct": MAX_UNREALIZED_LOSS_PCT,
            "emergency_loss_min_elapsed_sec": EMERGENCY_LOSS_MIN_ELAPSED_SEC,
            "max_seconds_without_exchange_sl": MAX_SECONDS_WITHOUT_EXCHANGE_SL,
            "regime_tighten_sl": ENABLE_REGIME_TIGHTEN_SL,
            "regime_tighten_min_elapsed_sec": REGIME_TIGHTEN_MIN_ELAPSED_SEC,
            "regime_tighten_buffer_pct": REGIME_TIGHTEN_BUFFER_PCT,
            "regime_tighten_only_if_loss": REGIME_TIGHTEN_ONLY_IF_LOSS,
        },
        "entry_filters": {
            "pre_order_slip_band_pct": PRE_ORDER_SLIP_BAND_PCT,
            "entry_protected_ioc": ENTRY_PROTECTED_IOC,
            "paper_track_rr_rejects": PAPER_TRACK_RR_REJECTS,
            "underwater_block_same_dir": UNDERWATER_BLOCK_SAME_DIR,
            "underwater_min_loss_pct": UNDERWATER_MIN_LOSS_PCT,
            "underwater_min_loss_usdt": UNDERWATER_MIN_LOSS_USDT,
            "paper_track_underwater_rejects": PAPER_TRACK_UNDERWATER_REJECTS,
            "range_fail_exit": RANGE_FAIL_EXIT,
            "range_fail_exit_rule": [RANGE_FAIL_EXIT_MIN_SEC, RANGE_FAIL_EXIT_MFE_MAX_PCT, RANGE_FAIL_EXIT_ADVERSE_R],
            "range_profit_lock": RANGE_PROFIT_LOCK,
            "paper_track_slmin_rejects": PAPER_TRACK_SLMIN_REJECTS,
            "paper_track_samedir_cap_rejects": PAPER_TRACK_SAMEDIR_CAP_REJECTS,
            "paper_track_overext_rejects": PAPER_TRACK_OVEREXT_REJECTS,
            "overext_strong_def": {"er_min": OVEREXT_STRONG_ER, "adx_1h_min": OVEREXT_STRONG_ADX},
            "entry_max_slippage_pct": ENTRY_MAX_SLIPPAGE_PCT,
            "range_exit_ignore_regime": RANGE_EXIT_IGNORE_REGIME,
            "min_confluence": MIN_CONFLUENCE_REAL,
            "min_sl_distance_pct": MIN_SL_DISTANCE_PCT,
            "max_sl_distance_pct": MAX_SL_DISTANCE_PCT,
            "enable_er_noise_filter": ENABLE_ER_NOISE_FILTER_REAL,
            "er_noise_max": ER_NOISE_MAX,
            "enable_ci_noise_filter": ENABLE_CI_NOISE_FILTER_REAL,
            "ci_noise_max": CI_NOISE_MAX,
            "enable_trend_quality_gate": ENABLE_TREND_QUALITY_GATE,
            "enable_entry_candle_confirm": ENABLE_ENTRY_CANDLE_CONFIRM,
            "enable_candle_noise_filter": ENABLE_CANDLE_NOISE_FILTER,
            "enable_trend_transition_guard": ENABLE_TREND_TRANSITION_GUARD,
            "anti_noise_fail_closed": ANTI_NOISE_FAIL_CLOSED,
            "enable_adx_bypass_btc_chop": ENABLE_ADX_BYPASS_BTC_CHOP,
            "enable_real_m5_closed_trigger": ENABLE_REAL_M5_CLOSED_TRIGGER,
            "enable_alt_er_strict": ENABLE_ALT_ER_STRICT,
            "alt_er_min": ALT_ER_MIN,
            "enable_min_adx_entry": ENABLE_MIN_ADX_ENTRY,
            "min_adx_1h_for_entry": MIN_ADX_1H_FOR_ENTRY,
            "enable_range_scalp": ENABLE_RANGE_SCALP,
            "range_min_confluence": RANGE_MIN_CONFLUENCE,
            "range_min_rr": RANGE_MIN_RR,
            "range_min_tp_pct": RANGE_MIN_TP_PCT,
            "range_max_sl_distance_pct": RANGE_MAX_SL_DISTANCE_PCT,
            "range_size_mult": RANGE_SIZE_MULT,
            "range_max_open": RANGE_MAX_OPEN_POSITIONS,
            "range_signal_only": RANGE_SIGNAL_ONLY,
            "range_time_stop_sec": RANGE_TIME_STOP_SEC,
            "range_max_loss_usdt": RANGE_MAX_LOSS_USDT,
            "enable_weak_trend": ENABLE_WEAK_TREND,
            "weak_trend_size_mult": WEAK_TREND_SIZE_MULT,
            "weak_trend_min_confluence": WEAK_TREND_MIN_CONFLUENCE,
            "weak_trend_min_adx": WEAK_TREND_MIN_ADX,
            "weak_trend_max_loss_usdt": WEAK_TREND_MAX_LOSS_USDT,
            "min_btc_adx_1h_for_alt": MIN_BTC_ADX_1H_FOR_ALT,
            "adx_strong_bypass_btc": ADX_STRONG_BYPASS_BTC,
            "enable_strong_adx_bypass_btc_pause": ENABLE_STRONG_ADX_BYPASS_BTC_PAUSE,
            "min_rr": MIN_RR_REAL,
            "min_tp_distance_pct": MIN_TP_DISTANCE_PCT,
            "real_min_symbol_wr": REAL_MIN_SYMBOL_WR,
            "live_wr_block_min_n": LIVE_WR_BLOCK_MIN_N,
            "live_wr_block_pct": LIVE_WR_BLOCK_PCT,
            "live_wr_probation_min_n": LIVE_WR_PROBATION_MIN_N,
            "live_wr_probation_pct": LIVE_WR_PROBATION_PCT,
            "live_wr_probation_size_mult": LIVE_WR_PROBATION_SIZE_MULT,
            "symbol_cooldown_sec": SYMBOL_COOLDOWN_SECONDS,
            "post_close_cooldown_sec": POST_CLOSE_COOLDOWN_SECONDS,
            "post_sl_cooldown_sec": POST_SL_COOLDOWN_SECONDS,
            "post_negative_cooldown_sec": POST_NEGATIVE_COOLDOWN_SECONDS,
            "negative_pnl_threshold_usdt": NEGATIVE_PNL_THRESHOLD_USDT,
            "post_profit_cooldown_sec": POST_PROFIT_COOLDOWN_SECONDS,
            "enable_post_profit_hysteresis": ENABLE_POST_PROFIT_HYSTERESIS,
            "post_profit_hyst_window_sec": POST_PROFIT_HYST_WINDOW_SEC,
            "symbol_sl_lock_count": SYMBOL_SL_LOCK_COUNT,
            "symbol_sl_lock_lookback_sec": SYMBOL_SL_LOCK_LOOKBACK_SEC,
            "symbol_sl_lock_sec": SYMBOL_SL_LOCK_SEC,
            "enable_btc_chop_gate": ENABLE_BTC_CHOP_GATE,
            "auto_pause_entries_on_btc_regime": AUTO_PAUSE_ENTRIES_ON_BTC_REGIME,
            "auto_resume_min_btc_conf": AUTO_RESUME_MIN_BTC_CONF,
            "auto_pause_on_btc_bear_stack": AUTO_PAUSE_ON_BTC_BEAR_STACK,
            "btc_chop_block_alts": BTC_CHOP_BLOCK_ALTS,
            "btc_weak_min_conf": BTC_WEAK_MIN_CONF,
            "global_sl_limit": GLOBAL_SL_LIMIT,
            "global_sl_lookback_sec": GLOBAL_SL_LOOKBACK_SEC,
            "global_sl_lock_remaining": _global_sl_remaining(),
            "rolling_low_profit_window_sec": ROLLING_LOW_PROFIT_WINDOW_SEC,
            "min_notional_usdt": MIN_NOTIONAL_USDT,
            "min_margin_usdt": MIN_MARGIN_USDT,
            "max_margin_usdt": MAX_MARGIN_USDT_ABS, "margin_fraction": MARGIN_FRACTION, "max_margin_fraction": MAX_MARGIN_FRACTION,
            "adaptive_min_notional": True,
            "adaptive_max_positions": True,
        },
        "recent_closed": recent_closed,
                "symbol_direction_tiers": _build_symbol_direction_tiers(),
        "symbol_direction_policy": "keep|probation|strict|block بر اساس n/WR/expectancy نماد+جهت",
        "tiers_pnl_unit": "usdt_net (decision_net_pnl preferred; |pnl|>8 skipped)",
        "session_global_lock": "session-only; PERSIST_GLOBAL_ENTRY_LOCK=false",
        "symbol_performance": symbol_performance,
        "symbol_performance_note": (
            "V.2.10.53 · آمار مشاهده‌ای از تا ۴۰ پوزیشن اخیر صرافی · "
            "blacklist خودکار نیست · تصمیم دستی بعد از n≥۵–۸ تمیز همان نسخه"
        ),
        "last_attempts": sorted(
            _last_attempts.values(),
            key=lambda x: float(x.get("ts") or 0),
            reverse=True,
        )[:15],
        # V.2.10.101 — همهٔ تنظیمات صفحهٔ Settings در گزارش
        "runtime_settings": _settings_for_report(),
        # V.2.11.0
        "btc_drift": dict(_BTC_DRIFT_CACHE.get("state") or {}),
        "paper_trades": _paper_summary(),
        "exit_whatif": _whatif_summary(await _memory_context()),
        "range_small_tp": _small_tp_report(),   # V.2.11.9 — گزارش کامل برای تصمیم
        "backtest": _backtest_report(),          # V.2.12.0
        "path_capture_queue": len(_path_capture_queue),
        # V.2.11.3
        "strategy_matrix": _matrix_report(),  # V.2.13.0
        "scan_window": {"window_min": SCAN_WINDOW_SEC // 60, "tsmom_window_h": TSMOM_SCAN_WINDOW_SEC / 3600,
                        "done_slots": dict(_SCAN_SLOTS), "notes": dict(_SCAN_NOTES)},   # V.2.18.5
        "rs_intraday_50": {"enabled": RSI_ENABLED, "last": _RSI_STATE.get("last_result"),
                           "next_scan_utc": time.strftime("%H:%M", time.gmtime((int(time.time() // 14400) + 1) * 14400 + 120)),
                           "rules": {"top_n": RSI_TOP_N, "lookback_h": RSI_LOOKBACK_H, "max_hold_h": RSI_MAX_HOLD_SEC / 3600,
                                     "max_24h_range_pct": RSI_MAX_24H_RANGE_PCT, "universe_n": len(_rsi_universe()),
                                     "directions": "BTC ۱۲h > ۰ ⇒ لانگ قوی‌ترین‌ها؛ < ۰ ⇒ شورت ضعیف‌ترین‌ها (V.2.18.2)",
                                     "gate_mode": {d_: _gate_mode("rs_intraday_50", d_) for d_ in ("long", "short")}}},
        "income": _portfolio_report(),   # V.2.18.1 — روزانه (کوتاه‌مدت) و ماهانه (بلندمدت)
        "forward_test": _fwd_report(),    # V.2.19.0
        "server_time": time.time(),       # V.2.19.0 — برای تشخیص گزارش کهنه
        "server_time_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "tsmom_daily": {"enabled": TSMOM_ENABLED, "last": _TSMOM_STATE.get("last_result"),
                        "rules": {"symbols": _tsmom_symbols(), "ext_passed": _tsmom_ext_on(),
                                  "live_sl_cap_pct": TSMOM_LIVE_SL_CAP_PCT,
                                  "max_hold_days": TSMOM_MAX_HOLD_SEC / 86400, "max_open": _daily_max_open("tsmom_daily")}},
        "github_strategies": _gh_report(),   # V.2.22.0 — فقط کاغذی
        "trend_atr_daily": {"enabled": TREND_ATR_ENABLED, "last": _TATR_STATE.get("last_result"),   # V.2.20.0
                            "passes": bool(_daily_research("trend_atr_daily").get("passes")),
                            "rules": {"symbols": _trend_atr_symbols(), "entry": "بسته شدن > سقف ۲۰ روز + > EMA50 + BTC > EMA50",
                                      "sl": "۲٫۵×ATR (۳٪ تا سقف)", "live_sl_cap_pct": TREND_ATR_SL_CAP_PCT,
                                      "exit": "بسته شدن روزانه < بیشترین بسته شدن − ۲٫۵×ATR، یا ۳۰ روز",
                                      "max_open": TREND_ATR_MAX_OPEN, "direction": "فقط لانگ"}},
        "rel_strength": {"enabled": RS_ENABLED, "last": _RS_STATE.get("last_result"),
                         "next_scan_utc": time.strftime("%H:%M", time.gmtime((int(time.time() // 14400) + 1) * 14400 + 90)),
                         "rules": {"top_n": RS_TOP_N, "min_rs_pct": RS_MIN_RS_PCT, "sl_atr": RS_SL_ATR,
                                   "sl_pct_range": [RS_SL_MIN_PCT, RS_SL_MAX_PCT], "tp_r": RS_TP_R,
                                   "max_hold_h": RS_MAX_HOLD_SEC / 3600,
                                   "gate_mode": _gate_mode("rel_strength", "long")}},
        "maker_tp": {"enabled": TREND_MAKER_TP, "disabled_reason": "V.2.18.4: limit بستن مقدار پوزیشن را قفل می‌کرد ⇒ SL صرافی اجرا نشد",
                     "selftest_enabled": MAKER_TP_SELFTEST,
                     "selftest": {k: v for k, v in _MAKER_SELFTEST.items() if k != "tries"},
                     "selftest_tries": (_MAKER_SELFTEST.get("tries") or [])[:3]},
        "protected_entry": {
            "enabled": ENTRY_PROTECTED_IOC,
            "max_slippage_pct": ENTRY_MAX_SLIPPAGE_PCT,
            "selftest_enabled": ENTRY_PROTECTED_SELFTEST,
            "selftest": dict(_PROTECTED_SELFTEST),
        },
        # V.2.11.2
        "path_capture_log": _path_capture_log[:6],
        "news_impact": _news_impact_summary(),
        "news_impact_by_title": _news_impact_by_title(),  # V.2.11.5 — همهٔ روزها
        "remote_state_load": dict(_REMOTE_STATE_RESULT),   # V.2.11.5 — بازگرداندن کاغذی/خبر بعد از بوت
        "manager_heartbeat": {
            "last_cycle_ago_sec": round(time.time() - float(_MANAGER_HEARTBEAT.get("ts") or 0), 1)
            if _MANAGER_HEARTBEAT.get("ts") else None,
            "cycles_since_boot": _MANAGER_HEARTBEAT.get("cycles"),
        },
        # V.2.10.101 — دفتر فشرده (PnL صرافی + زمینه از حافظه/Supabase)
        "ledger_recent": _ledger_recent_payload,
    }
