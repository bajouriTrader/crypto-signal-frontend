"""
V.2.22.0 — استراتژی‌های متن‌باز گیت‌هاب (مخزن رسمی freqtrade/freqtrade-strategies) با همان قواعد اصلی‌شان،
روی دادهٔ ۹۰ روزهٔ ۲۰ نماد (بک‌تست) + «کاغذی رو به جلو» با همان کد روی کندل‌های تازه.

ترجمهٔ وفادار از کد اصلی (populate_entry/exit + minimal_roi + stoploss + trailing)، با سه تفاوت ایمنی:
  - SL حداکثر SL_CAP_PCT (۱۰٪) — اصلشان تا ۲۶٫۵٪ یا بدون SL است (برای حساب ۴۲$ با ۵× غیرقابل قبول).
  - حداکثر نگه‌داری MAX_HOLD_H (۷ روز).
  - ورود در open کندل بعد از سیگنال (مثل freqtrade)، خروج سیگنالی در open کندل بعد؛ در هر کندل اول SL بعد ROI.
کارمزد/لغزش همان موتور بک‌تست (br._stats).

V.2.24.0 — پاک‌سازی: ردشده‌ها (fadx_sma، freinforced، fsample، fsupertrend، trendfollow، الگوی V ویدیو) حذف شدند؛
۵ نامزد جدید ۱h/۴h اضافه شد (adxmomentum، adxsmas، awesomemacd، hlhb، average).

استراتژی‌های قبلی (تاریخچه؛ فقط volsystem و bbandrsi مانده‌اند):
  gh_fadx_sma       futures/FAdxSmaStrategy.py          1h  L/S  ADX14>30 + کراس SMA12/SMA48؛ خروج ADX<30؛ SL ۵٪
  gh_freinforced    futures/FReinforcedStrategy.py      5m  L/S  کراس EMA8/EMA21 + قیمت سمت SMA50 ساعتی؛ خروج ADX<30
  gh_fsample        futures/FSampleStrategy.py          1h  L/S  RSI کراس ۳۰/۷۰ + TEMA نسبت به میانهٔ BB
  gh_fsupertrend    futures/FSupertrendStrategy.py      1h  L/S  ۳ سوپرترند هم‌جهت؛ خروج سوپرترند دوم؛ تریلینگ
  gh_trendfollow    futures/TrendFollowingStrategy.py   5m  L/S  کراس EMA20 + OBV
  gh_volsystem      futures/VolatilitySystem.py         1h  L/S  تغییر بستهٔ ۳ ساعته > ۲×ATR(۳h)
  gh_bbandrsi       berlinguyinca/BbandRsi.py           1h  L    RSI<30 و زیر باند پایین؛ خروج RSI>70
"""
from __future__ import annotations

import random
import time
import zlib

import backtest_range as br

SL_CAP_PCT = 10.0
MAX_HOLD_H = 7 * 24
H1 = 3_600_000
M5 = 300_000
TF_MS = {"4h": 4 * H1, "1h": H1, "15m": 900_000, "5m": M5}

STRATEGIES: dict[str, dict] = {
    # قبول‌شده در بک‌تست ۹۰ روزه (V.2.22.0) — زنده با حداقل حجم
    "gh_bbandrsi": {"tf": "1h", "src": "berlinguyinca/BbandRsi.py", "sl": 25.0, "roi": {0: 10.0},
                    "trail": None, "short": False},
    # V.2.24.0 — نامزدهای جدید (۱h/۴h، فقط لانگ مثل اصلشان؛ کم‌معامله ⇒ کارمزد کمتر)
    "gh_adxsmas": {"tf": "1h", "src": "berlinguyinca/AdxSmas.py", "sl": 25.0, "roi": {0: 10.0},
                   "trail": None, "short": False},
    "gh_hlhb": {"tf": "4h", "src": "hlhb.py", "sl": 32.11, "roi": {0: 62.25, 703: 21.87, 2849: 3.63, 5520: 0.0},
                "trail": (1.17, 1.86, True), "short": False},
}
# V.2.25.0 — استراتژی‌های طلای پیج vixmarket.fx (فایل کاربر). فقط روی نماد طلا (XAU، وگرنه PAXG/XAUT).
# پیپ طلا = ۰٫۱ دلار ⇒ ۶۰ پیپ = ۶ دلار. هجینگ (قفل پوزیشن) پیاده نشد: در حساب یک‌طرفه پوزیشن مخالف هم‌حجم = بستن.
GOLD_SYMBOLS = ("XAU", "PAXG", "XAUT")
_VIX = "vixmarket.fx (اینستاگرام) — فایل کاربر"
# V.2.25.1 — هر ۶ نسخه در بک‌تست ۹۰ روزهٔ XAU رد شدند (همه منفی در آموزش و اعتبارسنجی) ⇒ حذف:
#   wma_otf_4h −۰٫۲۱٪ (n=۵۸)، wma_otf_4h_atr −۰٫۵۰٪، bbmid_15m −۰٫۱۰٪ (n=۶۴۸)، bbmid_15m_atr −۰٫۱۰٪،
#   macd_ewo_1h −۰٫۱۱٪ (برد ۲۹٪، نه ۹۵٪)، macd_ewo_4h −۰٫۲۱٪. زیرساخت طلا (applies/levels/gold_symbol) می‌ماند.
# V.2.26.0 — نسخه‌های محافظ برای ۴ استراتژی زنده (درخواست کاربر: «اگر روند برگردد با منفی بسته می‌شود»):
#   _btc     : ورود فقط وقتی BTC (۴h) بالای EMA50 است + خروج فوری وقتی BTC زیر EMA50 بسته شود
#   _sl5     : حد ضرر ۵٪ به‌جای ۱۰٪
#   _btc_sl5 : هر دو
# زنده: از هر خانواده فقط «بهترین نسخهٔ قبول‌شده» (بیشترین سود کل ÷ بیشترین افت) — choose_family().
# V.2.30.0 — استراتژی‌های عمومی معروف (TradingView / کتاب): دوطرفه، SL سقف ۱۰٪، خروج با سیگنال خودشان
# V.2.31.0 — پاک‌سازی: ردشده‌ها حذف (RSI-2 ۱h، UT Bot ۱h، Squeeze ۱h، WaveTrend ۱h/۴h، VolSystem، ADXMomentum)
_TV = "https://www.tradingview.com/scripts/"
STRATEGIES.update({
    "pb_rsi2_4h": {"tf": "4h", "src": "Larry Connors RSI-2 (prorealcode / کتاب Short Term Trading Strategies That Work)",
                   "engine": "public", "sl": 100.0, "roi": {0: 100.0}, "trail": None, "short": True},
    # V.2.32.0 — ویدیوهای ۲۱ اکتبر: Range Filter (fxchart.hunter: «RF - B&S Signals»، دورهٔ ۲۳، ضریب ۲٫۵) و
    # فیبوی ۰٫۶۱۸ روی لگ قوی (mehraninvest: «ساختار یک‌ساعته»، ورود در ۰٫۶۲، SL زیر شروع لگ، TP سقف لگ)
    "pb_rangefilter_1h": {"tf": "1h", "src": _TV + " Range Filter Buy and Sell [DonovanWall] (۲۳، ۲٫۵)", "engine": "public",
                          "sl": 100.0, "roi": {0: 100.0}, "trail": None, "short": True},
    "pb_rangefilter_4h": {"tf": "4h", "src": _TV + " Range Filter Buy and Sell [DonovanWall] (۲۳، ۲٫۵)", "engine": "public",
                          "sl": 100.0, "roi": {0: 100.0}, "trail": None, "short": True},
    "pb_fib618_1h": {"tf": "1h", "src": "mehraninvest: پولبک ۰٫۶۱۸ فیبوناچی لگ قوی (SL زیر شروع لگ، TP سقف لگ)",
                     "engine": "public", "sl": 100.0, "roi": {0: 100.0}, "trail": None, "short": True, "lv": "fib"},
    "pb_fib618_4h": {"tf": "4h", "src": "mehraninvest: پولبک ۰٫۶۱۸ فیبوناچی لگ قوی", "engine": "public",
                     "sl": 100.0, "roi": {0: 100.0}, "trail": None, "short": True, "lv": "fib"},
    # V.2.33.1 — Master Candle (nofacetrad، ۴h) در بک‌تست ۹۰ روزه رد و حذف شد: n=105 avg=−۰٫۴۵٪ pf=۰٫۶۵،
    # همهٔ نسخه‌ها (_btc/_sl5/_tr) منفی در اعتبارسنجی.
    # V.2.34.0 — SP2L پورصمدی (۳ ویدیوی یوتیوب: Forex SJ، Topintrade، Kaveh Trader؛ سبک Al Brooks):
    # اسپایک = ≥۳ کندل پشت‌سرهم که هر کدام بالای سقف کندل قبل بسته شده (با گپ/FVG و ≥۲ATR)، اولین پولبک
    # (کف زیر کف کندل قبل، گپ پر نشده) ⇒ ورود برای لگ دوم؛ SL زیر شروع اسپایک، TP = ۱R.
    # V.2.34.1 — بک‌تست ۹۰ روزه: فقط ۱h_btc قبول (n=۸۷ avg=+۰٫۴۷٪ pf=۱٫۶۳). رد و حذف: ۱۵m (n=۱۰۳۰ −۰٫۰۶٪)،
    # «بهینه» sp2lx_15m (n=۱۳۰ +۰٫۰۶٪، va −۰٫۲۸)، sp2lx_1h (n=۲۱ −۰٫۱۴٪)، sp2lt_15m با فیلتر سشن (n=۳۳، va −۰٫۳۷).
    "pb_sp2l_1h": {"tf": "1h", "src": "SP2L پورصمدی (YouTube: Forex SJ / Topintrade / Kaveh Trader)", "engine": "public",
                   "sl": 100.0, "roi": {0: 100.0}, "trail": None, "short": True, "lv": "sp2l"},
    # V.2.35.2 — BTB (PRO BTB، n=۱۸۰ avg=+۰٫۲۵٪ اما اعتبارسنجی −۰٫۶۷٪) و TrendPB (n=۲۷۷ −۰٫۲۲٪) در بک‌تست ۹۰ روزه
    # رد و حذف شدند (همهٔ نسخه‌ها؛ کاغذی هم منفی). قانون قبولی strict برای پایه‌های تازه باقی است.
    # V.2.38.0 — حذف ردشده‌های V.2.37.0 (بک‌تست ۹۰ روزه): pb_bbmr_1h n=125 −۰٫۱۰٪، _tr n=126 +۰٫۰۸٪ pf=۱٫۱۲؛
    # نسخه‌های _bear: rsi2_4h −۰٫۲۳٪، sp2l_1h −۰٫۶۲٪، fib618_4h −۰٫۸۹٪ (و _tr همه منفی). زیرساخت bear می‌ماند.
    "pb_utbot_4h": {"tf": "4h", "src": _TV + " UT Bot Alerts (key=1، ATR10)", "engine": "public",
                    "sl": 100.0, "roi": {0: 100.0}, "trail": None, "short": True},
})
# V.2.38.0 — ۱۰ استراتژی عمومی تازه (درخواست کاربر؛ پیشنهاددهنده/منتقد). همه فقط لانگ، strict، نسخه‌ها فقط _btc/_btc_tr،
# اول فقط کاغذی (GH_PAPER_FIRST در real_trade) تا ≥۱۰ معاملهٔ کاغذی رو به جلو با میانگین مثبت. SL با ATR (سقف ۱۰٪).
_N10 = {"engine": "public", "sl": 10.0, "roi": {0: 100.0}, "trail": None, "short": False, "strict": True,
        "variants": ("_btc", "_btc_tr")}
