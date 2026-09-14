V.2.10.72 — فیکس نمایش اخبار

باگ اصلی: فیلد news_blackout در JSON وضعیت ساخته می‌شد ولی در return نمی‌آمد.
الان:
1. status.news_blackout کامل برمی‌گردد
2. GET /news-calendar عمومی (بدون لاگین)
3. seed fallback اگر API از Space قطع باشد
4. فرانت از /news-calendar می‌خواند

بک‌اند: news_blackout.py, real_trade.py, app.py, runtime_settings.py, version.py
فرانت: SessionClock.jsx
