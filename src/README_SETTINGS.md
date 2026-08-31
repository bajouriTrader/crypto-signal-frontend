# V.2.10.19 — صفحه تنظیمات + رمز پلتفرم

## بک‌اند (HuggingFace Space)

فایل‌های جدید/جایگزین:
- `runtime_settings.py` (جدید)
- `settings_api.py` (جدید)
- `real_trade.py` (جایگزین — apply_runtime_settings)
- `version.py` → `APP_VERSION = "V.2.10.19"`

### در `app.py`
```python
from settings_api import router as settings_router
app.include_router(settings_router)
```

### در `auth.py` (چک رمز ورود)
```python
import runtime_settings

def check_site_password(password: str) -> bool:
    override = runtime_settings.get_site_password_override()
    expected = override if override is not None else SITE_PASSWORD
    if not expected:
        return False
    return password == expected
```
در `/auth/login` به‌جای مقایسه مستقیم با `SITE_PASSWORD` از `check_site_password` استفاده کن.

Relaunch Space.

## فرانت (GitHub Pages)
- `src/SettingsPanel.jsx` (جدید)
- `src/main.jsx` (جایگزین)
- `src/App.jsx` (لینک «تنظیمات» در topbar و footer)

push + hard refresh.

## استفاده
1. ورود با رمز پلتفرم
2. لینک **تنظیمات** در بالای صفحه
3. تغییر پارامترهای ریل → ذخیره
4. بخش پایین: تغییر رمز ورود

## نکات
- تنظیمات در `data/runtime_settings.json`
- رمز override در `data/site_password.override`
- روی HF بدون Persistent Storage ممکن است بعد از rebuild پاک شوند؛ Secrets محیطی همچنان fallback است.