STRATEGIES.update({
    "pb_ibs_4h": {**_N10, "tf": "4h", "src": "IBS mean reversion (QuantifiedStrategies): c>SMA200 & IBS<0.2, exit c>prev high",
                  "sl_atr": 2.5},
    "pb_double7_4h": {**_N10, "tf": "4h", "src": "Connors Double 7s: c>SMA200 & 7-bar closing low, exit 7-bar closing high",
                      "sl_atr": 2.5},
    "pb_ichimoku_4h": {**_N10, "tf": "4h", "src": "Ichimoku TK cross above green cloud (cloud = span[i−26]), exit c<kijun",
                       "sl_atr": 2.5},
})
# V.2.38.1 — بک‌تست ۹۰ روزه: ۷ پایه رد و حذف (donchian، supertrend: train +۱٫۴/+۱٫۹ ولی valid −۲٫۳/−۱٫۵؛ 3ll، awesomemacd،
# macd200، cci، haema: منفی). ماندند (قبول فقط _btc_tr، اول کاغذی): ibs، double7، ichimoku.
NEW_BASES_V2380 = ("pb_ibs_4h", "pb_double7_4h", "pb_ichimoku_4h")
# V.2.39.1 — pb_bbrsi_15m (پورت BbandRsi به ۱۵m) در بک‌تست ۹۰ روزه رد و حذف شد: n=57 avg=−۰٫۳۳٪ (همهٔ نسخه‌ها منفی).
# قانون قبولی تایم پایین (کارمزد ۰٫۱۸٪) برای هر استراتژی ۱۵m آینده باقی است.
# V.2.41.1 — شورت‌های نزولی V.2.41.0 رد و حذف شدند (۳۶۵ روز ۴h): pb_bdn_4h n=898 avg=−۰٫۴۱٪ pf=۰٫۷۶ (کاغذی n=81 −۲٫۲۵٪)،
# pb_lhfade_4h n=134 avg=−۰٫۹۱٪ pf=۰٫۴۶. این خط بسته شد (بدون تنظیم مجدد). گیت عمومی «bear» (V.2.37.0) باقی است.
LTF_FEE_PCT, LTF_MIN_AVG_AT_FEE = 0.18, 0.15   # ۱۵m: میانگین خالص با کارمزد زندهٔ ۰٫۱۸٪ باید ≥ ۰٫۱۵٪ باشد
STRICT_VALID_N, STRICT_VALID_PF, STRICT_VALID_AVG = 12, 1.1, 0.10   # V.2.38.0 — منتقد: دورهٔ اعتبارسنجی هم باید لبه داشته باشد
PUBLIC_BASES = tuple(n for n, sp in STRATEGIES.items() if sp.get("engine") == "public")
TRAIL_LOCK = (1.0, 1.5, True)
# V.2.34.1 — حداقل لبه برای قبولی (Range Filter ۱h با avg=+۰٫۰۶٪ و pf=۱٫۰۷ قبول و زنده شده بود)
MIN_EDGE_AVG_PCT, MIN_EDGE_PF = 0.15, 1.2   # (فاصلهٔ تریل ٪، شروع از سود ٪، فقط بعد از شروع)
LIVE_BASES = ("gh_adxsmas", "gh_bbandrsi", "gh_hlhb") + PUBLIC_BASES   # V.2.31.1 — Average (رد در ۳ بک‌تست پشت‌سرهم) حذف
VARIANTS = {"_btc": {"btc_filter": True}, "_sl5": {"sl": 5.0}, "_btc_sl5": {"btc_filter": True, "sl": 5.0},
            # V.2.31.3 — قفل سود (درخواست کاربر: OP تا +۰٫۵۵$ رفت و برگشت): از +۱٫۵٪ سود، حد ضرر = بیشترین قیمت − ۱٪
            "_tr": {"trail": TRAIL_LOCK}, "_btc_tr": {"btc_filter": True, "trail": TRAIL_LOCK}}
for _b in LIVE_BASES:
    for _suf in STRATEGIES[_b].get("variants", tuple(VARIANTS)):   # V.2.37.0 — فهرست مجاز هر پایه
        STRATEGIES[_b + _suf] = {**STRATEGIES[_b], **VARIANTS[_suf], "base": _b,
                                 "src": STRATEGIES[_b]["src"]}
# V.2.37.0 — بازار نزولی: نسخهٔ «_bear» = فقط شورت و فقط وقتی BTC (۴h) زیر EMA50 است؛ خروج وقتی BTC بالای آن برگردد.
# خانوادهٔ جدا (شبه‌پایه) ⇒ آمار زنده/تنزل/انتخاب نسخه جدا از سمت لانگ. فقط پایه‌هایی که منطق شورت قرینه دارند.
BEAR_SOURCES: tuple = ()   # V.2.38.0 — هر ۶ نسخهٔ bear رد شدند ⇒ خالی
BEAR_BASES = tuple(b + "_bear" for b in BEAR_SOURCES)
for _b in BEAR_SOURCES:
    _nb = _b + "_bear"
    STRATEGIES[_nb] = {**STRATEGIES[_b], "bear": True, "strict": True, "variants": ("_tr",),
                       "src": STRATEGIES[_b]["src"] + " — bear-only shorts (BTC 4h < EMA50)"}
    STRATEGIES[_nb + "_tr"] = {**STRATEGIES[_nb], "trail": TRAIL_LOCK, "base": _nb}
LIVE_BASES = LIVE_BASES + BEAR_BASES
# V.2.31.0 — نگه‌داری کوتاه‌تر (درخواست کاربر: پوزیشن ۱۶ ساعته جای استراتژی‌های سودده را می‌گیرد):
# ۱h ⇒ حداکثر ۱۲ ساعت، ۴h ⇒ حداکثر ۲۴ ساعت. بک‌تست با همین قانون اجرا می‌شود (قبولی دوباره سنجیده می‌شود).
MAX_HOLD_BY_TF = {"15m": 6, "1h": 12, "4h": 24}
for _n, _sp in STRATEGIES.items():
    _sp.setdefault("max_hold_h", MAX_HOLD_BY_TF.get(_sp["tf"], MAX_HOLD_H))
BTC_EMA = 50


# V.2.38.2 — پیشنهاددهنده/منتقد: «قوی‌ترها اسلات بگیرند، سود پس داده نشود»
VALID_MIN_N_FOR_SCORE = 12          # میانگین امتیاز = min(کل، اعتبارسنجی) وقتی اعتبارسنجی n ≥ ۱۲ (افت لبه جریمه شود)
FWD_SHRINK_K, FWD_SHRINK_MIN_N = 50, 10   # ترکیب میانگین بک‌تست با کاغذی رو به جلو (فقط رتبهٔ زنده)
MC_MULT = {"ok": 1.0, "insufficient": 0.8, "error": 0.8, "warn": 0.6, "high": 0.0}
FWD_VETO_N, FWD_VETO_AVG = 20, 0.0            # کاغذی n ≥ ۲۰ و میانگین ≤ ۰ ⇒ زنده نه
FWD_VETO_FAST_N, FWD_VETO_FAST_AVG = 10, -0.5  # یا n ≥ ۱۰ و میانگین ≤ −۰٫۵
FWD_UNVETO_N, FWD_UNVETO_AVG = 20, 0.10        # برداشتن وتو: از زمان وتو n ≥ ۲۰ و میانگین ≥ +۰٫۱۰ (هیسترزیس)
MC_HIGH_OVERRIDE_N, MC_HIGH_OVERRIDE_AVG = 20, 0.15   # mc[high] فقط با کاغذی قوی زنده می‌شود
FWD_VETO: set = set()   # نام‌های وتوشده (real_trade پر می‌کند؛ choose_family همه‌جا همان را می‌خواند)


def _score_avg(r: dict) -> float:
    a = float(((r.get("all") or {}).get("net_avg_pct") or 0))
    v = r.get("valid") or {}
    if int(v.get("n") or 0) >= VALID_MIN_N_FOR_SCORE and v.get("net_avg_pct") is not None:
        a = min(a, float(v["net_avg_pct"]))
    return a


def score_of(r: dict | None, fwd: dict | None = None, mc_on: bool = False) -> float | None:
    """امتیاز رتبه‌بندی (همان معیار انتخاب خانواده): سود کل ÷ بیشترین افت.
    V.2.38.2 — میانگین = min(کل، اعتبارسنجی)؛ زنده: + ترکیب با کاغذی رو به جلو (fwd) و ضریب مونت‌کارلو (mc_on)."""
    if not r or not r.get("passes"):
        return None
    a = _score_avg(r)
    fn = int((fwd or {}).get("n") or 0)
    if fwd and fn >= FWD_SHRINK_MIN_N and fwd.get("net_avg_pct") is not None:
        a = (a * FWD_SHRINK_K + float(fwd["net_avg_pct"]) * fn) / (FWD_SHRINK_K + fn)
    sc = a * float((r.get("all") or {}).get("n") or 0) / max(1.0, float(r.get("max_dd_pct") or 0))
    if mc_on:
        sc *= MC_MULT.get(str((r.get("mc") or {}).get("flag") or "insufficient"), 0.8)
    return sc


def rank_live(research: dict | None, candidates, fwd_fn=None) -> list:
    """استراتژی‌های زنده به ترتیب امتیاز (بیشترین اول). fwd_fn(name) ⇒ آمار کاغذی (فقط زنده)."""
    st = ((research or {}).get("strategies") or {})
    sc = [(score_of(st.get(n), fwd_fn(n) if fwd_fn else None, mc_on=fwd_fn is not None), n) for n in candidates]
    return [n for s_, n in sorted((x for x in sc if x[0] is not None and x[0] > 0), key=lambda x: -x[0])]


def base_of(name: str) -> str:
    return STRATEGIES.get(name, {}).get("base") or name


def family(base: str) -> list:
    return [base] + [base + s_ for s_ in STRATEGIES.get(base, {}).get("variants", tuple(VARIANTS))]


def btc_regime(btc4h: list) -> tuple[list, list, list]:
    """(زمان بسته شدن هر کندل ۴h بیت‌کوین، بالای EMA50؟، زیر EMA50؟) — V.2.37.0: «زیر» جدا (بدون EMA ⇒ هیچ‌کدام)"""
    rows = br._norm_rows(btc4h or [])
    e = ema([r[4] for r in rows], BTC_EMA)
    return ([r[0] + 4 * H1 for r in rows], [bool(e[i] is not None and rows[i][4] > e[i]) for i in range(len(rows))],
            [bool(e[i] is not None and rows[i][4] < e[i]) for i in range(len(rows))])


