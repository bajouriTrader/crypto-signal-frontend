## V.1.5 — برچسب `is_probation_trade` (تکمیل کار عقب‌افتاده از V.1.3)

موقع فیکس باگ مصرف دوگانه‌ی probation (V.1.3)، یه پیشنهاد قبلی جا مونده بود: برچسب‌گذاری هر معامله با این‌که آیا از طریق probation باز شده یا نه، تا بشه win-rate این دو گروه رو جدا سنجید. این نسخه همون رو اضافه می‌کنه — بدون تغییر منطق اصلی probation.

### تغییرات

**`signal_filters.py`**
- `confirm_probation_trial_for_trade()` حالا یک عنصر سوم هم برمی‌گردونه: `is_probation_trade` (bool) — `True` فقط وقتی این معامله واقعاً از مصرف یک پیشنهاد pending باز شده، نه یک سیگنال عادی.

**`app.py`**
- خروجی سوم بالا گرفته می‌شه و به `demo_trade.start_demo_trade()` پاس داده می‌شه.
- `/demo-trade/stats` یک تفکیک جدید برمی‌گردونه: `by_probation` (`probation` در برابر `normal`)، دقیقاً مثل تفکیک‌های موجود `by_mode`/`by_direction`/`by_symbol`.
- `APP_VERSION` → `V.1.5`.

**`demo_trade.py`**
- `start_demo_trade()` یک پارامتر جدید می‌گیره: `is_probation_trade: bool = False`، و روی خودِ دیکشنری `trade` ذخیره‌ش می‌کنه.

**`supabase_client.py`**
- `save_demo_trade()` فیلد `is_probation_trade` رو هم توی ردیفی که به Supabase می‌فرسته می‌ذاره.

**`App.jsx`**
- نشان نسخه‌ی بالای صفحه دیگه فرمت «فرانت‌اند / بک‌اند» رو نشون نمی‌ده — فقط یک عدد نشون می‌ده (نسخه‌ی بک‌اند، از `GET /version`؛ تا وقتی جواب نیومده، موقتاً `FRONTEND_VERSION` نشون داده می‌شه). جزئیات دو نسخه هنوز توی `title` (تولتیپ روی هاور) موجوده، برای دیباگ.
- `FRONTEND_VERSION` به `V.1.5` بروز شد، چون این‌بار خودِ فرانت (`AdminPanel.jsx`) واقعاً تغییر کرده.

**`AdminPanel.jsx`**
- ستون جدید «Probation» به جدول معاملات دمو اضافه شد (🧪 آزمایشی / —).
- یک جدول تفکیک جدید «تفکیک بر اساس probation» (مثل تفکیک حالت/جهت/ارز) به بخش آمار اضافه شد.
- فیلتر جدید «Probation» (همه / فقط آزمایشی / فقط عادی) به نوار فیلتر اضافه شد.
- خروجی Excel و خروجی Markdown (همون فرمت گزارش `demo-trades-*.md`) هم ستون Probation رو دارن.

### ⚠️ قبل از دیپلوی: یک migration دیتابیس لازمه
فایل `migration_add_is_probation_trade.sql` رو **قبل از دیپلوی بک‌اند** توی Supabase SQL Editor اجرا کن:
```sql
ALTER TABLE demo_trades
ADD COLUMN IF NOT EXISTS is_probation_trade boolean NOT NULL DEFAULT false;
```
اگه این ستون رو اضافه نکنی، هر `POST /demo-trade/start` با خطا از Supabase برمی‌گرده (چون `save_demo_trade` حالا یک فیلد ناشناخته می‌فرسته).

### نکته‌ی مهم درباره‌ی داده‌های قدیمی
معاملاتی که قبل از این نسخه ثبت شدن، `is_probation_trade = false` می‌گیرن (چون این ستون قبلاً اصلاً وجود نداشت) — یعنی نمی‌شه با این فلگ رفت عقب و فهمید کدوم معاملات قدیمی (مثلاً همون خوشه‌ی مشکوک ۴/۲۸-۴/۲۹ که قبلاً بررسی کردیم) واقعاً probation بودن یا نه. این فلگ فقط از این نسخه به بعد قابل‌اعتماده.

### فایل‌های این نسخه

**بک‌اند:**
- `app.py`, `signal_filters.py`, `demo_trade.py`, `supabase_client.py` (تغییر یافته)
- `indicators.py` (بدون تغییر — فقط برای کامل بودن snapshot)
- `migration_add_is_probation_trade.sql` (باید قبل از دیپلوی بک‌اند اجرا بشه)

**فرانت‌اند:**
- `AdminPanel.jsx` (تغییر یافته — ستون/فیلتر/تفکیک probation)
- `App.jsx` (تغییر یافته — نشان نسخه ساده‌سازی شد، فقط یک عدد)
- `index.css` (بدون تغییر)

⚠️ برخلاف V.1.4، این‌بار **فرانت هم باید دوباره دیپلوی بشه** (چون `AdminPanel.jsx` واقعاً عوض شده) — روی GitHub Pages فایل جدید رو جایگزین کن.

### نحوه‌ی برگشت از V.1.5 به V.1.4
- بک‌اند: `app.py`, `signal_filters.py`, `demo_trade.py`, `supabase_client.py` رو با نسخه‌ی پوشه‌ی `V.1.4/` جایگزین کن.
- فرانت: `AdminPanel.jsx` رو با نسخه‌ی `V.1.4/` جایگزین کن.
- ستون `is_probation_trade` توی دیتابیس رو می‌تونی نگه داری (بی‌ضرره) یا با `ALTER TABLE demo_trades DROP COLUMN is_probation_trade;` حذف کنی.
