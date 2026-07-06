# SignalDesk — Crypto Signal Frontend

فرانت‌اند پلتفرم تحلیل چندمدلی سیگنال‌های اسکلپ فیوچرز کریپتو.

## اجرا روی سیستم خودت

```bash
npm install
npm run dev
```

## Build برای دیپلوی

```bash
npm run build
```

## دیپلوی روی GitHub Pages

این پروژه یک ورک‌فلوی GitHub Actions آماده داره (`.github/workflows/deploy.yml`)
که با هر push به شاخه‌ی `main`، خودش build و publish می‌کنه.

مراحل فعال‌سازی (فقط یک‌بار لازمه):

1. این پوشه رو به ریپوی `crypto-signal-frontend` روی GitHub push کن.
2. برو به Settings → Pages
3. زیر «Build and deployment» → «Source» رو روی **GitHub Actions** بذار.
4. چند دقیقه صبر کن، آدرس سایت زیر تب Actions یا همون صفحه‌ی Pages نمایش داده می‌شه:
   `https://<username>.github.io/crypto-signal-frontend/`

> نکته: اگر اسم ریپو رو چیز دیگه‌ای گذاشتی، حتماً مقدار `base` توی
> `vite.config.js` رو هم به همون اسم تغییر بده، وگرنه استایل‌ها و فایل‌ها لود نمی‌شن.

## وضعیت فعلی

این نسخه فقط **رابط کاربری (UI)** فاز ۲ هست با داده‌ی نمایشی (Mock).
اتصال واقعی به ۴ مدل هوش مصنوعی و منطق تحلیل در فاز ۳ (Backend) اضافه می‌شه.