def btc_down_at(reg, t_ms: float) -> bool:
    """V.2.37.0 — BTC در آخرین کندل ۴h بسته‌شده تا t_ms زیر EMA50 است (بدون داده/EMA ⇒ False = شورت نه)."""
    if not reg or not reg[0] or len(reg) < 3:
        return False
    import bisect
    k = bisect.bisect_right(reg[0], t_ms) - 1
    return bool(k >= 0 and reg[2][k])


def btc_up_at(reg, t_ms: float) -> bool:
    """وضعیت BTC در آخرین کندل ۴h که تا t_ms بسته شده است (بدون داده ⇒ False = ورود نه)."""
    if not reg or not reg[0]:
        return False
    import bisect
    k = bisect.bisect_right(reg[0], t_ms) - 1
    return bool(k >= 0 and reg[1][k])


def mc_high_blocked(name: str, r: dict | None) -> bool:
    """V.2.38.2 — مونت‌کارلوی high ⇒ زنده نه، مگر کاغذی رو به جلو n ≥ ۲۰ و میانگین ≥ +۰٫۱۵."""
    if str(((r or {}).get("mc") or {}).get("flag") or "") != "high":
        return False
    f = fwd_stats(name)
    return not (int(f.get("n") or 0) >= MC_HIGH_OVERRIDE_N and float(f.get("net_avg_pct") or -1) >= MC_HIGH_OVERRIDE_AVG)


def choose_family(base: str, research: dict | None, gate: bool = True) -> str | None:
    """بهترین نسخهٔ قبول‌شده (score_of)؛ V.2.38.2 — وتوی کاغذی و mc[high] رد می‌شوند ⇒ نسخهٔ بعدی؛ هیچ‌کدام ⇒ None.
    V.2.42.0 — gate=True: نسخه‌ای که کنترل تک‌پوزیشنی/۳۶۵ روزه را رد شده انتخاب نمی‌شود (مدیریت پوزیشن باز: gate=False)."""
    st = ((research or {}).get("strategies") or {})
    best, score = None, None
    for n in family(base):
        r = st.get(n) or {}
        if not r.get("passes") or n in FWD_VETO or mc_high_blocked(n, r):
            continue
        if gate and gate_block(r, (research or {}).get("gate_v")):
            continue
        sc = score_of(r)
        if sc is not None and (score is None or sc > score):
            best, score = n, sc
    return best


GOLD_STRATEGIES = tuple(n for n, sp in STRATEGIES.items() if sp.get("gold"))


def applies(name: str, sym: str) -> bool:
    """استراتژی طلا فقط روی طلا؛ بقیه هرگز روی طلا."""
    g = str(sym).upper() in GOLD_SYMBOLS
    return g == bool(STRATEGIES[name].get("gold"))


def uses_levels(spec: dict) -> bool:
    """V.2.38.0 — SL/TP هر معامله از levels() می‌آید؟ (یک تعریف برای بک‌تست و زنده؛ قبلاً زنده sl_atr را نادیده می‌گرفت)"""
    return bool(spec.get("sl_usd") or spec.get("tp_usd") or spec.get("sl_atr") or spec.get("tp_atr")
                or spec.get("lv") or spec.get("gold"))


def levels(name: str, rows: list, i: int, entry: float, atr: list | None = None) -> tuple[float, float | None]:
    """(sl_pct, tp_pct یا None) برای ورود روی سیگنال کندل i — همین تابع در بک‌تست و زنده."""
    spec = STRATEGIES[name]
    sl_pct, tp_pct = min(SL_CAP_PCT, float(spec["sl"])), None
    if entry <= 0:
        return sl_pct, tp_pct
    if spec.get("sl_usd"):
        sl_pct = spec["sl_usd"] / entry * 100
    if spec.get("tp_usd"):
        tp_pct = spec["tp_usd"] / entry * 100
    if spec.get("lv") == "fib":   # V.2.32.0 — SL زیر شروع لگ (−۰٫۱ATR)، TP = سقف لگ
        fs = fib_setup(rows, i, atr)
        if fs:
            d_, lo_, hi_, a_ = fs
            if d_ == "long":
                sl_pct, tp_pct = (entry - (lo_ - 0.1 * a_)) / entry * 100, (hi_ - entry) / entry * 100
            else:
                sl_pct, tp_pct = ((hi_ + 0.1 * a_) - entry) / entry * 100, (entry - lo_) / entry * 100
            if tp_pct <= 0:
                tp_pct = None
        else:
            return None, None   # V.2.35.0 — setup در قیمت ورود معتبر نیست ⇒ معامله نکن (قبلاً SL پیش‌فرض ۱۰٪)
        if sl_pct <= 0:
            return None, None
        return min(SL_CAP_PCT, sl_pct), tp_pct
    if spec.get("lv") == "sp2l":  # V.2.34.0 — SL زیر/بالای شروع اسپایک (±۰٫۱ATR)، TP = ۱R
        ss = sp2l_setup(rows, i, atr)
        if ss:
            d_, ext, _a = ss
            sl_pct = ((entry - (ext - 0.1 * _a)) if d_ == "long" else ((ext + 0.1 * _a) - entry)) / entry * 100
            tp_pct = sl_pct if sl_pct > 0 else None
        if not ss or sl_pct <= 0:
            return None, None   # V.2.35.0
        return min(SL_CAP_PCT, sl_pct), tp_pct
    if spec.get("sl_atr") or spec.get("tp_atr"):
        a = (atr if atr is not None else atr_w(rows, 14))[i]
        if a:
            if spec.get("sl_atr"):
                sl_pct = spec["sl_atr"] * a / entry * 100
            if spec.get("tp_atr"):
                tp_pct = spec["tp_atr"] * a / entry * 100
    return min(SL_CAP_PCT, sl_pct), tp_pct


def fib_setup(rows: list, i: int, atr: list | None = None, look: int = 40):
    """لگ قوی (≥۴ATR در ≤۱۵ کندل) و اولین برگشت به ۰٫۶۱۸ با بسته شدن پشت ۰٫۷۰۵ — خرید در لگ صعودی، فروش قرینه.
    خروجی: (dir, low_leg, high_leg, atr) یا None."""
    a = (atr if atr is not None else atr_w(rows, 14))
    if i < look + 2 or a[i] is None:
        return None
    w = range(i - look, i)
    gh = max(w, key=lambda k: rows[k][2])
    gl = min(w, key=lambda k: rows[k][3])
    r = rows[i]
    if gh > gl:   # آخرین اکسترمم سقف ⇒ لگ صعودی
        jh = gh
        jl = min(range(max(0, jh - 15), jh), key=lambda k: rows[k][3])
        H, L = rows[jh][2], rows[jl][3]
        rng = H - L
        if rng <= 0 or rng < 4 * a[i] or i - jh < 2:
            return None
        f618, f705 = H - 0.618 * rng, H - 0.705 * rng
        if min(x[3] for x in rows[jh + 1:i]) > f618 and r[3] <= f618 and r[4] > f705 and \
                min(x[3] for x in rows[jh:i + 1]) > L:
            return "long", L, H, a[i]
    else:         # لگ نزولی
        jl = gl
        jh = max(range(max(0, jl - 15), jl), key=lambda k: rows[k][2])
        H, L = rows[jh][2], rows[jl][3]
        rng = H - L
        if rng <= 0 or rng < 4 * a[i] or i - jl < 2:
            return None
        f618, f705 = L + 0.618 * rng, L + 0.705 * rng
        if max(x[2] for x in rows[jl + 1:i]) < f618 and r[2] >= f618 and r[4] < f705 and \
                max(x[2] for x in rows[jl:i + 1]) < H:
            return "short", L, H, a[i]
    return None


def sp2l_setup(rows: list, i: int, atr: list | None = None, nmin: int = 3, nmax: int = 12):
    """SP2L: کندل‌های i-n..i-1 (n≥۳) هر کدام بالای سقف کندل قبل بسته شده‌اند (اسپایک بدون پولبک)، حداقل یک گپ
    (کف کندل k > سقف کندل k-2) و طول اسپایک ≥ ۲ATR؛ کندل i اولین پولبک است (کفش زیر کف کندل قبل) ولی گپ را
    کامل پر نکرده. خروجی: (dir, شروع اسپایک (کف/سقف کندل قبل از اسپایک), atr) یا None. شورت قرینه."""
    a = (atr if atr is not None else atr_w(rows, 14))
    if i < nmax + 16 or a[i] is None:
        return None
    r = rows[i]
    for d_ in ("long", "short"):
        up = d_ == "long"
        def brk(k):
            return rows[k][4] > rows[k - 1][2] if up else rows[k][4] < rows[k - 1][3]
        if brk(i) or not brk(i - 1):
            continue
        n = 0
        while n < nmax and brk(i - 1 - n):
            n += 1
        if n < nmin:
            continue
        s0 = i - n                       # اولین کندل اسپایک
        pre = s0 - 1
        start = rows[pre][3] if up else rows[pre][2]
        top = rows[i - 1][2] if up else rows[i - 1][3]
        if abs(top - start) < 2 * a[i]:
            continue
        if up:
            gaps = [rows[k - 2][2] for k in range(s0 + 1, i) if rows[k][3] > rows[k - 2][2]]
            if gaps and r[3] < rows[i - 1][3] and r[3] > min(gaps):
                return "long", start, a[i]
        else:
            gaps = [rows[k - 2][3] for k in range(s0 + 1, i) if rows[k][2] < rows[k - 2][3]]
            if gaps and r[2] > rows[i - 1][2] and r[2] < max(gaps):
                return "short", start, a[i]
    return None


# ── V.2.36.0 — Monte Carlo و walk-forward (اسکیل backtesting-frameworks + مناظرهٔ پیشنهاددهنده/منتقد) ─────────────
# فقط گزارش (passes تغییر نمی‌کند). منتقد: بک‌تست معاملات هم‌زمانِ ~۲۰ نماد را جمع می‌زند ولی زنده حداکثر ۲ پوزیشن
# دارد ⇒ اول فهرست معاملات به ۲ پوزیشن هم‌زمان محدود می‌شود، بعد دلار (notional ۲۵$) و بوت‌استرپ بلوکی.
MC_VERSION = 1
MC_RUNS, MC_K, MC_NOTIONAL, MC_EQUITY = 2000, 2, 25.0, 40.0
MC_WARN = {"dd95_pct_eq": 25.0, "ret5_pct_eq": -15.0, "p_loss": 0.30}   # هشدار
MC_HIGH = {"dd95_pct_eq": 35.0, "p_loss": 0.45}                          # سطح وتوی آینده (فعلاً فقط برچسب)


def _cap_concurrency(trades: list, k: int = MC_K) -> list:
    """همان چیزی که زنده می‌تواند بگیرد: به ترتیب (ورود، نماد)، وقتی k پوزیشن باز است ورود جدید رد می‌شود."""
    out, open_ = [], []
    for x in sorted(trades, key=lambda x: (x["t"], x["symbol"])):
        open_ = [e for e in open_ if e > x["t"]]
        if len(open_) >= k:
            continue
        open_.append(x.get("exit_t") or x["t"])
        out.append(x)
    return out


