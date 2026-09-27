# V.2.10.94.1 — Settings registry sync

## چرا
چند پارامتر در `real_trade` از `cfg` خوانده می‌شدند ولی در `runtime_settings.DEFAULTS` / صفحه Settings نبودند؛ یا در UI نبودند (`breakeven_min_r`).

## تغییرات
### backend
- `runtime_settings`: اضافه شدن کلیدهای `post_negative_*`, `global_sl_*`, `enable_regime_adverse_*`, `stale_flat_*`, + range برای `breakeven_min_r` / CI / ADX
- `real_trade`: `GLOBAL_SL_LIMIT/LOOKBACK/LOCK` از Settings قابل اعمال
- `version` → V.2.10.94.1

### frontend
- `SettingsPanel.jsx`: همه کلیدهای بالا + `breakeven_min_r` در LABELS و GROUPS

## بعد از دیپلوی — در Settings چک/Save کنید
| کلید | مقدار پیشنهادی |
|------|----------------|
| breakeven_trigger_pct | **0.3** (نه 0.8) |
| breakeven_min_r | **0.8** |
| float_only_if_slots_full | true |
| float_min_r | 1.2 |
| anti_noise_fail_closed | true |

اگر `breakeven_trigger_pct=0.8` مانده، احتمالاً با `min_r` قاطی شده — trigger را 0.3 بگذارید.

منطق ورود/خروج .94 عوض نشده؛ فقط registry و UI.