# V.2.42.0 — دو کنترل اعتبار بک‌تست (پیشنهاددهنده/منتقد؛ تحقیق ۳۸۵ روزه 2026-11-11): (۱) بک‌تست همهٔ سیگنال‌های هم‌زمان را
# می‌شمرد ولی زنده از هر استراتژی یک پوزیشن می‌گیرد (bbandrsi_tr: ۹۰ روز همه +۰٫۳۴٪، تک‌پوزیشنی +۰٫۰۸٪)؛ (۲) پنجرهٔ ۹۰ روزه
# استراتژی‌ای را قبول می‌کرد که در ۳۶۵ روز زیان‌ده بود (−۰٫۱۵٪). passes دست نمی‌خورد؛ این دو فقط «زنده شدن» را می‌بندند.
GATE_V = 1
GATE_FEE_RT = 0.18            # کارمزد زنده (مثل LTF_FEE_PCT / PP_FEE_RT) + لغزش حد ضرر از br._net
ONE_MIN_N = 20                # تک‌پوزیشنی با n کمتر ⇒ «na» (مسدود نمی‌کند؛ کنترل ۳۶۵ روزه پوشش می‌دهد)
LONG_DAYS, LONG_WARM_DAYS = 365, 35
LONG_MIN_DAYS, LONG_MIN_N, LONG_CARRY_DAYS = 300, 60, 14


def one_slot(trades: list, order: dict | None = None) -> list:
    """همان چیزی که یک اسلات زنده می‌گیرد: به ترتیب (ورود، ترتیب واچ‌لیست)، ورود فقط وقتی اسلات قبلی آزاد شده."""
    order = order or {}
    out, free = [], float("-inf")
    for x in sorted(trades, key=lambda x: (x["t"], order.get(x["symbol"], 999), x["symbol"])):
        if x["t"] >= free:
            out.append(x)
            free = _pp_close_t(x)
    return out


def _gate_stats(tr: list, p: dict) -> dict:
    return br._stats(tr, dict(p, fee_main=GATE_FEE_RT))


def gate_block(r: dict | None, gate_v) -> str | None:
    """دلیل فارسیِ «زنده نه» از کنترل‌های V.2.42.0، یا None. gate_v خالی (بک‌تست قدیمی/بازیابی‌شده) ⇒ اعمال نمی‌شود."""
    if not gate_v or not r:
        return None
    o, lg = r.get("one") or {}, r.get("long") or {}
    if o.get("status") == "fail":
        return f"تک‌پوزیشنی ۹۰ روزه منفی (n={o.get('n')}، میانگین {float(o.get('net_avg_pct') or 0):+.2f}٪ با کارمزد ۰٫۱۸) ⇒ کاغذی"
    st = lg.get("status")
    if st == "fail":
        return f"۳۶۵ روزه منفی (n={lg.get('n')}، میانگین {float(lg.get('net_avg_pct') or 0):+.2f}٪) ⇒ کاغذی"
    if st == "thin":
        return f"نمونهٔ ۳۶۵ روزه کم (n={lg.get('n')}) ⇒ کاغذی"
    if st == "unavailable":
        return "دادهٔ ۳۶۵ روزه در دسترس نیست ⇒ کاغذی"
    return None


def long_eval(name: str, spec: dict, long_data: dict, reg_long, p: dict, order: dict, ext: set) -> dict:
    """کنترل ۳۶۵ روزه (فقط برای قبول‌شده‌های ۹۰ روزه): همهٔ سیگنال‌ها روی واچ‌لیست اصلی، خالص با کارمزد ۰٫۱۸٪."""
    syms = [s for s in (long_data or {}) if s not in ext and applies(name, s)]
    frames = {s: frames_for(long_data[s], spec["tf"]) for s in syms}
    frames = {s: r for s, r in frames.items() if len(r) >= 120}
    if not syms or "BTC" not in (long_data or {}) or not frames:
        return {"status": "unavailable", "ts": time.time(), "n": 0}
    end = max(r[-1][0] for r in frames.values())
    okc = [s for s, r in frames.items() if (r[-1][0] - r[0][0]) / 86_400_000 >= LONG_MIN_DAYS]
    days = round(max((r[-1][0] - r[0][0]) / 86_400_000 for r in frames.values()), 1)
    if len(okc) < 0.75 * len(syms):
        return {"status": "unavailable", "ts": time.time(), "n": 0, "days": days, "covered": f"{len(okc)}/{len(syms)}"}
    t_from = end - LONG_DAYS * 86_400_000
    trades = []
    for s in okc:
        trades += simulate(name, s, frames[s], t_from=t_from, btc=reg_long)
    a = _gate_stats(trades, p)
    n, avg = a.get("n") or 0, a.get("net_avg_pct")
    mid = t_from + (end - t_from) / 2
    h1, h2 = _gate_stats([x for x in trades if x["t"] < mid], p), _gate_stats([x for x in trades if x["t"] >= mid], p)
    one = _gate_stats(one_slot(trades, order), p)
    return {"status": "thin" if n < LONG_MIN_N else ("fail" if (avg is None or avg <= 0) else "ok"), "ts": time.time(),
            "days": days, "n": n, "net_avg_pct": avg, "profit_factor": a.get("profit_factor"),
            "h1": h1.get("net_avg_pct"), "h2": h2.get("net_avg_pct"), "one_n": one.get("n"), "one_avg": one.get("net_avg_pct")}


def _pct(v: list, q: float) -> float:
    v = sorted(v)
    if not v:
        return 0.0
    i = (len(v) - 1) * q / 100
    lo = int(i)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def _mc_bootstrap(r: list, m: int, seed: int, runs: int = MC_RUNS) -> dict:
    """بوت‌استرپ بلوکی دایره‌ای روی سود/زیان دلاری هر معامله (ترتیب زمانی) — RNG پایتون خالص برای تکرارپذیری."""
    n = len(r)
    L = min(5, max(2, m // 4))
    rng = random.Random(seed)
    dds, tots = [], []
    for _ in range(runs):
        c = pk = dd = 0.0
        k = 0
        while k < m:
            st = rng.randrange(n)
            for q in range(L):
                if k >= m:
                    break
                c += r[(st + q) % n]
                pk = max(pk, c)
                dd = max(dd, pk - c)
                k += 1
        dds.append(dd)
        tots.append(c)
    return {"m": m, "L": L, "dd95_usd": round(_pct(dds, 95), 3), "ret5_usd": round(_pct(tots, 5), 3),
            "p_loss": round(sum(1 for t in tots if t < 0) / runs, 4), "dd50_usd": round(_pct(dds, 50), 3)}


def mc_report(name: str, trades: list, p: dict, span_days: float) -> tuple[dict, dict, list]:
    """(capped، mc، wf) — فقط گزارش."""
    cap = _cap_concurrency(trades)
    r = [round(br._net(x, p["fee_main"], p) * MC_NOTIONAL / 100, 4) for x in cap]
    eq = pk = dd = 0.0
    for v in r:
        eq += v
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    tpd = len(cap) / span_days if span_days > 0 else 0.0
    capped = {"n": len(cap), "trades_per_day": round(tpd, 3), "net_total_usd": round(sum(r), 3), "max_dd_usd": round(dd, 3),
              "notional_usd": MC_NOTIONAL, "k": MC_K}
    m = int(round(tpd * 30))
    if len(cap) < 30 or m < 4:
        mc = {"flag": "insufficient", "m": m, "version": MC_VERSION}
    else:
        seed = zlib.crc32(f"{name}|{len(r)}|{round(sum(r), 4)}".encode())
        mc = _mc_bootstrap(r, m, seed)
        mc["dd95_pct_eq"] = round(mc["dd95_usd"] / MC_EQUITY * 100, 2)
        mc["ret5_pct_eq"] = round(mc["ret5_usd"] / MC_EQUITY * 100, 2)
        high = mc["dd95_pct_eq"] > MC_HIGH["dd95_pct_eq"] or mc["p_loss"] > MC_HIGH["p_loss"]
        warn = (mc["dd95_pct_eq"] > MC_WARN["dd95_pct_eq"] or mc["ret5_pct_eq"] < MC_WARN["ret5_pct_eq"]
                or mc["p_loss"] > MC_WARN["p_loss"])
        mc.update(flag="high" if high else ("warn" if warn else "ok"), version=MC_VERSION, equity_ref=MC_EQUITY)
    wf = []
    if cap:
        t0 = min(x["t"] for x in trades)
        for x, v in zip(cap, r):
            w = int((x["t"] - t0) // (30 * 86_400_000))
            while len(wf) <= w:
                wf.append({"n": 0, "usd": 0.0})
            wf[w]["n"] += 1
            wf[w]["usd"] = round(wf[w]["usd"] + v, 3)
    return capped, mc, wf


REPO = "https://github.com/freqtrade/freqtrade-strategies"


# ── اندیکاتورها (لیست ساده؛ None تا گرم شدن) ─────────────────────────────
def sma(v: list, n: int) -> list:
    out, s = [], 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n:
            s -= v[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def ema(v: list, n: int) -> list:
    out, e, k = [], None, 2.0 / (n + 1)
    for i, x in enumerate(v):
        if x is None:
            out.append(None)
            continue
        e = x if e is None else (x - e) * k + e
        out.append(e if i >= n - 1 else None)
    return out


def _ema_opt(v: list, n: int) -> list:
    """EMA روی سری‌ای که اولش None دارد."""
    out, e, k, c = [], None, 2.0 / (n + 1), 0
    for x in v:
        if x is None:
            out.append(None)
            continue
        e = x if e is None else (x - e) * k + e
        c += 1
        out.append(e if c >= n else None)
    return out


def rsi(c: list, n: int = 14) -> list:
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = l_ = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        g += max(d, 0)
        l_ += max(-d, 0)
    g, l_ = g / n, l_ / n
    out[n] = 100.0 if l_ == 0 else 100 - 100 / (1 + g / l_)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l_ = (l_ * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if l_ == 0 else 100 - 100 / (1 + g / l_)
    return out


def atr_w(rows: list, n: int = 14) -> list:
    out, a = [None] * len(rows), None
    for i in range(1, len(rows)):
        h, l, pc = rows[i][2], rows[i][3], rows[i - 1][4]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        if i < n:
            a = (a or 0) + tr
            continue
        a = (a + tr) / n if i == n else (a * (n - 1) + tr) / n
        out[i] = a
    return out


def adx(rows: list, n: int = 14) -> list:
    m = len(rows)
    out = [None] * m
    if m < 2 * n + 1:
        return out
    tr_s = pdm_s = ndm_s = 0.0
    dxs = []
    for i in range(1, m):
        h, l, ph, pl, pc = rows[i][2], rows[i][3], rows[i - 1][2], rows[i - 1][3], rows[i - 1][4]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        up, dn = h - ph, pl - l
        pdm = up if (up > dn and up > 0) else 0.0
        ndm = dn if (dn > up and dn > 0) else 0.0
        if i <= n:
            tr_s += tr
            pdm_s += pdm
            ndm_s += ndm
            if i < n:
                continue
        else:
            tr_s = tr_s - tr_s / n + tr
            pdm_s = pdm_s - pdm_s / n + pdm
            ndm_s = ndm_s - ndm_s / n + ndm
        pdi = 100 * pdm_s / tr_s if tr_s else 0.0
        ndi = 100 * ndm_s / tr_s if tr_s else 0.0
        dx = 100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) else 0.0
        dxs.append(dx)
        if len(dxs) == n:
            out[i] = sum(dxs) / n
        elif len(dxs) > n:
            out[i] = (out[i - 1] * (n - 1) + dx) / n
    return out


def bbands(v: list, n: int = 20, k: float = 2.0) -> tuple[list, list, list]:
    lo, mid, up = [None] * len(v), [None] * len(v), [None] * len(v)
    for i in range(n - 1, len(v)):
        w = v[i - n + 1:i + 1]
        m = sum(w) / n
        sd = (sum((x - m) ** 2 for x in w) / n) ** 0.5
        lo[i], mid[i], up[i] = m - k * sd, m, m + k * sd
    return lo, mid, up


def sma_opt(v: list, n: int) -> list:
    out = []
    for i in range(len(v)):
        w = v[i - n + 1:i + 1] if i >= n - 1 else []
        out.append(sum(w) / n if len(w) == n and None not in w else None)
    return out


def di(rows: list, n: int) -> tuple[list, list]:
    """+DI / −DI وایلدر با دورهٔ n (همان ta.PLUS_DI / MINUS_DI)."""
    m = len(rows)
    pdi, ndi = [None] * m, [None] * m
    tr_s = p_s = n_s = 0.0
    for i in range(1, m):
        h, l, ph, pl, pc = rows[i][2], rows[i][3], rows[i - 1][2], rows[i - 1][3], rows[i - 1][4]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        up, dn = h - ph, pl - l
        pdm = up if (up > dn and up > 0) else 0.0
        ndm = dn if (dn > up and dn > 0) else 0.0
        if i <= n:
            tr_s += tr
            p_s += pdm
            n_s += ndm
            if i < n:
                continue
        else:
            tr_s = tr_s - tr_s / n + tr
            p_s = p_s - p_s / n + pdm
            n_s = n_s - n_s / n + ndm
        pdi[i] = 100 * p_s / tr_s if tr_s else 0.0
        ndi[i] = 100 * n_s / tr_s if tr_s else 0.0
    return pdi, ndi


def macd_line(c: list, f: int = 12, s_: int = 26) -> list:
    a, b = ema(c, f), ema(c, s_)
    return [x - y if None not in (x, y) else None for x, y in zip(a, b)]


def wma(v: list, n: int) -> list:
    w = n * (n + 1) / 2
    return [sum(v[i - n + 1 + k] * (k + 1) for k in range(n)) / w if i >= n - 1 else None for i in range(len(v))]


def otf(rows: list) -> list:
    """Optimal Tracking Filter (Ehlers): آلفا از نسبت حرکت هموار به دامنهٔ هموار."""
    out, v1, v2, v3 = [], 0.0, 0.0, None
    for i, r in enumerate(rows):
        p = (r[2] + r[3]) / 2
        pp = (rows[i - 1][2] + rows[i - 1][3]) / 2 if i else p
        v1 = 0.2 * (p - pp) + 0.8 * v1
        v2 = 0.1 * (r[2] - r[3]) + 0.8 * v2
        lam = abs(v1 / v2) if v2 else 0.0
        al = (-lam ** 2 + (lam ** 4 + 16 * lam ** 2) ** 0.5) / 8 if lam else 0.0
        v3 = p if v3 is None else al * p + (1 - al) * v3
        out.append(v3 if i >= 20 else None)
    return out


def _cross_up(a, b, i):
    return None not in (a[i], b[i], a[i - 1], b[i - 1]) and a[i] > b[i] and a[i - 1] <= b[i - 1]


def _cross_dn(a, b, i):
    return None not in (a[i], b[i], a[i - 1], b[i - 1]) and a[i] < b[i] and a[i - 1] >= b[i - 1]


def _hh(v: list, n: int, i: int):
    """بیشترین v[i-n+1..i] (None اگر کافی نیست)."""
    return max(v[i - n + 1:i + 1]) if i >= n - 1 else None


def _ll(v: list, n: int, i: int):
    return min(v[i - n + 1:i + 1]) if i >= n - 1 else None


def ichimoku(rows: list) -> tuple[list, list, list, list]:
    """(tenkan, kijun, spanA, spanB) — ابر روی کندل i = مقدار محاسبه‌شده در i−26 (بدون نگاه به آینده)."""
    h, l = [r[2] for r in rows], [r[3] for r in rows]
    m = len(rows)
    mid = lambda n, i: ((_hh(h, n, i) + _ll(l, n, i)) / 2) if i >= n - 1 else None   # noqa: E731
    tk, kj = [mid(9, i) for i in range(m)], [mid(26, i) for i in range(m)]
    ra = [None if (tk[i] is None or kj[i] is None) else (tk[i] + kj[i]) / 2 for i in range(m)]
    rb = [mid(52, i) for i in range(m)]
    sa = [ra[i - 26] if i >= 26 else None for i in range(m)]
    sb = [rb[i - 26] if i >= 26 else None for i in range(m)]
    return tk, kj, sa, sb


def resample(rows: list, ms: int) -> list:
    """کندل‌های بزرگ‌تر (فقط کامل‌ها) با زمان شروع."""
    out, cur = [], None
    for r in rows:
        b = int(r[0] // ms * ms)
        if cur is None or cur[0] != b:
            if cur is not None:
                out.append(tuple(cur))
            cur = [b, r[1], r[2], r[3], r[4], r[5] if len(r) > 5 else 0.0, 1]
        else:
            cur[2], cur[3], cur[4] = max(cur[2], r[2]), min(cur[3], r[3]), r[4]
            cur[5] += r[5] if len(r) > 5 else 0.0
            cur[6] += 1
    if cur is not None:
        out.append(tuple(cur))
    return out


# ── سیگنال‌ها: برای هر کندل (enter_long, enter_short, exit_long, exit_short) ─────
def signals(name: str, rows: list) -> list[tuple[bool, bool, bool, bool]]:
    name = base_of(name)   # V.2.26.0 — نسخه‌ها همان سیگنال پایه را دارند
    m = len(rows)
    c = [r[4] for r in rows]
    sig = [(False, False, False, False)] * m
    if name == "gh_bbandrsi":
        r_ = rsi(c, 14)
        tp = [(r[2] + r[3] + r[4]) / 3 for r in rows]
        lo, _, _ = bbands(tp, 20, 2)
        for i in range(m):
            el = r_[i] is not None and lo[i] is not None and r_[i] < 30 and c[i] < lo[i]
            sig[i] = (el, False, r_[i] is not None and r_[i] > 70, False)
    elif name == "gh_adxsmas":
        ad, s3, s6 = adx(rows, 14), sma(c, 3), sma(c, 6)
        for i in range(1, m):
            if ad[i] is None:
                continue
            sig[i] = (ad[i] > 25 and _cross_up(s3, s6, i), False, ad[i] < 25 and _cross_up(s6, s3, i), False)
    elif name == "gh_hlhb":
        hl2 = [(r[4] + r[1]) / 2 for r in rows]   # همان تعریف فایل اصلی: (close + open) / 2
        r_ = rsi(hl2, 10)
        e5, e10, ad = ema(c, 5), ema(c, 10), adx(rows, 14)
        fifty = [50.0] * m
        for i in range(1, m):
            if ad[i] is None:
                continue
            el = _cross_up(r_, fifty, i) and _cross_up(e5, e10, i) and ad[i] > 25
            xl = _cross_dn(r_, fifty, i) and _cross_dn(e5, e10, i) and ad[i] > 25
            sig[i] = (el, False, xl, False)
    elif name.startswith("pb_rsi2"):
        r2, s200, s5 = rsi(c, 2), sma(c, 200), sma(c, 5)
        for i in range(m):
            if None in (r2[i], s200[i], s5[i]):
                continue
            el = c[i] > s200[i] and r2[i] < 10
            es = c[i] < s200[i] and r2[i] > 90
            sig[i] = (el, es, c[i] > s5[i], c[i] < s5[i])
    elif name.startswith("pb_utbot"):
        a = atr_w(rows, 10)
        ts = [None] * m
        for i in range(1, m):
            if a[i] is None:
                continue
            nl = a[i] * 1.0
            p = ts[i - 1] if ts[i - 1] is not None else c[i]
            if c[i] > p and c[i - 1] > p:
                ts[i] = max(p, c[i] - nl)
            elif c[i] < p and c[i - 1] < p:
                ts[i] = min(p, c[i] + nl)
            else:
                ts[i] = c[i] - nl if c[i] > p else c[i] + nl
        for i in range(2, m):
            if ts[i] is None or ts[i - 1] is None:
                continue
            buy = c[i] > ts[i] and c[i - 1] <= ts[i - 1]
            sell = c[i] < ts[i] and c[i - 1] >= ts[i - 1]
            sig[i] = (buy, sell, sell, buy)
    elif name.startswith("pb_rangefilter"):
        per, mult = 23, 2.5
        dif = [None] + [abs(c[k] - c[k - 1]) for k in range(1, m)]
        av = _ema_opt(dif, per)
        sm = _ema_opt(av, per * 2 - 1)
        filt, up_, dn_, cond = [None] * m, 0, 0, 0
        for i in range(1, m):
            if sm[i] is None:
                continue
            r_ = sm[i] * mult
            pf = filt[i - 1] if filt[i - 1] is not None else c[i]
            filt[i] = max(pf, c[i] - r_) if c[i] > pf else min(pf, c[i] + r_)
            if filt[i - 1] is not None:
                up_ = up_ + 1 if filt[i] > filt[i - 1] else (0 if filt[i] < filt[i - 1] else up_)
                dn_ = dn_ + 1 if filt[i] < filt[i - 1] else (0 if filt[i] > filt[i - 1] else dn_)
            lc = c[i] > filt[i] and up_ > 0
            sc = c[i] < filt[i] and dn_ > 0
            prev = cond
            cond = 1 if lc else (-1 if sc else cond)
            buy, sell = lc and prev == -1, sc and prev == 1
            sig[i] = (buy, sell, sell, buy)
    elif name in NEW_BASES_V2380:
        sig = _signals_v2380(name, rows)
    elif name.startswith("pb_sp2l"):
        a = atr_w(rows, 14)
        for i in range(m):
            ss = sp2l_setup(rows, i, a)
            if ss:
                sig[i] = (ss[0] == "long", ss[0] == "short", False, False)
    elif name.startswith("pb_fib618"):
        a = atr_w(rows, 14)
        for i in range(m):
            fs = fib_setup(rows, i, a)
            if fs:
                sig[i] = (fs[0] == "long", fs[0] == "short", False, False)
    return sig


def _signals_v2380(name: str, rows: list) -> list:
    """V.2.38.0/V.2.38.1 — پایه‌های تازهٔ باقی‌مانده (فقط لانگ). سیگنال روی بسته شدن کندل i، ورود در باز شدن i+1."""
    m = len(rows)
    c, h, l = [r[4] for r in rows], [r[2] for r in rows], [r[3] for r in rows]
    sig = [(False, False, False, False)] * m
    s200 = sma(c, 200) if name in ("pb_ibs_4h", "pb_double7_4h") else None
    if name == "pb_ibs_4h":
        for i in range(1, m):
            if s200[i] is None:
                continue
            rg = h[i] - l[i]
            ibs = (c[i] - l[i]) / rg if rg > 0 else 0.5
            sig[i] = (c[i] > s200[i] and ibs < 0.2, False, c[i] > h[i - 1], False)
    elif name == "pb_double7_4h":
        for i in range(6, m):
            if s200[i] is None:
                continue
            sig[i] = (c[i] > s200[i] and c[i] <= _ll(c, 7, i), False, c[i] >= _hh(c, 7, i), False)
    elif name == "pb_ichimoku_4h":
        tk, kj, sa, sb = ichimoku(rows)
        for i in range(1, m):
            if None in (sa[i], sb[i], kj[i]):
                continue
            el = _cross_up(tk, kj, i) and sa[i] > sb[i] and c[i] > max(sa[i], sb[i])
            sig[i] = (el, False, c[i] < kj[i], False)
    return sig


def _src(spec: dict) -> str:
    return spec["src"] if spec.get("engine") else f"{REPO}/blob/main/user_data/strategies/{spec['src']}"


def _roi_at(roi: dict, minutes: float) -> float:
    k = max([t for t in roi if t <= minutes], default=0)
    return float(roi[k])


def simulate(name: str, sym: str, rows: list, t_from: float = 0, btc=None) -> list[dict]:
    """همهٔ معاملات بسته‌شده (ورود ≥ t_from). یک پوزیشن هم‌زمان برای هر نماد/استراتژی."""
    spec = STRATEGIES[name]
    sig = signals(name, rows)
    tf_ms = TF_MS[spec["tf"]]
    sl_pct = min(SL_CAP_PCT, float(spec["sl"]))
    _lv = uses_levels(spec)
    _atr = atr_w(rows, 14) if _lv else None
    max_bars = int(float(spec.get("max_hold_h", MAX_HOLD_H)) * H1 / tf_ms)
    out = []
    i, m = 1, len(rows)
    while i < m - 1:
        el, es = sig[i][0], sig[i][1] and spec["short"]
        if spec.get("btc_filter") and (el or es):   # V.2.26.0 — فقط وقتی BTC بالای EMA50 (۴h) است
            el = el and btc_up_at(btc, rows[i][0] + tf_ms)
            es = False
        if spec.get("bear"):   # V.2.37.0 — فقط شورت و فقط وقتی BTC زیر EMA50 است
            el = False
            es = es and btc_down_at(btc, rows[i][0] + tf_ms)
        if not (el or es):
            i += 1
            continue
        d = "long" if el else "short"
        sg = 1.0 if el else -1.0
        k = i + 1
        e = rows[k][1]
        if rows[k][0] < t_from or e <= 0:
            i += 1
            continue
        tp_x = None
        if _lv:
            sl_pct, tp_x = levels(name, rows, i, e, _atr)
            # V.2.35.0 — همان گیت زنده: setup نامعتبر یا SL کمتر از حداقل زنده (۰٫۵٪، طلا ۰٫۰۵٪) ⇒ ورود نیست
            if sl_pct is None or sl_pct < (0.05 if spec.get("gold") else 0.5):
                i += 1
                continue
        stop = e * (1 - sg * sl_pct / 100)
        peak = e
        ex = why = None
        j = k
        while j < m:
            h, l, cl = rows[j][2], rows[j][3], rows[j][4]
            if (sg > 0 and l <= stop) or (sg < 0 and h >= stop):
                ex, why = stop, ("be_sl" if (sg > 0 and stop > e * (1 - sl_pct / 100) + 1e-12)
                                 or (sg < 0 and stop < e * (1 + sl_pct / 100) - 1e-12) else "sl")
                break
            mins = (rows[j][0] - rows[k][0]) / 60_000
            roi = tp_x if tp_x is not None else _roi_at(spec["roi"], mins)
            tgt = e * (1 + sg * roi / 100)
            if (sg > 0 and h >= tgt) or (sg < 0 and l <= tgt):
                ex, why = tgt, "tp"
                break
            if j - k + 1 >= max_bars:   # V.2.41.0 — هم‌سان با زنده: ۴h ⇒ ۶ کندل = ۲۴ ساعت (قبلاً ۷ کندل = ۲۸ ساعت)
                ex, why = cl, "max_hold"
                break
            peak = max(peak, h) if sg > 0 else min(peak, l)
            if spec["trail"]:
                tpos, off = spec["trail"][0], spec["trail"][1]
                only_off = len(spec["trail"]) > 2 and spec["trail"][2]
                gain = sg * (peak / e - 1) * 100
                if gain >= off or not only_off:
                    trail_pct = tpos if gain >= off else sl_pct
                    ns = peak * (1 - sg * trail_pct / 100)
                    stop = max(stop, ns) if sg > 0 else min(stop, ns)
            exs = sig[j][2] if sg > 0 else sig[j][3]
            if spec.get("btc_filter") and not exs and not btc_up_at(btc, rows[j][0] + tf_ms) and j + 1 < m:
                ex, why = rows[j + 1][1], "btc_exit"   # روند BTC برگشت ⇒ خروج در open کندل بعد
                j += 1
                break
            if spec.get("bear") and not exs and btc_up_at(btc, rows[j][0] + tf_ms) and j + 1 < m:
                ex, why = rows[j + 1][1], "btc_exit"   # V.2.37.0 — BTC بالای EMA50 برگشت ⇒ بستن شورت
                j += 1
                break
            if exs and j + 1 < m:
                ex, why = rows[j + 1][1], "exit_signal"
                j += 1
                break
            j += 1
        if ex is None:
            break   # هنوز باز است (کاغذی رو به جلو: بعداً)
        gross = sg * (ex / e - 1) * 100
        out.append({"t": rows[k][0], "symbol": sym, "dir": d, "strategy": name, "gross_pct": round(gross, 4),
                    "exit": why, "bars": j - k + 1, "sl_pct": round(sl_pct, 4), "tp_pct": round(tp_x or 0.0, 4), "mfe": None, "drift": None,
                    "hour": int(rows[k][0] // H1 % 24), "market": "any", "exit_t": rows[min(j, m - 1)][0]})
        i = j + 1
    return out


def gold_symbol(data: dict) -> str | None:
    for g in GOLD_SYMBOLS:
        if len(((data or {}).get(g) or {}).get("1h") or []) >= 120:
            return g
    return None


def frames_for(frames: dict, tf: str) -> list:
    rows = br._norm_rows((frames or {}).get(tf) or [])
    if len(rows) < 120 and tf == "4h":   # طلا: ۴h از ۱h ساخته می‌شود
        h1 = br._norm_rows((frames or {}).get("1h") or [])
        rows = [r for r in resample(h1, 4 * H1) if r[6] == 4] if h1 else []
        rows = [tuple(r[:6]) for r in rows]
    return rows


# V.2.40.0 — نمادهای اضافه (پیشنهاددهنده/منتقد؛ «معاملهٔ بیشتر در بازار صعودی»): قبولی هر استراتژی فقط روی واچ‌لیست اصلی
# می‌ماند؛ روی نمادهای اضافه جدا سنجیده می‌شود (خارج از نمونه) و فقط با لبهٔ کافی زنده می‌شود.
EXT_MIN_N, EXT_MIN_AVG, EXT_MIN_PF = 30, 0.15, 1.2
EXT_STRICT_AVG, EXT_STRICT_PF = 0.20, 1.3


def _ext_eval(name: str, spec: dict, core: dict, ext_trades: list, all_trades: list, p: dict) -> dict:
    """آمار و ext_ok استراتژی روی نمادهای اضافه."""
    st = br._stats(ext_trades, p) if ext_trades else {"n": 0}
    out = {k: st.get(k) for k in ("n", "net_avg_pct", "profit_factor", "win_rate")}
    if ext_trades:
        ts = [x["t"] for x in ext_trades]
        split = min(ts) + (max(ts) - min(ts)) * float(p.get("train_frac") or 0.7)
        out["train"] = br._stats([x for x in ext_trades if x["t"] < split], p).get("net_avg_pct")
        out["valid"] = br._stats([x for x in ext_trades if x["t"] >= split], p).get("net_avg_pct")
        by_s: dict = {}
        for x in ext_trades:
            by_s[x["symbol"]] = by_s.get(x["symbol"], 0.0) + x["gross_pct"]
        top = max(by_s, key=by_s.get)
        out["without_top_symbol"] = br._stats([x for x in ext_trades if x["symbol"] != top], p).get("net_avg_pct")
        comb = br._stats(all_trades, p)
        out["combined_avg"], out["combined_pf"] = comb.get("net_avg_pct"), comb.get("profit_factor")
    a_min, pf_min = (EXT_STRICT_AVG, EXT_STRICT_PF) if spec.get("strict") else (EXT_MIN_AVG, EXT_MIN_PF)
    out["ext_ok"] = bool(core.get("passes") and ext_trades and (out.get("n") or 0) >= EXT_MIN_N
                         and (out.get("net_avg_pct") or -1) >= a_min and (out.get("profit_factor") or 0) >= pf_min
                         and (out.get("train") or -1) > 0 and (out.get("valid") or -1) > 0
                         and (out.get("without_top_symbol") or -1) > 0
                         and (out.get("combined_avg") or -1) >= MIN_EDGE_AVG_PCT
                         and (out.get("combined_pf") or 0) >= MIN_EDGE_PF)
    return out


def run_github(data: dict, params: dict | None = None, ext: set | None = None, long_data: dict | None = None) -> dict:
    """data: {sym: {'1h': rows, '5m': rows}} (همان trend_data بک‌تست ۹۰ روزه). ext = نمادهای اضافه (V.2.40.0).
    long_data = {sym: {'1h': rows}} حدود ۴۰۰ روزه برای کنترل ۳۶۵ روزه (V.2.42.0)؛ None ⇒ کنترل خاموش («off»)."""
    ext = set(ext or ())
    p = dict(br.DEFAULT_PARAMS)
    p.update(params or {})
    t0 = time.time()
    out: dict = {"repo": REPO, "sl_cap_pct": SL_CAP_PCT, "max_hold_h": MAX_HOLD_H, "strategies": {}}
    reg = btc_regime(((data or {}).get("BTC") or {}).get("4h") or [])
    gsym = gold_symbol(data)
    out["gold_symbol"] = gsym
    out["ext_symbols"] = sorted(ext)
    out["gate_v"] = GATE_V
    _order = {s: i for i, s in enumerate(data or {})}
    _reg_long = None
    if long_data is not None:
        try:
            _reg_long = btc_regime(frames_for((long_data or {}).get("BTC") or {}, "4h"))
        except Exception:   # noqa: BLE001
            _reg_long = None
    for name, spec in STRATEGIES.items():
        trades, t_all, ext_trades = [], [], []
        for sym, frames in (data or {}).items():
            if not applies(name, sym) or (spec.get("gold") and sym != gsym):
                continue
            rows = frames_for(frames, spec["tf"])
            if len(rows) < 120:
                continue
            if sym in ext:
                ext_trades += simulate(name, sym, rows, btc=reg)
                continue
            t_all += [rows[0][0], rows[-1][0]]
            trades += simulate(name, sym, rows, btc=reg)
        if not t_all:
            out["strategies"][name] = {"error": "no data", "passes": False, "source": _src(spec), "timeframe": spec["tf"]}
            continue
        res = br.summarize(trades, p, len(trades), {}, [(min(t_all), "", 0), (max(t_all), "", 0)], time.time() - t0)
        res.pop("_trades", None)
        tr_n = (res.get("train") or {}).get("net_avg_pct")
        va_n = (res.get("valid") or {}).get("net_avg_pct")
        robust = None
        if trades and spec.get("gold"):   # یک نماد ⇒ بدون بهترین معامله
            best = max(trades, key=lambda x: x["gross_pct"])
            robust = {"without_best_trade": round(best["gross_pct"], 3),
                      "net_avg_pct": br._stats([x for x in trades if x is not best], p).get("net_avg_pct")}
        elif trades:
            by_s: dict = {}
            for x in trades:
                by_s[x["symbol"]] = by_s.get(x["symbol"], 0.0) + x["gross_pct"]
            top = max(by_s, key=by_s.get)
            robust = {"without_top_symbol": top,
                      "net_avg_pct": br._stats([x for x in trades if x["symbol"] != top], p).get("net_avg_pct")}
        res["robust"] = robust
        eq = pk = dd = 0.0   # V.2.26.0 — بیشترین افت (جمع ٪ خالص معاملات به ترتیب زمان خروج)
        for x in sorted(trades, key=lambda x: x.get("exit_t") or x["t"]):
            eq += br._net(x, p["fee_main"], p)
            pk = max(pk, eq)
            dd = max(dd, pk - eq)
        res["max_dd_pct"] = round(dd, 3)
        res["worst_trade_pct"] = round(min((br._net(x, p["fee_main"], p) for x in trades), default=0.0), 3)
        res["by_dir"] = {d: br._stats([x for x in trades if x["dir"] == d], p) for d in ("long", "short")}
        res["passes"] = bool(len(trades) >= 30 and (tr_n or -1) > 0 and (va_n or -1) > 0
                             and robust and (robust.get("net_avg_pct") or -1) > 0)
        _a = res.get("all") or {}
        if res["passes"] and ((_a.get("net_avg_pct") or 0) < MIN_EDGE_AVG_PCT or (_a.get("profit_factor") or 0) < MIN_EDGE_PF):
            res["passes"], res["thin_edge"] = False, True   # V.2.34.1 — قبول با حاشیهٔ خیلی کم ⇒ زنده نه
        if res["passes"] and spec.get("bear"):   # V.2.37.0 — منتقد: دورهٔ نزولی ممکن است فقط در یک نیمه باشد
            if ((res.get("train") or {}).get("n") or 0) < 12 or ((res.get("valid") or {}).get("n") or 0) < 12:
                res["passes"], res["bear_split_fail"] = False, True
        if res["passes"] and spec.get("strict"):   # V.2.35.0 — قبولی سخت‌تر برای پایه‌های تازه (پیشنهاد منتقد)
            _f12 = ((_a.get("net_avg_pct_by_fee") or {}).get("0.12"))
            if (len(trades) < 40 or (_a.get("net_avg_pct") or 0) < 0.20 or (_a.get("profit_factor") or 0) < 1.3
                    or (_f12 is not None and _f12 <= 0)):
                res["passes"], res["strict_fail"] = False, True
            _v = res.get("valid") or {}   # V.2.38.0 — منتقد: اعتبارسنجی هم n≥۱۲، pf≥۱٫۱، میانگین≥۰٫۱۰٪
            if res["passes"] and ((_v.get("n") or 0) < STRICT_VALID_N or (_v.get("profit_factor") or 0) < STRICT_VALID_PF
                                  or (_v.get("net_avg_pct") or 0) < STRICT_VALID_AVG):
                res["passes"], res["valid_fail"] = False, True
        if spec.get("tf") == "15m" and trades:   # V.2.39.0 — تایم پایین: قبولی با کارمزد زندهٔ ۰٫۱۸٪
            _f18 = sum(br._net(x, LTF_FEE_PCT, p) for x in trades) / len(trades)
            res["net_avg_pct_fee018"] = round(_f18, 4)
            if res["passes"] and _f18 < LTF_MIN_AVG_AT_FEE:
                res["passes"], res["ltf_fee_fail"] = False, True
        try:   # V.2.42.0 — تک‌پوزیشنی (مثل زنده) + کنترل ۳۶۵ روزه؛ passes تغییر نمی‌کند، فقط gate_block
            _o = _gate_stats(one_slot(trades, _order), p)
            _on, _oa = _o.get("n") or 0, _o.get("net_avg_pct")
            res["one"] = {"status": "na" if _on < ONE_MIN_N else ("fail" if (_oa is None or _oa <= 0) else "ok"),
                          "n": _on, "net_avg_pct": _oa, "profit_factor": _o.get("profit_factor")}
            if long_data is None:
                res["long"] = {"status": "off"}
            elif res["passes"] and res["one"]["status"] != "fail":
                res["long"] = long_eval(name, spec, long_data, _reg_long, p, _order, ext)
        except Exception as _ge:   # noqa: BLE001
            res["long"] = {"status": "unavailable", "ts": time.time(), "error": f"{type(_ge).__name__}: {_ge}"[:120]}
        try:   # V.2.36.0 — فقط گزارش؛ passes تغییر نمی‌کند
            _span = (max(t_all) - min(t_all)) / 86_400_000 if t_all else 0
            res["capped"], res["mc"], res["wf"] = mc_report(name, trades, p, _span) if (res["passes"] and trades) else ({}, {}, [])
        except Exception as _mce:   # noqa: BLE001
            res["mc"] = {"flag": "error", "error": f"{type(_mce).__name__}: {_mce}"[:120]}
        res["source"] = _src(spec)
        res["timeframe"] = spec["tf"]
        if ext:
            try:
                res["ext"] = _ext_eval(name, spec, res, ext_trades, trades + ext_trades, p)
            except Exception as _xe:   # noqa: BLE001
                res["ext"] = {"ext_ok": False, "error": f"{type(_xe).__name__}: {_xe}"[:120]}
        out["strategies"][name] = res
    out["secs"] = round(time.time() - t0, 1)
    return out


# ─────────────────────────────────────────────────────────────
# کاغذی رو به جلو: همان simulate روی کندل‌های تازه؛ فقط معاملاتی که بعد از شروع آزمون وارد شده‌اند
# ─────────────────────────────────────────────────────────────
FWD: dict = {"start": None, "trades": [], "keys": [], "last_run": None, "errors": []}


EXT_FWD_CAP = 2000
EXT_VETO_N = 10


def forward_add(name: str, sym: str, rows: list, btc=None, ext: bool = False) -> int:
    """rows: کندل‌های بسته‌شدهٔ اخیر. معاملات بسته‌شدهٔ جدید (ورود ≥ start) به دفتر اضافه می‌شوند.
    V.2.40.0 — ext=True ⇒ دفتر جدای نمادهای اضافه (آمار وتو/ارتقا/رتبهٔ اصلی و آزمون C2 دست نمی‌خورند)."""
    if not FWD.get("start"):
        return 0
    if ext:
        start = float(FWD.setdefault("ext_start", time.time()))
        ek = set(FWD.setdefault("ext_keys", []))
        n = 0
        for x in simulate(name, sym, br._norm_rows(rows), t_from=start * 1000, btc=btc):
            k = f"{name}|{sym}|{int(x['t'])}"
            if k in ek:
                continue
            ek.add(k)
            FWD["ext_keys"].append(k)
            FWD.setdefault("ext_trades", []).append(x)
            n += 1
        del FWD.setdefault("ext_trades", [])[:-EXT_FWD_CAP]
        del FWD["ext_keys"][:-2 * EXT_FWD_CAP]
        return n
    keys = set(FWD["keys"])
    n = 0
    for x in simulate(name, sym, br._norm_rows(rows), t_from=float(FWD["start"]) * 1000, btc=btc):
        k = f"{name}|{sym}|{int(x['t'])}"
        if k in keys:
            continue
        keys.add(k)
        FWD["keys"].append(k)
        FWD["trades"].append(x)
        n += 1
    if name in PP_STRATEGIES:   # V.2.39.2 — دفتر جدا و بدون برش مشترک برای آزمون سبد کاغذی (RF-4h-C2)
        pk = set(FWD.setdefault("pp_keys", []))
        for x in simulate(name, sym, br._norm_rows(rows), t_from=float(FWD["start"]) * 1000, btc=btc):
            k = f"{name}|{sym}|{int(x['t'])}"
            if k in pk:
                continue
            pk.add(k)
            FWD["pp_keys"].append(k)
            FWD.setdefault("pp_trades", []).append(dict(x, seen=float(FWD.get("last_run") or time.time())))
        del FWD.setdefault("pp_trades", [])[:-PP_CAP]   # V.2.39.3 — بدون KeyError
        del FWD["pp_keys"][:-2 * PP_CAP]
    del FWD["keys"][:-12000]   # V.2.38.2 — منتقد: کلید ≥ ۲× معاملات (وگرنه معاملهٔ تکراری) و ۶۰۰۰ معامله برای آمار وتو
    del FWD["trades"][:-6000]
    return n


# ── V.2.39.2 — آزمون کاغذیِ سبد «RF-4h-C2» (درخواست کاربر؛ پیشنهاددهنده/منتقد). فقط گزارش؛ هیچ مسیر زنده‌ای این را نمی‌خواند.
PP_STRATEGIES = ("pb_rangefilter_4h_tr",)
PP_CAP = 3000
PP_FINAL_LAG_H = 32          # معاملهٔ باز هنوز در دفتر نیست ⇒ فقط ورودهای قدیمی‌تر از ۳۲ ساعت «قطعی»اند
PP_FEE_RT = 0.18             # کارمزد زنده (+ لغزش ۰٫۱۰ روی sl/be_sl از br._net)
RF_C2_PAPER = {"id": "rf4h_c2", "strategy": "pb_rangefilter_4h_tr", "max_open": 3, "max_same_dir": 2,
               "notional": 14.0, "risk_cap": 4.5, "leverage": 5, "ref_equity": 40.66,
               "min_n": 100, "min_days": 56, "max_days": 84, "pf_pass": 1.1}
RF_CUR_PAPER = {**RF_C2_PAPER, "id": "rf4h_current", "max_open": 2, "notional": 21.0, "risk_cap": 3.0}


def _pp_close_t(x: dict) -> float:
    """زمان واقعی آزاد شدن اسلات: exit_t = باز شدن کندل خروج؛ خروج سیگنالی همان‌جا، بقیه (sl/tp/max_hold/تریل) تا پایان کندل."""
    tf = TF_MS[STRATEGIES.get(x.get("strategy"), {}).get("tf", "4h")]
    return float(x.get("exit_t") or x["t"]) + (0 if x.get("exit") in ("exit_signal", "btc_exit") else tf)


def paper_portfolio(trades: list, cfg: dict, since_s: float, now_s: float, order: dict | None = None) -> dict:
    """بازپخش معاملات کاغذی یک استراتژی با قوانین سبد (اسلات، هم‌جهت، ریسک تعهدشدهٔ روزانه). دلار = notional × خالص٪."""
    p = dict(br.DEFAULT_PARAMS)
    order = order or {}
    est = cfg["notional"] * (SL_CAP_PCT + PP_FEE_RT) / 100.0
    lag_ms = PP_FINAL_LAG_H * H1
    cut = now_s * 1000 - lag_ms
    rel = sorted((x for x in trades if x.get("strategy") == cfg["strategy"] and x["t"] / 1000 >= since_s),
                 key=lambda x: (x["t"], order.get(x.get("symbol"), 999), str(x.get("symbol"))))
    # دیر رسیده (ثبت بیش از ۳۲ ساعت بعد از ورود، مثلاً خطای دریافت داده) ⇒ از بازپخش بیرون تا تصمیم‌های قطعی عوض نشوند
    late_ids = {id(x) for x in rel if x.get("seen") is not None and float(x["seen"]) * 1000 - x["t"] > lag_ms}
    out_open, taken, skip, realized = [], [], {"slots": 0, "same_dir": 0, "risk": 0, "symbol": 0}, {}
    day = lambda ms: int(ms // 86_400_000)   # noqa: E731
    for x in rel:
        if id(x) in late_ids:
            continue
        for o in [o for o in out_open if _pp_close_t(o) <= x["t"]]:
            out_open.remove(o)
            realized[day(_pp_close_t(o))] = realized.get(day(_pp_close_t(o)), 0.0) + o["usd"]
        if any(o.get("symbol") == x.get("symbol") for o in out_open):
            skip["symbol"] += 1
            continue
        if len(out_open) >= cfg["max_open"]:
            skip["slots"] += 1
            continue
        if sum(1 for o in out_open if o.get("dir") == x.get("dir")) >= cfg["max_same_dir"]:
            skip["same_dir"] += 1
            continue
        if min(0.0, realized.get(day(x["t"]), 0.0)) - est * len(out_open) - est < -cfg["risk_cap"] - 1e-9:
            skip["risk"] += 1
            continue
        y = dict(x, usd=cfg["notional"] * br._net(x, PP_FEE_RT, p) / 100.0, final=x["t"] < cut)
        out_open.append(y)
        taken.append(y)
    fin = [x for x in taken if x["final"]]
    prov = [x for x in taken if not x["final"]]
    gw = sum(x["usd"] for x in fin if x["usd"] > 0)
    gl = -sum(x["usd"] for x in fin if x["usd"] < 0)
    eq = pk = dd = 0.0
    for x in sorted(fin, key=_pp_close_t):
        eq += x["usd"]
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    days = max(0.0, (now_s - since_s) / 86400.0)
    n = len(fin)
    pf = round(gw / gl, 3) if gl > 0 else (None if not n else 99.0)
    res = {"id": cfg["id"], "since": since_s, "days": round(days, 1), "n_final": n, "n_provisional": len(prov),
           "late_n": len(late_ids), "skipped": skip, "trades_per_day": round(n / days, 2) if days >= 1 else None,
           "win_rate": round(sum(1 for x in fin if x["usd"] > 0) / n, 3) if n else None, "profit_factor": pf,
           "net_avg_pct": round(sum(br._net(x, PP_FEE_RT, p) for x in fin) / n, 4) if n else None,
           "net_usd": round(eq, 3), "net_pct_of_ref_equity": round(eq / cfg["ref_equity"] * 100, 2),
           "max_dd_usd": round(dd, 3), "provisional_usd": round(sum(x["usd"] for x in prov), 3),
           "rules": {k: cfg[k] for k in ("max_open", "max_same_dir", "notional", "risk_cap", "leverage")},
           "fee": "0.18% RT + 0.10% slip on sl/be_sl (live friction)"}
    if days < cfg["min_days"]:
        res["verdict"] = "collecting"
    elif n >= cfg["min_n"]:
        res["verdict"] = "pass" if (pf or 0) > cfg["pf_pass"] else "fail"
    else:
        res["verdict"] = "insufficient" if days >= cfg["max_days"] else "collecting"
    return res


def paper_portfolios_report(now_s: float | None = None) -> dict:
    now_s = float(now_s or FWD.get("last_run") or time.time())
    try:
        from watchlist import WATCHLIST as _wl
        order = {str(s).upper(): i for i, s in enumerate(_wl)}
    except Exception:
        order = {}
    tr = FWD.get("pp_trades") or []
    start = float((FWD.get("pp_start") or {}).get("rf4h_c2") or 0)
    out = {"note": "آزمون کاغذی RF-4h-C2 (۳ اسلات، ۱۴$، سقف ریسک ۴٫۵$) — ≥۱۰۰ معامله و ≥۸ هفته؛ قبول اگر PF > ۱٫۱؛ "
                   "زنده فقط با تصمیم کاربر. هیچ تنظیم زنده‌ای عوض نشده."}
    if start:
        out["rf4h_c2"] = paper_portfolio(tr, RF_C2_PAPER, start, now_s, order)
        out["rf4h_current"] = paper_portfolio(tr, RF_CUR_PAPER, start, now_s, order)
    if FWD.get("trades"):   # نمای قبلی از دفتر مشترک (بریده‌شده؛ برای تصمیم نیست)
        retro = paper_portfolio(FWD["trades"], RF_C2_PAPER, float(FWD.get("start") or 0), now_s, order)
        retro["label"] = "retro — not decision-grade (shared FWD ledger, trimmed, rules designed after seeing it)"
        out["rf4h_c2_retro"] = retro
    return out


def ext_vetoed(name: str) -> bool:
    """V.2.40.0 — کاغذی رو به جلوی همان استراتژی روی نمادهای اضافه n ≥ ۱۰ و میانگین < ۰ ⇒ ورود زنده روی نماد اضافه نه."""
    fw = [x for x in (FWD.get("ext_trades") or []) if x.get("strategy") == name]
    if len(fw) < EXT_VETO_N:
        return False
    st = br._stats(fw, dict(br.DEFAULT_PARAMS))
    return float(st.get("net_avg_pct") or 0) < 0


_FWD_CACHE: dict = {}


def fwd_stats(name: str, since: float = 0.0) -> dict:
    """V.2.38.2 — آمار کاغذی رو به جلوی همین نام (خالص با کارمزد، br._stats)؛ since = ثانیه (ورود ≥ since)."""
    tr = FWD.get("trades") or []
    key = (name, float(since or 0), len(tr), id(tr), (tr[-1].get("t") if tr else None))
    if key in _FWD_CACHE:
        return _FWD_CACHE[key]
    fw = [x for x in tr if x.get("strategy") == name and float(x.get("t") or 0) / 1000 >= float(since or 0)]
    out = br._stats(fw, dict(br.DEFAULT_PARAMS)) if fw else {"n": 0, "net_avg_pct": None}
    if len(_FWD_CACHE) > 2000:
        _FWD_CACHE.clear()
    _FWD_CACHE[key] = out
    return out


def fwd_veto_decide(name: str, vetoed_since: float | None) -> tuple[bool, dict]:
    """(وتو؟، آمار). vetoed_since = زمان وتوی قبلی یا None (هیسترزیس: برداشتن فقط با کاغذی تازهٔ خوب)."""
    if vetoed_since:
        f = fwd_stats(name, vetoed_since)
        ok = int(f.get("n") or 0) >= FWD_UNVETO_N and float(f.get("net_avg_pct") or -1) >= FWD_UNVETO_AVG
        return (not ok), f
    f = fwd_stats(name)
    n, a = int(f.get("n") or 0), f.get("net_avg_pct")
    if a is None:
        return False, f
    a = float(a)
    return bool((n >= FWD_VETO_N and a <= FWD_VETO_AVG) or (n >= FWD_VETO_FAST_N and a <= FWD_VETO_FAST_AVG)), f


def report(backtest: dict | None) -> dict:
    p = dict(br.DEFAULT_PARAMS)
    out = {"repo": REPO, "note": "کاغذی — پول واقعی فقط اگر بک‌تست ۹۰ روزه قبول + کاغذی رو به جلو n ≥ ۱۵ با میانگین > ۰",
           "forward_start": FWD.get("start"), "forward_last_run": FWD.get("last_run"),
           "forward_errors": (FWD.get("errors") or [])[-5:], "rules": {"sl_cap_pct": SL_CAP_PCT, "max_hold_h": MAX_HOLD_H},
           "strategies": {}}
    bt = ((backtest or {}).get("strategies") or {})
    for name, spec in STRATEGIES.items():
        b = bt.get(name) or {}
        fw = [x for x in FWD["trades"] if x["strategy"] == name]
        fs = br._stats(fw, p)
        bsum = {"passes": b.get("passes"), "n": (b.get("all") or {}).get("n"),
                "net_avg_pct": (b.get("all") or {}).get("net_avg_pct"),
                "profit_factor": (b.get("all") or {}).get("profit_factor"),
                "win_rate": (b.get("all") or {}).get("win_rate"),
                "train": (b.get("train") or {}).get("net_avg_pct"), "valid": (b.get("valid") or {}).get("net_avg_pct"),
                "trades_per_day": b.get("trades_per_day"), "exit_mix": b.get("exit_mix"), "robust": b.get("robust"),
                "max_dd_pct": b.get("max_dd_pct"), "worst_trade_pct": b.get("worst_trade_pct"),
                "capped": b.get("capped"), "mc": b.get("mc"), "wf": b.get("wf"), "ext": b.get("ext"),
                "one": b.get("one"), "long": b.get("long"),
                "by_dir": {d: {kk: (x or {}).get(kk) for kk in ("n", "net_avg_pct")}
                           for d, x in (b.get("by_dir") or {}).items()}} if b else None
        out["strategies"][name] = {
            "timeframe": spec["tf"], "source": _src(spec),
            "backtest_90d": bsum,
            "forward_paper": {kk: fs.get(kk) for kk in ("n", "net_avg_pct", "win_rate", "profit_factor", "net_total_usdt")},
            "candidate_for_micro_live": bool(b.get("passes") and (fs.get("n") or 0) >= 15 and (fs.get("net_avg_pct") or -1) > 0)}
    out["ext_symbols"] = ((backtest or {}).get("ext_symbols") or [])   # V.2.40.0
    try:   # V.2.39.2
        out["paper_portfolios"] = paper_portfolios_report()
    except Exception as _ppe:   # noqa: BLE001
        out["paper_portfolios"] = {"error": f"{type(_ppe).__name__}: {_ppe}"[:160]}
    return out
