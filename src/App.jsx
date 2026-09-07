import { useState, useRef, useEffect } from "react";

const API_URLS = [
  "https://asbajouri-it-assistant-api.hf.space",
];

// Cache برای custom_qa
let _qaCache = null;
let _qaCacheTime = 0;

async function fetchWithFallback(path, options) {
  // retries/retryDelayMs پیش‌فرض ۰/بدون‌تأخیرن — یعنی رفتار همه‌ی call siteهای فعلی (weather,
  // admin/login, extract-image, ...) دقیقاً همون قبلیه، هیچ‌کدوم عوض نشدن.
  // فقط /chat به‌صورت صریح retries:1 پاس می‌ده (پایین‌تر) چون تنها جایی‌ست که به‌خاطر زنجیره‌ی
  // ۴ تا provider رایگان، گاهی یه burst کوتاه باعث ۵۰۳ میشه که چند ثانیه بعد خودش برطرف میشه.
  // ۱۸ اوت ۲۰۲۶: پارامتر signal (اختیاری) اضافه شد تا فراخوان بتونه یه AbortSignal بیرونی بده (مثلاً
  // برای دکمه‌ی «توقف» موقع لود جواب AI) — این signal با همون AbortController داخلیِ هر تلاش (که
  // برای timeout استفاده می‌شه) ترکیب می‌شه، بدون این‌که رفتار timeout هیچ‌کدوم از call siteهای دیگه عوض بشه.
  const { timeoutMs, retries = 0, retryDelayMs = 2500, signal: externalSignal, ...fetchOptions } = options || {};
  for (let attempt = 0; attempt <= retries; attempt++) {
    if (externalSignal && externalSignal.aborted) throw new DOMException("لغو شد توسط کاربر", "AbortError");
    for (const base of API_URLS) {
      try {
        const controller = new AbortController();
        const t = setTimeout(() => controller.abort(), timeoutMs || 12000);
        const onExternalAbort = () => controller.abort();
        if (externalSignal) externalSignal.addEventListener("abort", onExternalAbort);
        let res;
        try {
          res = await fetch(`${base}${path}`, { ...fetchOptions, signal: controller.signal });
        } finally {
          clearTimeout(t);
          if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);
        }
        if (res.ok) return res;
      } catch (e) {
        if (externalSignal && externalSignal.aborted) throw new DOMException("لغو شد توسط کاربر", "AbortError");
        continue;
      }
    }
    if (attempt < retries) {
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
    }
  }
  throw new Error("هر دو سرور در دسترس نیستند");
}
// === آب و هوا — تشخیص سوال و استخراج نام شهر ===
const IRAN_CITIES = ["تهران", "مشهد", "شاندیز", "اصفهان", "شیراز", "تبریز", "اهواز", "کرج", "قم", "کرمان", "یزد", "رشت", "همدان", "ارومیه", "زاهدان", "ساری", "بندرعباس", "کرمانشاه", "اراک", "زنجان", "قزوین", "گرگان", "سنندج", "خرم‌آباد", "خرم آباد", "یاسوج", "بجنورد", "بیرجند", "ایلام", "بوشهر", "دماوند", "توس"];

// نرمال‌سازی متن فارسی (حروف عربی/فارسی یکسان، حروف کوچک) — هم برای جستجوی اسناد هم برای جستجوی تلفن استفاده میشه
const normalizeText = (t) => t
  .toLowerCase()
  .replace(/ي/g, "ی")   // ي → ی
  .replace(/ك/g, "ک")   // ك → ک
  .replace(/ى/g, "ی")   // ى → ی
  .replace(/[\u200c\u200d]/g, " ")   // نیم‌فاصله (ZWNJ/ZWJ) → فاصله‌ی عادی، وگرنه «بیت‌کوین» (با نیم‌فاصله) و «بیت کوین» (با فاصله‌ی معمولی) دو رشته‌ی متفاوت حساب می‌شن
  .replace(/[؀-ۿ]+/g, m => m)
  .trim();


// === تاریخ امروز / فردا / دیروز + هفته میلادی (قطعی، بدون AI) ===
const isDateQuery = (text) => {
  const t = text || "";
  if (/قیمت|نرخ|دلار|طلا|سکه|آب\s*هوا|منو|غذا|داخلی|ایمیل|اخبار/i.test(t)) return false;
  return /تاریخ|امروز|فردا|دیروز|پریروز|پس\s*فردا|چه\s*روز|چندم|چند\s*شنبه|هفته\s*چند|week\s*number|what\s*day|today'?s\s*date|what\s*date/i.test(t);
};

const formatDateReply = (userText, lang = "fa") => {
  const t = (userText || "").trim();
  const now = new Date();
  let offset = 0;
  if (/پریروز|پریرورز/i.test(t)) offset = -2;
  else if (/دیروز|yesterday/i.test(t)) offset = -1;
  else if (/پس\s*فردا|day\s*after\s*tomorrow/i.test(t)) offset = 2;
  else if (/فردا|tomorrow/i.test(t)) offset = 1;
  // else امروز / today / تاریخ
  const d = new Date(now);
  d.setDate(d.getDate() + offset);
  const weekdayFa = ["یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه"][d.getDay()];
  const weekdayEn = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][d.getDay()];
  const toEn = (s) => String(s).replace(/[۰-۹]/g, (x) => "۰۱۲۳۴۵۶۷۸۹".indexOf(x));
  const pParts = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { year: "numeric", month: "long", day: "numeric" }).formatToParts(d);
  const pDay = toEn(pParts.find((x) => x.type === "day")?.value || "");
  const pMonth = pParts.find((x) => x.type === "month")?.value || "";
  const pYear = toEn(pParts.find((x) => x.type === "year")?.value || "");
  const gY = d.getFullYear();
  const gM = String(d.getMonth() + 1).padStart(2, "0");
  const gD = String(d.getDate()).padStart(2, "0");
  // ISO week number (هفته میلادی، دوشنبه‌محور استاندارد ISO-8601)
  const tmp = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = tmp.getUTCDay() || 7;
  tmp.setUTCDate(tmp.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(tmp.getUTCFullYear(), 0, 1));
  const isoWeek = Math.ceil((((tmp - yearStart) / 86400000) + 1) / 7);
  const labelFa = offset === 0 ? "امروز" : offset === 1 ? "فردا" : offset === -1 ? "دیروز" : offset === 2 ? "پس‌فردا" : offset === -2 ? "پریروز" : "تاریخ";
  const labelEn = offset === 0 ? "Today" : offset === 1 ? "Tomorrow" : offset === -1 ? "Yesterday" : offset === 2 ? "Day after tomorrow" : offset === -2 ? "Day before yesterday" : "Date";
  if (lang === "en") {
    return `📅 ${labelEn}: ${weekdayEn}, ${gY}-${gM}-${gD} (Gregorian)\\nPersian calendar: ${pDay} ${pMonth} ${pYear}\\nISO week number: ${isoWeek}`;
  }
  return `📅 ${labelFa}: ${weekdayFa}\\nشمسی: ${pDay} ${pMonth} ${pYear}\\nمیلادی: ${gY}/${gM}/${gD}\\nشماره هفته میلادی (ISO): ${isoWeek}`;
};

const isWeatherQuery = (text) => /هوا|آب.?و.?هوا|دما|رطوبت|weather|temperature/i.test(text);

// === منابع وب (پنل مدیریت → تب «منابع وب») — ۱۶ اوت ۲۰۲۶ ===
// ادمین یه URL دلخواه (مثلاً سایت نرخ ارز) به‌همراه یه لیبل و چندتا کلیدواژه‌ی جداشده با
// ویرگول ثبت می‌کنه. اگه سوال کاربر با کلیدواژه‌های یکی از منابع مچ شد، محتوای بلادرنگ (یا
// کش چند دقیقه‌ای، برای این‌که فشار زیادی به سایت مقصد وارد نشه) همون صفحه به AI داده می‌شه
// تا دقیقاً از روی متن واقعی جواب بده — منبع دقیق (لیبل + URL) و ساعت دریافت هم همیشه (بدون
// وابستگی به این‌که AI خودش یادش بمونه) زیر جواب اضافه می‌شه.
const WEB_SOURCE_CACHE_MS = 10 * 60 * 1000; // ۱۰ دقیقه — طبق تصمیم کاربر: «بلادرنگ با کش کوتاه»
// مچ کلمه‌به‌کلمه (نه substring خام) — بدون این، کلیدواژه‌ی دو-سه‌حرفیِ رایج مثل «ای» یا «را»
// می‌تونست وسط کلمه‌های کاملاً نامرتبط (مثلاً «ای» داخل «برای») هم پیدا بشه و باعث match اشتباه بشه
const wordBoundaryIncludes = (haystackNorm, needleNorm) => {
  const esc = needleNorm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  try {
    return new RegExp(`(^|[^\\p{L}\\p{N}])${esc}([^\\p{L}\\p{N}]|$)`, "u").test(` ${haystackNorm} `);
  } catch {
    return (` ${haystackNorm} `).includes(` ${needleNorm} `); // fallback برای مرورگرهای خیلی قدیمی بدون پشتیبانی \p{}
  }
};

// ۱۸ اوت ۲۰۲۶: وقتی یه کلیدواژه‌ی چندکلمه‌ای (مثلاً «طلای آب شده») به تک‌تک کلمات شکسته می‌شه
// (پایین‌تر توضیح داده شده چرا لازمه)، کلمه‌های خیلی رایج/کمکی فارسی («شده»، «است»، «را»، ...)
// نباید خودشون به‌تنهایی یه کلیدواژه‌ی معتبر بشن — وگرنه هر جمله‌ی کاملاً نامرتبطی که تصادفاً
// شامل «شده» باشه (مثل «ویندوزم کند شده») اشتباهی مچ می‌خوره. عبارت کامل («طلای آب شده») همچنان
// به‌طور کامل یه کلیدواژه‌ی معتبره؛ فقط تک‌کلمه‌های داخلش که توی این لیستن فیلتر می‌شن.
const WEB_SOURCE_STOPWORDS = new Set([
  "شده", "است", "بود", "را", "به", "در", "از", "با", "برای", "تا", "که", "این", "آن", "و", "یا",
  "هم", "هر", "یک", "دو", "چه", "چی", "می", "نمی", "اگر", "تو", "من", "ما", "شما", "او", "بر",
  "روی", "زیر", "بین", "پس", "قبل", "بعد", "چون", "اما", "ولی", "نیز", "دیگر", "خود",
]);

const matchWebSource = (userText, sources) => {
  if (!sources || sources.length === 0) return [];
  const userNorm = normalizeText(userText);
  const candidates = [];
  for (const src of sources) {
    // کلیدواژه‌ها ممکنه ادمین با ویرگول جدا کرده باشه («دلار، یورو») یا فقط با فاصله («دلار یورو») —
    // هر دو حالت رو پشتیبانی می‌کنیم: هم عبارت کامل بین دو ویرگول رو یه کلیدواژه حساب می‌کنیم، هم
    // تک‌تک کلمات داخلش رو. بدون این، یه رشته‌ی طولانیِ بدون ویرگول («دلار ارز حواله طلا سکه...»)
    // هیچ‌وقت داخل یه سوال کوتاه («دلار») پیدا نمی‌شد و match شکست می‌خورد.
    const parts = (src.keywords || "").split(/[،,]+/).map(k => k.trim()).filter(Boolean);
    const terms = new Set();
    for (const part of parts) {
      const norm = normalizeText(part);
      if (norm.length >= 2) terms.add(norm);
      for (const w of norm.split(/\s+/)) { if (w.length >= 2 && !WEB_SOURCE_STOPWORDS.has(w)) terms.add(w); }
    }
    let score = 0;
    for (const term of terms) { if (wordBoundaryIncludes(userNorm, term)) score++; }
    if (score > 0) candidates.push({ src, score });
  }
  if (candidates.length === 0) return [];
  // وقتی چندتا منبع هم‌زمان با یه سوال مچ می‌شن (مثلاً هم Navasan هم tgju.org روی «دلار»)، اولویت
  // (عدد کوچیک‌تر = مهم‌تر، پیش‌فرض ۰) تعیین‌کننده‌ی اصلیه. در اولویت برابر، Navasan برای
  // سوالات قیمتی (طلا/دلار/سکه/رمزارز) ترجیح داده می‌شه چون API ساختاریافته و واحد مشخص داره.
  // Navasan را ترجیح بده برای ارز/رمزارز، یا وقتی سوال ترکیبی فلز+ارز است
  // (چون فقط Navasan همه را یکجا و structured دارد). سکه/نقره خالص از اولویت پنل می‌آید.
  const hasFxCrypto = /دلار|تتر|یورو|پوند|درهم|بیت\s*کوین|بیتکوین|bitcoin|btc|اتریوم|رمزارز/i.test(userText);
  const hasMetal = /طلا(?!یی)|سکه|نقره|مثقال/i.test(userText);
  const isScrapQ = /ضایعات|قراضه|آهن\s*قراضه|iron\s*scrap/i.test(userText);
  const preferNavasan = hasFxCrypto && !isScrapQ; // ضایعات هرگز به Navasan نرود
  const scrapBoost = (src) => {
    const blob = ((src.url || "") + " " + (src.label || "") + " " + (src.keywords || "")).toLowerCase();
    if (/iranzayeat|ضایعات/.test(blob)) return 2;
    if (/tgju.*silver|silver_999|نقره/.test(blob) && isScrapQ) return -5;
    if (/navasan/.test(blob) && isScrapQ) return -3;
    return 0;
  };
  candidates.sort((a, b) => {
    // برای ضایعات: iranzayeat اول، منابع نقره/navasan آخر
    if (isScrapQ) {
      const ba = scrapBoost(a.src), bb = scrapBoost(b.src);
      if (ba !== bb) return bb - ba;
    }
    const pa = a.src.priority ?? 0, pb = b.src.priority ?? 0;
    if (pa !== pb) return pa - pb;
    if (preferNavasan) {
      const aNav = (a.src.url || "").includes("navasan.tech") ? 1 : 0;
      const bNav = (b.src.url || "").includes("navasan.tech") ? 1 : 0;
      if (aNav !== bNav) return bNav - aNav;
    }
    return b.score - a.score;
  });
  // ضایعات: منابع نامرتبط نقره را حذف کن تا به tgju/silver نرود
  if (isScrapQ) {
    const filtered = candidates.filter((c) => scrapBoost(c.src) >= 0);
    if (filtered.length) {
      // replace candidates list content
      candidates.length = 0;
      candidates.push(...filtered);
    }
  }
  // ۲۲/۲۳ اوت ۲۰۲۶: کل لیست مرتب‌شده برمی‌گرده (نه فقط بهترین یکی) — تا اگه بهترین منبع
  // (اولویت ۰) فچ/جوابش شکست خورد یا AI گفت «پیدا نشد»، فراخوان بتونه سریع بره سراغ اولویت
  // بعدی، به‌جای نشون‌دادن جواب ناقص یا خطا.
  return candidates.map(c => c.src);
};
const isWebSourceStale = (src) => {
  // منابع Navasan همیشه بلادرنگ فچ می‌شن، نه از کش: چون بعضی درخواست‌ها فقط یه آیتم خاص (مثلاً
  // فقط دلار) رو از API می‌گیرن نه کل لیست، کشِ عمومیِ این منبع نمی‌تونه تضمین کنه دقیقاً همون
  // آیتمی که سوال فعلی می‌خواد توش هست — پس برای این دامنه کش رو کلاً دور می‌زنیم. درخواست تک‌آیتمی
  // خیلی سبکه، مشکلی برای سهمیه‌ی API ایجاد نمی‌کنه.
  if ((src.url || "").includes("navasan.tech")) return true;
  if (!src.last_fetched_at) return true;
  return Date.now() - new Date(src.last_fetched_at).getTime() > WEB_SOURCE_CACHE_MS;
};
// ۲۳ اوت ۲۰۲۶: وقتی AI موفق جواب می‌ده ولی خودِ جواب می‌گه «پیدا نشد» (چون این منبع خاص اون
// آیتم رو نداشت)، این باید مثل شکست حساب بشه و به منبع بعدی (اولویت پایین‌تر) سقوط کنه — نه
// این‌که به‌عنوان جواب نهایی نشون داده بشه. عبارت‌ها دقیقاً همونایی‌ان که توی wsSystemPrompt به
// AI گفتیم موقع نبودِ اطلاعات استفاده کنه.

// وقتی AI می‌گوید «پیدا نشد» ولی متن صفحه عدد/ردیف مرتبط دارد (مثلاً ضایعات)، همان خطوط را نشان بده
const extractRelevantPriceLines = (content, query) => {
  if (!content) return [];
  const q = query || "";
  const isScrap = /ضایعات|قراضه|آهن\s*قراضه/i.test(q);
  const qWords = normalizeText(q)
    .split(/\s+/)
    .filter((w) => w.length >= 2 && !WEB_SOURCE_STOPWORDS.has(w));
  const lines = String(content).split(/\n/).map((l) => l.trim()).filter((l) => l.length >= 4);
  const scored = [];
  for (const ln of lines) {
    if (!/\d{2,}/.test(ln.replace(/[,،]/g, ""))) continue;
    const n = normalizeText(ln);
    let score = 0;
    for (const w of qWords) {
      if (n.includes(w) || wordBoundaryIncludes(n, w)) score += 2;
    }
    // ضایعات: ردیف‌های آهن/کیلو/تومان/درجه حتی بدون کلمهٔ «ضایعات» در همان خط
    if (isScrap) {
      if (/آهن|ضایعات|قراضه|کیلو|تومان|درجه|سوپر|ویژه|عمده|بار/.test(n)) score += 3;
      if (/تومان|ریال|کیلو/.test(n) && /\d/.test(ln)) score += 1;
    }
    if (score > 0) scored.push({ score, ln: ln.slice(0, 220) });
  }
  scored.sort((a, b) => b.score - a.score || a.ln.length - b.ln.length);
  const out = [];
  const seen = new Set();
  for (const { ln } of scored) {
    const k = normalizeText(ln).slice(0, 80);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(ln);
    if (out.length >= 15) break;
  }
  return out;
};

const formatScrapReply = (lines, src, fetchedAt) => {
  const body = lines.length
    ? ("قیمت ضایعات آهن (از صفحه):\n" + lines.map((l) => "- " + l).join("\n"))
    : "";
  const foot = "\n\n—\nمنبع: " + (src.label || src.url) + (src.url ? " (" + src.url + ")" : "") + "\nساعت دریافت اطلاعات: " + formatFetchTime(fetchedAt);
  return body + foot;
};

const looksLikeWebSourceNotFound = (replyText) =>
  /پیدا نشد|مشخص نشد|موجود نیست|ذکر نشده|در دسترس نیست|توی این صفحه نیست|نداره|نیامده|نیومده/i.test(replyText || "");
// عدد طلای ۱۸ عیار گرمی در بازار ایران الان چند میلیون تومان است؛ اگر AI عددی زیر ۱ میلیون داد، اشتباه است
const looksLikeSuspiciousGoldPrice = (replyText, userQ) => {
  if (!/طلا(?!یی)|عیار|گرم/i.test(userQ || "") || /سکه|نقره/i.test(userQ || "")) return false;
  const nums = (replyText || "").replace(/,/g, "").match(/\d{4,}/g) || [];
  if (nums.length === 0) return false;
  const main = Math.max(...nums.map(n => parseInt(n, 10)));
  return main > 0 && main < 1_000_000; // کمتر از ۱ میلیون برای گرم ۱۸ عیار غیرواقعی است
};
const formatFetchTime = (iso) => {
  if (!iso) return "نامشخص";
  try { return new Date(iso).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" }); }
  catch { return "نامشخص"; }
};

// === اکتیوسازی ویندوز/آفیس — تشخیص سوال و پاسخ قطعی با KMS مشروع شرکت (بدون AI، بدون دانلود فایل) ===
const isActivationQuery = (text) =>
  /(ویندوز|آفیس|windows|office)[\s\S]{0,15}(اکتیو|فعال)|(اکتیو|فعال)[\s\S]{0,15}(ویندوز|آفیس|windows|office)|\bactivation\b/i.test(text);
const ACTIVATION_NETWORK_QUESTION = "آیا الان به شبکه داخلی شرکت (LAN یا VPN) وصل هستید؟";
const isYesReply = (text) => /^\s*(بله|بلی|آره|اره|بعله|yes|y)\b/i.test(text.trim());
const ACTIVATION_INTERNAL_ANSWER =
  "✅ چون به شبکه داخلی شرکت وصل هستید، از سرور KMS داخلی شرکت استفاده کنید (بدون نیاز به دانلود هیچ فایلی):\n\n" +
  "🔹 اکتیو کردن ویندوز:\nCMD رو با Run as Administrator باز کنید و این دستورات رو بزنید:\nslmgr /skms kms.danonemulti.net\nslmgr /ato\n\nبرای بررسی وضعیت لایسنس: slmgr /dli\n\n" +
  "🔹 اکتیو کردن Office:\nبه پوشه نصب آفیس برید (مثلاً Office16 برای نسخه 2016/2019 — مسیر: C:\\Program Files\\Microsoft Office\\Office16) و این دستورات رو بزنید:\ncscript ospp.vbs /sethst:kms.danonemulti.net\ncscript ospp.vbs /act\n\n" +
  "⚠️ همه‌ی دستورات باید توی CMD با دسترسی Administrator اجرا بشن.";

const extractCity = (text) => {
  for (const c of IRAN_CITIES) {
    if (text.includes(c)) return c;
  }
  const match = text.match(/(?:هوای|دمای|آب.?و.?هوای|weather (?:in|of)|temperature (?:in|of))\s+([^\s؟?.,!،]+(?:\s+[^\s؟?.,!،]+)?)/i);
  if (!match) return null;
  const candidate = match[1].trim();
  // اگه استخراج به‌جای اسم شهر یه عبارت پرسشی بود (مثل دکمه‌ی سریع «هوای کدوم شهرو میخوای؟»)، شهر واقعی نیست —
  // برگردون null تا اصلاً درخواستی به API آب‌وهوا نره و مستقیم بره سراغ Q&A/AI (سریع‌تر و بدون تلاش بی‌فایده)
  if (/کدوم|کدام|چه شهر|کجا|میخوای|می‌خوای|؟/.test(candidate)) return null;
  return candidate;
};

const WEATHER_ICONS = { "01d": "☀️", "01n": "🌙", "02d": "🌤️", "02n": "☁️", "03d": "☁️", "03n": "☁️", "04d": "☁️", "04n": "☁️", "09d": "🌧️", "09n": "🌧️", "10d": "🌦️", "10n": "🌧️", "11d": "⛈️", "11n": "⛈️", "13d": "❄️", "13n": "❄️", "50d": "🌫️", "50n": "🌫️" };

const formatWeatherReply = (data) => {
  const emoji = WEATHER_ICONS[data.icon] || "🌡️";
  let observedLine = "";
  if (data.observed_at_unix) {
    try {
      // ترفند: timestamp رو با آفست منطقه زمانی همون شهر جمع می‌زنیم و بعد با timeZone:"UTC" فرمت می‌کنیم
      // تا ساعت محلی شهر مقصد نمایش داده بشه، نه ساعت مرورگر کاربر
      const localMs = (data.observed_at_unix + (data.timezone_offset_sec || 0)) * 1000;
      const utcDate = new Date(localMs);
      const formatted = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
        year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC"
      }).format(utcDate);
      observedLine = `\n\n🕒 داده مربوط به: ${formatted} (به وقت محلی ${data.city})`;
    } catch { /* اگه فرمت تاریخ خطا داد، بی‌خیال نمایش ساعت میشیم ولی بقیه اطلاعات نمایش داده میشه */ }
  }

  let forecastBlock = "";
  if (Array.isArray(data.forecast) && data.forecast.length > 0) {
    const tzOffset = data.forecast_timezone_offset_sec || 0;
    const lines = data.forecast.map(d => {
      const dEmoji = WEATHER_ICONS[d.icon] || "🌡️";
      let weekday = "";
      try {
        const localMs = (d.date_unix + tzOffset) * 1000;
        weekday = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { weekday: "long", timeZone: "UTC" }).format(new Date(localMs));
      } catch { weekday = ""; }
      return `${dEmoji} ${weekday}: ${d.min}° تا ${d.max}°C — ${d.description}`;
    });
    forecastBlock = `\n\n📅 پیش‌بینی ۳ روز آینده:\n${lines.join("\n")}`;
  }

  return `${emoji} آب و هوای ${data.city}:\n\n🌡️ دما: ${data.temp}°C (احساس واقعی: ${data.feels_like}°C)\n☁️ وضعیت: ${data.description}\n💧 رطوبت: ${data.humidity}%\n💨 سرعت باد: ${data.wind_kmh} km/h${observedLine}${forecastBlock}\n\n📡 منبع: OpenWeatherMap`;
};

// ADMIN_PASSWORD moved to backend for security
const SUPABASE_URL = "https://lphczmltctrqmkxktdzo.supabase.co";
const SUPABASE_KEY = "sb_publishable_4zAcw2YmjJkFnpgZI-ZzLQ_EXznYJs_";

const sbHeaders = {
  "Content-Type": "application/json",
  "apikey": SUPABASE_KEY,
  "Authorization": `Bearer ${SUPABASE_KEY}`,
  "Prefer": "return=representation"
};

const sbFetch = async (path, options = {}) => {
  const res = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    ...options,
    headers: {
      ...sbHeaders,
      ...(options.headers || {}),
      // برای DELETE باید Prefer header باشه
      ...(options.method === "DELETE" ? { "Prefer": "return=representation" } : {})
    }
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Supabase error: ${res.status} — ${errText}`);
  }
  const text = await res.text();
  return text ? JSON.parse(text) : [];
};

const BASE_KNOWLEDGE = `تو دستیار هوش مصنوعی واحد IT شرکت Nutricia-MMP هستی که برای پشتیبانی کارکنان طراحی شده‌ای. به تمام سوالات مرتبط با IT، نرم‌افزار، سخت‌افزار، شبکه، برنامه‌نویسی و فناوری جواب بده — حتی اگه نرم‌افزار خاص شرکت نباشه.

قانون ۱ — زبان: به زبان سوال جواب بده. فارسی→فارسی، انگلیسی→انگلیسی. هیچ‌وقت از هیچ زبان یا خط دیگه‌ای استفاده نکن — نه چینی، نه ژاپنی، نه کره‌ای، نه هندی، نه ویتنامی، نه عربی، نه اسپانیایی، نه فرانسوی، نه هیچ زبان دیگه‌ای غیر از فارسی و انگلیسی. حتی یک کلمه یا حرف از این زبان‌ها (مثل «أ»، «ة»، یا کلمات اسپانیایی/عربی وسط جمله فارسی) قابل‌قبول نیست.

قانون ۱.۱ — فرمت: این چت فقط متن ساده نمایش می‌ده، Markdown رندر نمی‌شه. هرگز از ** برای بولد، # برای هدر، یا نشانه‌های Markdown دیگه استفاده نکن — در غیر این صورت همون کاراکترهای خام (**، #) توی پیام نمایش داده میشن. برای تاکید از emoji یا خط جدید استفاده کن. اگه از سندی داده‌ای مثل *** (به معنی خالی/ثبت‌نشده) دیدی، توی جوابت به‌جاش بنویس «ثبت نشده» یا «موردی ندارد».

قانون ۲ — حوزه تخصصی: حوزه تو بسیار گسترده‌ست — هر چیزی مرتبط با فناوری، نرم‌افزار، سخت‌افزار، شبکه، هوش مصنوعی (AI، LLM، Claude، ChatGPT، Gemini، Groq، MCP، API هوش مصنوعی، مدل‌های زبانی، prompt، agent)، برنامه‌نویسی، سیستم‌های سازمانی (راهکاران، ERP، CRM)، ابزارهای کاری و دیجیتال رو جواب بده. هوش مصنوعی و ابزارهای AI بخش مهمی از IT هستن و باید کامل توضیح بدی. اگه سوال صددرصد غیرفناوری بود (مثلاً پزشکی/سلامت/تغذیه مثل «سرما خوردم چیکار کنم»، آشپزی، ورزش، روانشناسی، حقوقی، مالی شخصی)، **باید مودبانه امتناع کنی، نه این‌که جواب واقعی بدی** — حتی اگه جواب رو بلدی و سوال بی‌ضرر به‌نظر می‌رسه. برای این حالت **دقیقاً و عیناً** این جمله رو (بدون تغییر، بدون اضافه کردن جواب واقعی قبل یا بعدش) به همون زبان سوال کاربر بده: «این موضوع در حوزه پشتیبانی IT نیست، متاسفانه نمی‌تونم کمکتون کنم.» — این جمله‌ی دقیق برای گزارش‌گیری آماری استفاده میشه، پس عبارت‌های مشابه یا بازنویسی‌شده قبول نیست.

قانون ۲.۰.۱ — اخبار روز: اگر کاربر اخبار / خبر روز / تیتر سیاسی اقتصادی ورزشی یا کریپتو خواست، این موضوع مجاز است و نباید با جملهٔ امتناع حوزه IT جواب بدهی؛ سیستم جداگانه از سرویس اخبار استفاده می‌کند.
قانون ۲.۱ — استثنای اسناد آپلودشده: اگه بخش «اسناد آموزشی مرتبط» یا «سوال و جواب‌های اختصاصی شرکت» توی این پرامپت محتوایی داشت که به سوال کاربر مرتبط بود (مثلاً منوی غذای کانتین، لیست تلفن داخلی، اطلاعیه‌های داخلی، فرم‌های اداری)، حتماً و بدون هیچ قید و شرطی از همون اطلاعات جواب بده — حتی اگه موضوعش IT نباشه. قانون ۲ فقط برای سوالاتی هست که هیچ سندی درباره‌شون آپلود نشده؛ وقتی سند مرتبط پیدا شد، محدودیت حوزه IT اعمال نمیشه چون خود واحد IT/HR شرکت این اطلاعات رو برای پاسخ‌گویی به کارکنان توی سیستم گذاشته.

قانون ۲.۱.۱ — بازتولید عیناً، نه بازنویسی: وقتی از یه سند/Q&A مرتبط جواب می‌دی، هر لینک، آدرس دانلود، دستور، شماره یا مقدار دقیق که توی اون سند اومده رو دقیقاً همون‌جوری که نوشته شده کپی کن — هرگز خودت لینک/دستور/سرور مشابه نساز یا حدس نزن، حتی اگه فکر می‌کنی می‌دونی جواب چیه (مثلاً برای اکتیوسازی ویندوز/آفیس با KMS، دستورات عمومی slmgr از خودت ننویس؛ اگه سند یه لینک دانلود فایل داده، همون لینک دقیق رو بده، نه یه دستورالعمل عمومی جایگزین). اگه چندین راه‌حل مرتبط توی اسناد بود (مثلاً یکی برای وضعیت متصل‌به‌شبکه و یکی برای غیرمتصل)، بر اساس context مکالمه دقیقاً همونی که مصداق داره رو انتخاب و عیناً بازتولید کن. اگه اطلاعات موردنیاز کاربر توی اسناد مرتبط نبود، صریح بگو «در اسناد موجود پیدا نشد» و از دانش عمومی خودت جایگزین نساز.

قانون ۳ — پیوستگی مکالمه: همیشه تاریخچه مکالمه رو در نظر بگیر. اگر پیام کاربر کوتاه یا مبهم بود (مثل بله، نه، آره، نه، yes، no، ok، ممنون، باشه، وصلم)، معنی‌اش رو از پیام‌های قبلی بفهم و ادامه منطقی مکالمه رو بده. هرگز پیام کوتاه رو بدون توجه به context قبلی جواب نده.

قانون ۴ — احوال‌پرسی: اگر صرفاً احوال‌پرسی یا تشکر بود، مودبانه جواب بده و اعلام آمادگی برای سوالات IT کن.

قانون ۵ — آب و هوا: سیستم به‌صورت خودکار سوالات آب و هوای شهرهای مختلف رو با داده واقعی از OpenWeatherMap جواب می‌ده (این بخش قبل از رسیدن به تو انجام می‌شه). اگه پیامی به دستت رسید که درباره آب و هواست ولی نتونستی داده واقعی بهش بدی، از کاربر بخواه اسم شهر رو واضح‌تر یا با نام لاتین بنویسه.

قانون ۶ — تاریخ و روز جاری: پایین همین پرامپت، یه بخش با عنوان «اطلاعات تاریخ امروز» هست که دقیقاً تاریخ شمسی، روز هفته و هفته جاری ماه رو مشخص می‌کنه. برای هر سوالی که به روز/هفته/تاریخ نیاز داره (مثل منوی غذا، برنامه شیفت، جدول زمان‌بندی هفتگی)، همیشه از همون اطلاعات استفاده کن. هرگز خودت تاریخ یا روز هفته رو حدس نزن یا محاسبه نکن — چون مدل‌های زبانی معمولاً در محاسبات تقویمی اشتباه می‌کنن.

قانون ۷ — جستجوی نام در اسناد (مثل لیست تلفن): اگه کاربر فقط بخشی از یه اسم رو گفت (مثلاً فقط نام‌خانوادگی «رضایی» بدون نام کوچیک)، هرگز نگو «لطفاً نام کامل و دقیق بدید». به‌جاش توی سند دنبال همه‌ی ردیف‌هایی بگرد که اون بخش از اسم توشونه (partial match) و همه‌شون رو با شماره‌ی داخلی‌شون لیست کن تا کاربر خودش انتخاب کنه. فقط وقتی هیچ‌کدوم از اسم‌های توی سند شبیه چیزی که کاربر گفته نبودن، بگو پیدا نشد.

دامین شرکت danonemulti.net است. تمام کاربران عضو این دامین هستند.
جواب‌هایت باید واضح، گام به گام و عملی باشند.

=== تغییر پسورد در دامین danonemulti.net ===
- روش اول (داخل ویندوز): Ctrl+Alt+Delete > Change a password
- روش دوم: Settings > Accounts > Sign-in options > Password > Change
- پسورد دامین باید حداقل 8 کاراکتر، شامل حروف بزرگ، کوچک و عدد باشد
- پسورد هر 90 روز یک بار منقضی می‌شود
- اگر پسورد فراموش شده: با IT Support تماس بگیرید تا ادمین دامین ریست کند
- بعد از ریست، اولین لاگین باید پسورد تغییر کند

=== لاگین به دامین danonemulti.net ===
- فرمت یوزرنیم: firstname.lastname@danonemulti.net
- اگر اکانت قفل شده: با IT Support تماس بگیرید
- حداکثر 5 بار تلاش اشتباه = قفل شدن اکانت
- VPN: برای دسترسی از خارج از شبکه شرکت به VPN نیاز است

=== اکتیو کردن ویندوز با KMS داخلی شرکت ===
سرور KMS شرکت: kms.danonemulti.net
دستورات را در CMD به عنوان Administrator اجرا کنید:
slmgr /skms kms.danonemulti.net
slmgr /ato
برای بررسی وضعیت لایسنس: slmgr /dli

=== اکتیو کردن Office با KMS داخلی شرکت ===
Office 2010: cd "C:\\Program Files\\Microsoft Office\\Office14"
Office 2013: cd "C:\\Program Files\\Microsoft Office\\Office15"
Office 2016 و 2019: cd "C:\\Program Files\\Microsoft Office\\Office16"
بعد از رفتن به پوشه:
cscript ospp.vbs /sethst:kms.danonemulti.net
cscript ospp.vbs /act
نکته مهم: CMD را حتماً با Run as Administrator اجرا کنید

=== ویندوز 10 و 11 ===
- Task Manager: Ctrl+Shift+Esc
- آپدیت ویندوز: Settings > Windows Update
- مشکل اینترنت: ipconfig /release و ipconfig /renew در CMD
- اضافه کردن پرینتر: Settings > Bluetooth & devices > Printers & scanners
- Remote Desktop: Settings > System > Remote Desktop > Enable

=== Microsoft Office - Excel ===
- فریز کردن ردیف/ستون: View > Freeze Panes
- VLOOKUP: =VLOOKUP(مقدار, محدوده, شماره_ستون, FALSE)
- Pivot Table: Insert > PivotTable
- فیلتر کردن: Data > Filter
- Conditional Formatting: Home > Conditional Formatting

=== Microsoft Office - Word ===
- فهرست خودکار: References > Table of Contents
- Track Changes: Review > Track Changes
- شماره صفحه: Insert > Page Number
- پیدا کردن و جایگزینی: Ctrl+H

=== Microsoft Outlook ===
- تنظیم Out of Office: File > Automatic Replies
- Signature: File > Options > Mail > Signatures
- بازیابی ایمیل حذف شده: Deleted Items > Recover Deleted Items

=== Microsoft Teams ===
- تغییر Background: ... > Apply Background Effects
- ضبط جلسه: ... > Start Recording
- اشتراک صفحه: Share

=== مشکلات رایج شبکه ===
- IP نگرفتن: ipconfig /release > ipconfig /flushdns > ipconfig /renew
- DNS مشکل: تغییر DNS به 8.8.8.8
- Ping: ping 8.8.8.8 در CMD

=== درخواست‌های IT ===
برای ثبت درخواست IT به سیستم تیکتینگ شرکت به آدرس servicenow.danonemulti.net مراجعه کنید.
با اکانت دامین danonemulti.net لاگین کنید.
اطلاعات لازم: نام، شماره پرسنلی، توضیح مشکل و اولویت.
زمان پاسخگویی: مشکلات عادی 24-48 ساعت، اورژانسی همان روز.

همیشه مودب، صبور و حرفه‌ای باش.

=== ابزار اکتیواسیون KMS ===
اگر کاربر گفت ویندوز یا آفیسش اکتیو نیست: این حالت الان با کد (بدون AI) مدیریت می‌شه —
اول سوال شبکه‌ی داخلی پرسیده می‌شه، اگه جواب «بله» بود، دستورات slmgr مستقیم نشون داده می‌شه.
اگه به این متن رسیدی، یعنی یا کاربر بعد از سوال شبکه چیزی غیر از «بله»/«خیر» واضح گفته، یا
حالت «خیر» (خارج از شبکه‌ی داخلی) بوده. در این حالت هرگز لینک دانلود فایل .cmd یا دستور
Run as Administrator نده (این عمداً از این پرامپت حذف شده و هرگز نباید برگرده) — فقط با
احترام بگو برای اکتیوسازی از بیرون شبکه‌ی داخلی باید با واحد IT (servicenow.danonemulti.net)
تیکت بزنه تا به‌صورت remote اکتیوش کنن.`;

// === فرمت تاریخ شمسی برای یک timestamp دلخواه (نه فقط امروز) — برای نمایش تاریخ اطلاعیه‌ها ===
const formatPersianDate = (dateInput) => {
  try {
    const d = new Date(dateInput);
    if (isNaN(d.getTime())) return "";
    const monthNamesFa = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
    const parts = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { year: "numeric", month: "numeric", day: "numeric" }).formatToParts(d);
    const get = (type) => parts.find(p => p.type === type)?.value || "";
    const toEnDigits = (s) => s.replace(/[۰-۹]/g, ch => "۰۱۲۳۴۵۶۷۸۹".indexOf(ch));
    const y = parseInt(toEnDigits(get("year")), 10);
    const m = parseInt(toEnDigits(get("month")), 10);
    const day = parseInt(toEnDigits(get("day")), 10);
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${day} ${monthNamesFa[m - 1]} ${y} — ساعت ${hh}:${mm}`;
  } catch { return ""; }
};

// === تاریخ و روز جاری — محاسبه دقیق شمسی + هفته چرخشی ۴تایی شنبه‌محور (پیوسته بین ماه‌ها) ===
// هفته‌ها از شنبه شروع می‌شن و سیکل ۴ هفته‌ای ماه‌به‌ماه ریست نمی‌شه
// (باگ قبلی: در مرز ماه مثل ۳۱ مرداد→۱ شهریور، هفته از نو «اول» می‌شد و سیکل منوی غذا می‌پرید)
const getContinuousWeekNumber = (date) => {
  // شنبه شروع‌کننده همین هفته
  const weekStart = new Date(date);
  weekStart.setHours(12, 0, 0, 0);
  const daysBackToSat = (weekStart.getDay() + 1) % 7; // Sun=1 … Sat=0
  weekStart.setDate(weekStart.getDate() - daysBackToSat);
  // مرجع ثابت: یک شنبه شناخته‌شده (۶ ژانویه ۲۰۲۴ = شنبه)
  const epoch = new Date(Date.UTC(2024, 0, 6, 12, 0, 0));
  const days = Math.round((weekStart.getTime() - epoch.getTime()) / 86400000);
  return ((Math.floor(days / 7) % 4) + 4) % 4 + 1; // ۱..۴
};

const getPersianDateContext = () => {
  try {
    const now = new Date();
    const weekdayNamesFa = ["یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه"];
    const todayWeekdayFa = weekdayNamesFa[now.getDay()];

    const parts = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { year: "numeric", month: "numeric", day: "numeric" }).formatToParts(now);
    const get = (type) => parts.find(p => p.type === type)?.value || "";
    const toEnDigits = (s) => s.replace(/[۰-۹]/g, d => "۰۱۲۳۴۵۶۷۸۹".indexOf(d));
    const pYear = parseInt(toEnDigits(get("year")), 10);
    const pMonth = parseInt(toEnDigits(get("month")), 10);
    const pDay = parseInt(toEnDigits(get("day")), 10);
    const monthNamesFa = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
    const weekNamesFa = ["اول", "دوم", "سوم", "چهارم"];

    const weekNumber = getContinuousWeekNumber(now);

    // جدول کامل روز به روز همین ماه شمسی — هفته‌ها با سیکل پیوسته ۴تایی
    const firstOfMonth = new Date(now);
    firstOfMonth.setDate(now.getDate() - (pDay - 1));
    const cursor = new Date(firstOfMonth);
    const monthTableRows = [];
    let d = 1;
    while (d <= 31) {
      const partsD = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { day: "numeric" }).formatToParts(cursor);
      const dayNum = parseInt(toEnDigits(partsD.find(p => p.type === "day").value), 10);
      if (dayNum !== d) break; // یعنی ماه عوض شده
      const wn = getContinuousWeekNumber(cursor);
      const marker = d === pDay ? "  ← امروز" : "";
      monthTableRows.push(`روز ${d} ${monthNamesFa[pMonth - 1]} = ${weekdayNamesFa[cursor.getDay()]}، هفته ${weekNamesFa[wn - 1]}${marker}`);
      cursor.setDate(cursor.getDate() + 1);
      d++;
    }
    const monthTableText = monthTableRows.join("\n");

    return `امروز ${todayWeekdayFa}، ${pDay} ${monthNamesFa[pMonth - 1]} ${pYear} است (روز ${pDay} ماه). بر اساس تقویم هفتگی شرکت که هفته‌ها از شنبه شروع می‌شن و سیکل ۴ هفته‌ای بین ماه‌ها پیوسته است، امروز جزو «هفته ${weekNamesFa[weekNumber - 1]}» محسوب میشه.

جدول مرجع روزهای ${monthNamesFa[pMonth - 1]} ${pYear} — یک خط برای هر روز:
${monthTableText}

قانون سخت‌گیرانه: برای هر سوالی که به روز هفته، هفته جاری ماه، یا هر تاریخ خاصی از همین ماه نیاز داره (مثلاً «۲۰ مرداد چه روزیه؟» یا «غذای فلان تاریخ چیه»)، خط دقیق همون روز رو توی جدول بالا پیدا کن و فقط از همون خط استفاده کن. هرگز حدس نزن، هرگز خودت محاسبه نکن، و هرگز روز/هفته رو با شمردن سرانگشتی از جدول تخمین نزن — دقیقاً خط «روز X ${monthNamesFa[pMonth - 1]}» رو که کاربر پرسیده پیدا کن.`;
  } catch {
    return "";
  }
};

// === انتخاب شیت مرتبط از سندهای چندشیتی (مثل آرشیو چندماهه/چندساله منوی غذا) ===
// چون سند می‌تونه خیلی بزرگ باشه، به‌جای بریدن از ابتدای متن (که شیت‌های قدیمی رو می‌ده)،
// نزدیک‌ترین شیت به ماه جاری شمسی رو پیدا و فقط همون رو به مدل می‌دیم
const PERSIAN_MONTH_PREFIXES = [
  ["فروردین", "فرور"], ["اردیبهشت", "ارد"], ["خرداد", "خرد"], ["تیر", "تیر"],
  ["مرداد", "مرد"], ["شهریور", "شهر"], ["مهر", "مهر"], ["آبان", "آبا"],
  ["آذر", "آذر"], ["دی", "دی"], ["بهمن", "بهم"], ["اسفند", "اسف"],
];

const getPersianTodayYM = () => {
  try {
    const now = new Date();
    const parts = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { year: "numeric", month: "numeric" }).formatToParts(now);
    const get = (type) => parts.find(p => p.type === type)?.value || "";
    const toEnDigits = (s) => s.replace(/[۰-۹]/g, d => "۰۱۲۳۴۵۶۷۸۹".indexOf(d));
    return { year: parseInt(toEnDigits(get("year")), 10), month: parseInt(toEnDigits(get("month")), 10) };
  } catch {
    return null;
  }
};

const pickRelevantSheet = (content) => {
  const sheetRegex = /=== شیت: ([^=]+?) ===\n([\s\S]*?)(?=\n=== شیت:|$)/g;
  const sheets = [];
  let m;
  while ((m = sheetRegex.exec(content)) !== null) {
    sheets.push({ title: m[1].trim(), body: m[2].trim() });
  }
  if (sheets.length <= 1) return null; // سند تک‌شیتی — نیازی به این منطق نیست

  const today = getPersianTodayYM();
  if (!today) return null;

  const scored = sheets.map(s => {
    let year = null, monthIdx = null;
    const yearMatch = s.title.match(/1[34]\d{2}/); // سال شمسی ۴ رقمی
    if (yearMatch) year = parseInt(yearMatch[0], 10);
    for (let i = 0; i < PERSIAN_MONTH_PREFIXES.length; i++) {
      if (s.title.includes(PERSIAN_MONTH_PREFIXES[i][1])) { monthIdx = i + 1; break; }
    }
    const key = (year && monthIdx) ? year * 12 + monthIdx : null;
    return { ...s, key };
  }).filter(s => s.key !== null);

  if (!scored.length) return null;
  const todayKey = today.year * 12 + today.month;

  // نزدیک‌ترین شیت به ماه جاری — در تساوی فاصله، ماه گذشته/جاری رو به ماه آینده ترجیح بده
  scored.sort((a, b) => {
    const da = Math.abs(a.key - todayKey) - (a.key <= todayKey ? 0.5 : 0);
    const db = Math.abs(b.key - todayKey) - (b.key <= todayKey ? 0.5 : 0);
    return da - db;
  });
  return scored[0];
};

// === جستجوی قطعی منوی غذا — بدون هوش مصنوعی، مستقیم با کد ===
// چون مدل‌های زبانی در محاسبه/تطبیق تاریخ قابل‌اعتماد نیستن، این بخش کاملاً با کد (نه AI) ردیف دقیق رو پیدا می‌کنه
// ۵ اوت ۲۰۲۶: قبلاً substring خام "منو" باعث می‌شد کلمه‌ی "ممنون" (تشکر) هم به‌اشتباه match بشه —
// چون "ممنون" = م+منو+ن، یعنی "منو" دقیقاً وسطش هست. (?<!م) یعنی "منو" نباید بلافاصله بعد از یه "م"
// دیگه بیاد — این دقیقاً همون تصادف حرفیِ "ممنون" رو رد می‌کنه، بدون این‌که به match های واقعی مثل
// "توی منو چی هست؟" آسیب بزنه.
const isMenuQuery = (text) => /غذا|ناهار|کانتین/i.test(text) || /(?<!م)منو/.test(text);

// تشخیص سوال اخبار — قبل از منابع وب تا «اخبار کریپتو» به Navasan نرود
const isNewsQuery = (text) =>
  /اخبار|خبر\s*روز|تیتر|headline|news/i.test(text) &&
  !/قیمت|چنده|چند\s*است|نرخ/i.test(text); // قیمت بیت‌کوین ≠ اخبار بیت‌کوین

const guessNewsCategory = (text) => {
  const t = (text || "").replace(/\u200c/g, " ");
  if (/کریپتو|ارز\s*دیجیتال|بیت\s*کوین|رمزارز|crypto|bitcoin/i.test(t)) return "crypto";
  if (/ورزش|فوتبال|لیگ|المپیک|sport/i.test(t)) return "sports";
  if (/اقتصاد|بورس|بازار|تورم|economic/i.test(t)) return "economic";
  if (/سیاس|سیاست|انتخاب|دولت|political/i.test(t)) return "political";
  return "general";
};

// === جستجوی قطعی لیست تلفن داخلی — بدون هوش مصنوعی ===
// مدل‌ها توی جستجوی partial/fuzzy داخل سندهای بزرگ قابل‌اعتماد نیستن (مثلاً "رضایی" رو پیدا نمی‌کنن مگه اسم کامل دقیق بدی)
// این تابع مستقیم توی متن سندها دنبال خط‌هایی می‌گرده که هم شبیه رکورد تلفن باشن (عدد ۳ تا ۵ رقمی داشته باشن) هم عبارت جستجو رو داشته باشن
const isPhoneQuery = (text) => /داخلی|شماره\s*تماس|شماره\s*تلفن|تلفن\s*داخلی/i.test(text);

const PHONE_QUERY_STOPWORDS = ["داخلی", "شماره", "تماس", "تلفن", "چنده", "چیه", "چیست", "هست", "است", "آقای", "خانم", "جناب", "سرکار", "لطفا", "لطفاً", "بگو", "بده"];

// ۱۳ اوت ۲۰۲۶: حذف stopword با regex ساده (substring) یه باگ واقعی داشت: کلمه‌ی توقف «را» به‌عنوان
// substring داخل کلمه‌های واقعی هم پیدا می‌شه — مثلاً «چنارانی» دقیقاً شامل «را» هست (چ-ن-ا-ر-ا-ن-ی،
// حروف ۴و۵ یعنی «را»)! نتیجه این بود که «چنارانی» به «چنا نی» خراب می‌شد. حالا اول نیم‌فاصله‌های
// نامرئی (که ممکنه ضمیر چسبیده مثل «داخلی‌ش» رو جدا کنن) به فاصله‌ی واقعی تبدیل می‌شن، بعد متن به
// کلمه تقسیم می‌شه و فقط کلمه‌هایی که دقیقاً (نه substring) با یه stopword یکی‌ان حذف می‌شن.
const stripStopwordsWholeWord = (text, stopwords) => {
  const stopSet = new Set(stopwords.map((w) => w.toLowerCase()));
  // بلندترین stopword ها اول، تا وقتی یه کلمه با چندتاشون هم‌زمان شروع می‌شه، طولانی‌ترین (دقیق‌ترین) رو بردارین
  const sortedStopwords = [...stopwords].sort((a, b) => b.length - a.length);
  const PRONOUN_SUFFIXES = new Set(["شون", "مون", "تون", "ش", "م", "ت", "ای", "ه"]);
  return text
    .replace(/[\u200c\u200d]/g, " ")
    .replace(/[؟?!.,]/g, " ")
    .split(/\s+/)
    .filter((w) => {
      if (!w) return false;
      const wLower = w.toLowerCase();
      if (stopSet.has(wLower)) return false;
      // «ایمیلش»، «داخلیمون»: stopword + ضمیر ملکی چسبیده بدون هیچ فاصله یا نیم‌فاصله‌ای
      const matchedStop = sortedStopwords.find((sw) => sw.length >= 3 && wLower.startsWith(sw.toLowerCase()));
      if (matchedStop) {
        const suffix = wLower.slice(matchedStop.length);
        if (PRONOUN_SUFFIXES.has(suffix)) return false;
      }
      return true;
    })
    .join(" ")
    .trim();
};

const extractPhoneSearchTerm = (text) => stripStopwordsWholeWord(text, PHONE_QUERY_STOPWORDS);

const isPhoneDirectoryDoc = (doc) => {
  const content = doc.content || "";
  const title = ((doc.title || "") + " " + (doc.category || ""));
  // همهٔ لیست‌های داخلی (تهران / مشهد / ...) — مارکر شیت یا عنوان سند
  if (/\(لیست تلفن\/داخلی\)/.test(content)) return true;
  if (/تلفن|داخلی|phone|directory|تهران|مشهد/i.test(title) && /\d{3,5}/.test(content)) return true;
  return false;
};

const lineMatchesPersonName = (line, termWords) => {
  const lineNorm = normalizeText(line);
  // ۱) تطبیق مستقیم فارسی/نرمال‌شده
  if (termWords.every((w) => lineNorm.includes(normalizeText(w)))) return true;
  // ۲) تطبیق اسکلت لاتین↔فارسی (برای AD و لیست‌های مخلوط)
  const tokens = line.match(/[A-Za-z\u0600-\u06FF]+/g) || [];
  if (!tokens.length) return false;
  return termWords.every((qw) =>
    tokens.some((tok) => wordsLikelyMatch(qw, tok) || normalizeText(tok).includes(normalizeText(qw)))
  );
};

const searchPhoneDirectory = (docs, term) => {
  if (!term || term.length < 2) return [];
  const termWords = normalizeText(term).split(/\s+/).filter((w) => w.length >= 2);
  if (termWords.length === 0) return [];
  const results = [];
  for (const doc of docs || []) {
    if (!isPhoneDirectoryDoc(doc)) continue;
    for (const line of (doc.content || "").split("\n")) {
      if (!/\d{3,5}/.test(line)) continue;
      if (!/داخلی|ext|tel|phone|—|-/i.test(line) && !/\(لیست تلفن/.test(doc.content || "")) {
        if (!/\(لیست تلفن\/داخلی\)/.test(doc.content || "")) continue;
      }
      if (lineMatchesPersonName(line, termWords)) {
        results.push(line.trim());
      }
    }
  }
  const uniq = [...new Set(results)];
  // حذف تکراری‌های تقریباً یکسان (همان داخلی)
  const byExt = new Map();
  for (const line of uniq) {
    const extM = line.match(/داخلی\s*:\s*(\d{3,5})/i) || line.match(/\b(\d{3,5})\b/);
    const ext = extM ? extM[1] : line;
    const prev = byExt.get(ext);
    if (!prev || line.length < prev.length) byExt.set(ext, line);
  }
  return [...byExt.values()];
};


// === جستجوی قطعی ایمیل/مشخصات کارمند (بدون AI) — ۱۳ اوت ۲۰۲۶ ===
// مشکل: کاربر معمولاً اسم رو فارسی تایپ می‌کنه («امید گوهری») ولی رکورد اکسل (خروجی AD) لاتینه
// («Omid Gohari») — چون دو الفبای متفاوتن، تطبیق رشته‌ای ساده (مثل searchPhoneDirectory) کار
// نمی‌کنه، و مدل‌های AI هم روی یه جدول بزرگ (که ممکنه توسط سقف کاراکتری بک‌اند هم قطع شده باشه)
// قابل‌اعتماد نیستن. راه‌حل: هر کلمه‌ی فارسی جستجو رو با یه نگاشت ساده به لاتین تبدیل می‌کنیم، بعد
// به‌جای تطبیق حرف‌به‌حرف دقیق (که به‌خاطر مصوت‌های نانوشته‌ی فارسی/عربی هیچ‌وقت قطعی نیست — مثلاً
// «امید» می‌تونه Omid یا Amid نوشته بشه)، «اسکلت بی‌صدا» (حذف مصوت‌ها) رو مقایسه می‌کنیم.
const FA_TO_LATIN_MAP = {
  "خ": "kh", "ش": "sh", "ژ": "zh", "چ": "ch", "غ": "gh", "ق": "gh",
  "ا": "a", "آ": "a", "ب": "b", "پ": "p", "ت": "t", "ث": "s", "ج": "j",
  "ح": "h", "د": "d", "ذ": "z", "ر": "r", "ز": "z", "س": "s", "ص": "s",
  "ض": "z", "ط": "t", "ظ": "z", "ع": "a", "ف": "f", "ک": "k", "گ": "g",
  "ل": "l", "م": "m", "ن": "n", "و": "o", "ه": "h", "ی": "i", "ئ": "i", "ء": "",
};
const transliterateFaToLatin = (text) => text.split("").map((ch) => (ch in FA_TO_LATIN_MAP ? FA_TO_LATIN_MAP[ch] : ch)).join("");
// ۱۳ اوت ۲۰۲۶: فارسی حرف دوبل رو یه بار می‌نویسه («حسین» یه «س» داره، ولی لاتینش «Hossein»
// دو تا «s» داره) — بدون یکی‌کردن حروف بی‌صدای پشت‌سرهم تکراری، اسکلت «حسین» (hsn) هیچ‌وقت با
// اسکلت واقعی «Hossein» (hssn) برابر نمی‌شد و کل ردیف (با اینکه بخش دوم اسمش «چنارانی» درست
// match می‌شد) به‌خاطر AND چندکلمه‌ای رد می‌شد. حالا حروف تکراری یکی می‌شن.
const consonantSkeleton = (word) => {
  const noVowels = word.toLowerCase().replace(/[^a-z]/g, "").replace(/[aeiou]/g, "");
  return noVowels.replace(/(.)\1+/g, "$1");
};

// یه کلمه‌ی جستجو (فارسی یا لاتین) رو با یه کلمه از رکورد (توکن لاتین توی سند) مقایسه می‌کنه.
// ۱۳ اوت ۲۰۲۶: قبلاً حداقل طول فقط روی qLower چک می‌شد، نه dLower — یعنی توکن‌های خیلی کوتاه
// (مثل «R»، «IT»، «CH» از سرنام‌های دپارتمان مثل «R&I»، «Finance – IT/IS») توی هر جستجویی که
// اون حروف رو داشت trivially match می‌شدن، و اسم یه نفر (مثلاً «chenarani») با ده‌ها نفر دیگه
// (که فقط یه دپارتمان مشترک داشتن) اشتباهی match می‌شد. حالا حداقل طول روی هر دو طرف چک می‌شه،
// و به‌جای startsWith (که مثلاً اسکلت کوتاه «Chain»=«chn» رو با اسکلت «Chenarani»=«chnrn» قاطی
// می‌کرد)، فقط تطابق دقیقِ اسکلت قبول می‌شه.
const wordsLikelyMatch = (queryWord, dataWord) => {
  const qLower = queryWord.toLowerCase();
  const dLower = dataWord.toLowerCase();
  if (qLower.length >= 3 && dLower.length >= 3 && dLower.includes(qLower)) return true;
  if (qLower.length >= 3 && dLower.length >= 4 && qLower.includes(dLower)) return true;
  const qLatin = transliterateFaToLatin(queryWord).toLowerCase().replace(/[^a-z]/g, "");
  const dLatin = dataWord.toLowerCase().replace(/[^a-z]/g, "");
  if (!qLatin || !dLatin) return false;
  // بعد از تبدیل فارسی→لاتین: برابری کامل (علی→ali ≈ Ali)
  if (qLatin.length >= 3 && qLatin === dLatin) return true;
  // تطبیق نزدیک لاتینی برای اسم‌های بلندتر
  if (qLatin.length >= 5 && dLatin.length >= 5) {
    if (qLatin === dLatin) return true;
    if (qLatin.length >= 6 && dLatin.length >= 6 && qLatin.slice(0, 6) === dLatin.slice(0, 6)) return true;
    // «طلایی»→tlaii در برابر talaei: اسکلت یکسان + طول نزدیک
    if (Math.abs(qLatin.length - dLatin.length) <= 2) {
      const qSkEarly = consonantSkeleton(qLatin);
      const dSkEarly = consonantSkeleton(dLatin);
      if (qSkEarly.length >= 2 && qSkEarly === dSkEarly) return true;
    }
  }
  const qSkeleton = consonantSkeleton(qLatin);
  const dSkeleton = consonantSkeleton(dLatin);
  if (qSkeleton.length < 2 || dSkeleton.length < 2) return false;
  // اسکلت ۲حرفی (طلایی→tl ≈ talaei→tl) فقط با طول لاتین نزدیک
  if (qSkeleton.length < 3 || dSkeleton.length < 3) {
    return qSkeleton === dSkeleton && qLatin.length >= 4 && dLatin.length >= 4
      && Math.abs(qLatin.length - dLatin.length) <= 2;
  }
  if (qSkeleton === dSkeleton) {
    if (Math.abs(qLatin.length - dLatin.length) > 3 && qLatin.length >= 6) return false;
    return true;
  }
  return false;
};

const isEmployeeLookupQuery = (text) =>
  /ایمیل|پست\s*الکترونیک|e-?mail/i.test(text) &&
  !/(فراموش|بازیابی|reset|forgot|عوض\s*کن|change).{0,15}(ایمیل|پسورد|پسوورد|رمز|password)/i.test(text);

const EMPLOYEE_QUERY_STOPWORDS = ["ایمیل", "پست", "الکترونیک", "آدرس", "چیه", "چیست", "کیه", "کجاست", "هست", "است", "بده", "رو", "را", "لطفا", "لطفاً", "آقای", "خانم", "جناب", "سرکار", "بگو", "مشخصات"];
const extractEmployeeSearchTerm = (text) => stripStopwordsWholeWord(text, EMPLOYEE_QUERY_STOPWORDS);

// ۱۳ اوت ۲۰۲۶: وقتی سوال ادامه‌ی سوال قبلیه و اسم رو تکرار نمی‌کنه («ایمیلش چیه؟»، «داخلی‌ش
// چنده؟»)، extractPhoneSearchTerm/extractEmployeeSearchTerm روی پیام فعلی هیچ اسمی گیرشون
// نمیاد (چون توی پیام فعلی اصلاً اسمی نیست، فقط ضمیر «ش» چسبیده به کلمه) — نتیجه‌ش این بود که
// جستجوی قطعی هیچ‌وقت match پیدا نمی‌کرد و کار می‌افتاد دست AI، که هم گاهی جواب اشتباه می‌ساخت
// (مثلاً «داخلی ثبت نشده» با اینکه واقعاً بود) هم گاهی دامنه‌ی ایمیل رو از خودش می‌ساخت
// (hallucination). این تابع اگه استخراج از پیام فعلی خالی بود، برمی‌گرده توی چند پیام قبلی
// مکالمه (حداکثر ۶ تا، کاربر یا دستیار) دنبال یه اسم می‌گرده — با همون تابع استخراج.
const GENERIC_NAME_STOPWORDS = [...new Set([...PHONE_QUERY_STOPWORDS, ...EMPLOYEE_QUERY_STOPWORDS])];
const extractGenericNameTerm = (text) => stripStopwordsWholeWord(text, GENERIC_NAME_STOPWORDS);

const resolveFollowupSearchTerm = (currentTerm, recentMessages) => {
  if (currentTerm && currentTerm.trim().length >= 2) return currentTerm;
  const history = (recentMessages || []).filter(m => m && m.role === "user").slice(-6);
  for (let i = history.length - 1; i >= 0; i--) {
    const candidate = extractGenericNameTerm(history[i].content || "");
    if (candidate && candidate.trim().length >= 2) return candidate;
  }
  return currentTerm;
};

const isEmployeeDirectoryDoc = (doc) => {
  const content = doc.content || "";
  const title = ((doc.title || "") + " " + (doc.category || ""));
  if (/\(جدول با هدر\)/.test(content)) return true;
  // فایل‌های AD/HR که مارکر نگرفته‌اند ولی ایمیل سازمانی دارند
  if (/@nutricia|@.*\.com/i.test(content) && /email|ایمیل|display\s*name|کارمند|پرسنل|AD|active\s*directory/i.test(title + content.slice(0, 500))) return true;
  if ((content.match(/@[a-z0-9.-]+\.[a-z]{2,}/gi) || []).length >= 5) return true;
  return false;
};

const emailLineMatchesPerson = (line, words) => {
  if (!line.includes("@")) return false;
  const significant = (words || []).map((w) => w.trim()).filter((w) => w.length >= 2);
  if (!significant.length) return false;

  const lineTokens = line.match(/[A-Za-z\u0600-\u06FF]+/g) || [];
  const localM = line.match(/([a-zA-Z0-9._-]+)@/);
  const localParts = localM
    ? localM[1].split(/[._-]+/).filter((p) => p.length >= 2)
    : [];
  const haystackTokens = [...lineTokens, ...localParts];

  const wordHitsHay = (qw) => {
    const qn = normalizeText(qw);
    if (qn.length >= 2 && normalizeText(line).includes(qn)) return true;
    return haystackTokens.some((tok) => wordsLikelyMatch(qw, tok));
  };

  // چندکلمه‌ای (نام + نام‌خانوادگی): همه باید بخورند — بدون fallback تک‌کلمه
  if (significant.length >= 2) {
    return significant.every(wordHitsHay);
  }

  // تک‌کلمه: فقط اگر توکن/local نسبتاً محکم مچ شود (نه اسکلت خیلی کوتاه)
  const qw = significant[0];
  const qSk = consonantSkeleton(transliterateFaToLatin(qw));
  if (qSk.length < 3 && qw.length < 4) return false;
  // تطبیق مستقیم در خط
  if (normalizeText(line).includes(normalizeText(qw))) return true;
  // local-part یا توکن با اسکلت برابر و طول کافی
  return haystackTokens.some((tok) => {
    if (wordsLikelyMatch(qw, tok)) {
      const dSk = consonantSkeleton(tok);
      // جلوگیری از احمدرضا ↔ حمیدرضا وقتی فقط اسکلت کوتاه مشترک است
      if (qSk.length >= 4 && dSk.length >= 4) {
        return qSk === dSk || normalizeText(tok).includes(normalizeText(transliterateFaToLatin(qw)));
      }
      return qSk === dSk && qSk.length >= 3;
    }
    return false;
  });
};

const searchEmployeeDirectory = (docs, term) => {
  if (!term || term.trim().length < 2) return [];
  // «مولوی - امیررضا» از لیست تلفن → کلمات تمیز
  const cleaned = term.replace(/[—–]/g, " ").replace(/\s+-\s+/g, " ");
  const words = cleaned.split(/\s+/).map((w) => w.trim()).filter((w) => w.length >= 2 && !/^(it|is|of)$/i.test(w));
  if (!words.length) return [];
  const results = [];
  for (const doc of docs || []) {
    if (!isEmployeeDirectoryDoc(doc)) continue;
    for (const line of (doc.content || "").split("\n")) {
      if (!line.includes("@")) continue;
      if (emailLineMatchesPerson(line, words)) {
        results.push(line.trim());
      }
    }
  }
  return [...new Set(results)];
};


// نام‌های نویز در خطوط داخلی (شهر/واحد) — نباید به‌عنوان بخش اسم برای جستجوی ایمیل استفاده شوند
const PHONE_LINE_NOISE = new Set([
  "مشهد", "تهران", "اصفهان", "شیراز", "تبریز", "کرج", "اهواز", "قم", "رشت", "کرمان",
  "مدیریت", "صنعتی", "واحد", "داخلی", "اداری", "مالی", "فروش", "بازرگانی", "تولید",
  "فنی", "انبار", "کارخانه", "دفتر", "مرکزی", "شعبه", "گروه", "بخش", "ایمنی", "منابع",
  "انسانی", "پشتیبانی", "خدمات", "مهندسی", "کیفیت", "کنترل", "it", "is", "hr", "of",
]);

/** از خطوط داخلی، کاندیدهای جستجوی ایمیل بساز و در AD بگرد — برای همهٔ همکاران یکسان کار می‌کند. */
const findEmailsFromPhoneLines = (docs, phoneMatches) => {
  const found = new Set();
  const tryTerm = (t) => {
    if (!t || t.trim().length < 2) return;
    searchEmployeeDirectory(docs, t).forEach((r) => found.add(r));
  };
  for (const pl of phoneMatches || []) {
    const namePart = (pl.split(/داخلی\s*:/i)[0] || pl).replace(/\d{3,5}/g, " ");
    const bits = namePart
      .replace(/[—–\-_/|,،]/g, " ")
      .split(/\s+/)
      .map((x) => x.trim())
      .filter((x) => x.length >= 2 && !PHONE_LINE_NOISE.has(x.toLowerCase()) && !PHONE_LINE_NOISE.has(x));
    if (!bits.length) continue;
    tryTerm(bits.join(" "));
    if (bits.length >= 2) tryTerm([...bits].reverse().join(" "));
    for (const b of bits) {
      if (b.length >= 4) tryTerm(b);
    }
  }
  return [...found];
};


// ۳۰ اوت ۲۰۲۶: وقتی فقط اسم همکار تایپ می‌شود (بدون «داخلی»/«ایمیل»)
const isLikelyPersonNameQuery = (text) => {
  const t = (text || "").trim();
  if (!t || t.length < 2 || t.length > 60) return false;
  if (isPhoneQuery(t) || isEmployeeLookupQuery(t)) return false;
  if (isMenuQuery(t) || isWeatherQuery(t) || isActivationQuery(t)) return false;
  if (isNewsQuery && typeof isNewsQuery === "function" && isNewsQuery(t)) return false;
  // «طلایی» (فامیلی) را رد نکن؛ فقط طلا به‌عنوان کالای قیمتی
  if (/دلار|تتر|یورو|پوند|درهم|لیر|حواله|سکه|طلا(?!یی)|نقره|بیت\s*کوین|قیمت|نرخ|اخبار|آب\s*هوا|منو|غذا|کانتین/i.test(t)) return false;
  if (/\d/.test(t)) return false;
  const words = t.replace(/[؟?!.,،]/g, " ").split(/\s+/).filter(Boolean);
  if (words.length < 1 || words.length > 4) return false;
  // فقط حروف فارسی/لاتین
  if (!words.every((w) => /^[\u0600-\u06FFa-zA-Z\u200c]+$/.test(w))) return false;
  return true;
};

const searchColleagueExtraInfo = (docs, term) => {
  if (!term || term.length < 2) return [];
  const termWords = normalizeText(term).split(/\s+/).filter((w) => w.length >= 2);
  if (!termWords.length) return [];
  const results = [];
  for (const doc of docs || []) {
    const content = doc.content || "";
    // خطوط ایمیل/داخلی خالص را رد کن (جداگانه در پروفایل می‌آیند) ولی بقیهٔ سندهای نقش/ایمنی را بخوان
    for (const line of content.split("\n")) {
      const ln = line.trim();
      if (ln.length < 12 || ln.length > 400) continue;
      if (/^===/.test(ln)) continue;
      // رد کردن خطوط خام فقط‌داخلی یا فقط‌ایمیل تکراری
      if (/داخلی\s*:\s*\d{3,5}\s*$/i.test(ln) && ln.length < 80) continue;
      if (lineMatchesPersonName(ln, termWords) || termWords.every((w) => normalizeText(ln).includes(w))) {
        // اگر دقیقاً همان خط تلفن/ایمیل است، در extra نگذار
        if (/@/.test(ln) && isEmployeeDirectoryDoc(doc)) continue;
        if (/داخلی\s*:/i.test(ln) && isPhoneDirectoryDoc(doc)) continue;
        results.push(ln);
      }
    }
  }
  return [...new Set(results)].slice(0, 10);
};

const buildColleagueProfileReply = (term, phoneMatches, emailMatches, extraMatches) => {
  const parts = [`👤 اطلاعات «${term}» از اسناد:`];
  if (phoneMatches.length) {
    parts.push("", "📞 داخلی / تلفن:");
    phoneMatches.forEach((m) => parts.push("- " + m));
  }
  if (emailMatches.length) {
    parts.push("", "📧 ایمیل / مشخصات سازمانی:");
    emailMatches.forEach((m) => parts.push("- " + m));
  }
  if (extraMatches.length) {
    parts.push("", "📄 سایر موارد در اسناد:");
    extraMatches.forEach((m) => parts.push("- " + m));
  }
  return parts.join("\n");
};



// یه خط CSV رو با رعایت quoteها پارس می‌کنه (خروجی SheetJS ممکنه فیلدهای دارای کاما رو داخل " " بذاره)
const parseCsvLine = (line) => {
  const result = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (line[i + 1] === '"') { cur += '"'; i++; } else inQuotes = false;
      } else cur += ch;
    } else {
      if (ch === '"') inQuotes = true;
      else if (ch === ",") { result.push(cur); cur = ""; }
      else cur += ch;
    }
  }
  result.push(cur);
  return result;
};

const normalizeWeekdayStr = (s) => (s || "").replace(/[\s\u200c]/g, "").trim();

// روز/هفته‌ی هدف رو از متن سوال کاربر یا (در نبود تاریخ صریح) از امروز محاسبه می‌کنه
const computeMenuTargetInfo = (userText) => {
  const now = new Date();
  const toEnDigits = (s) => s.replace(/[۰-۹]/g, d => "۰۱۲۳۴۵۶۷۸۹".indexOf(d));
  const monthNamesFa = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
  const weekdayNamesFa = ["یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه"]; // اندیس با getDay(): 0=یکشنبه...6=شنبه
  const weekNamesFa = ["اول", "دوم", "سوم", "چهارم"];
  const persianPartsOf = (d) => {
    const parts = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { year: "numeric", month: "numeric", day: "numeric" }).formatToParts(d);
    const get = (t) => parts.find(p => p.type === t)?.value || "";
    return { y: parseInt(toEnDigits(get("year")), 10), m: parseInt(toEnDigits(get("month")), 10), d: parseInt(toEnDigits(get("day")), 10) };
  };

  let targetDate = new Date(now);
  let isExplicit = false;

  // حالت صفر (بالاترین اولویت): روزهای نسبی مثل «فردا»، «دیروز»، «پس‌فردا»، «پریروز»
  const relativeDayMap = [
    [/پس\s*فردا|پسفردا/i, 2],
    [/پری\s*روز|پریروز/i, -2],
    [/فردا/i, 1],
    [/دیروز/i, -1],
  ];
  let relativeMatched = false;
  for (const [re, offset] of relativeDayMap) {
    if (re.test(userText)) {
      targetDate = new Date(now);
      targetDate.setDate(now.getDate() + offset);
      isExplicit = true;
      relativeMatched = true;
      break;
    }
  }

  // حالت الف: تاریخ صریح مثل «۲۰ مرداد» یا «مرداد ۲۰» — برای هر ماه/سالی، نه فقط ماه جاری
  const digitsFa = "۰۱۲۳۴۵۶۷۸۹";
  const dnum = "[0-9" + digitsFa + "]{1,2}";
  const monthAlt = monthNamesFa.join("|");
  const m1 = relativeMatched ? null : userText.match(new RegExp(`(${dnum})\\s*(${monthAlt})`));
  const m2 = relativeMatched ? null : userText.match(new RegExp(`(${monthAlt})\\s*(${dnum})`));
  const dayMatch = m1 ? m1[1] : (m2 ? m2[2] : null);
  const monthMatch = m1 ? m1[2] : (m2 ? m2[1] : null);

  if (dayMatch && monthMatch) {
    const targetMonthIdx = monthNamesFa.indexOf(monthMatch) + 1;
    const targetDayNum = parseInt(toEnDigits(dayMatch), 10);
    // نزدیک‌ترین وقوع این روز/ماه رو نسبت به امروز پیدا کن (تا ۴۰۰ روز جلو و عقب) — سال رو خودش حل می‌کنه
    outer:
    for (let offset = 0; offset <= 400; offset++) {
      const signs = offset === 0 ? [1] : [1, -1];
      for (const sign of signs) {
        const cand = new Date(now);
        cand.setDate(now.getDate() + sign * offset);
        const p = persianPartsOf(cand);
        if (p.m === targetMonthIdx && p.d === targetDayNum) {
          targetDate = cand; isExplicit = true;
          break outer;
        }
      }
    }
  } else if (!relativeMatched) {
    // حالت ب: فقط اسم روز هفته گفته شده (بدون تاریخ دقیق) — نزدیک‌ترین وقوع همون روز، از امروز به بعد (امروز هم حساب میشه)
    const weekdayEntries = [
      ["یکشنبه", 0], ["دوشنبه", 1], ["سهشنبه", 2], ["چهارشنبه", 3], ["پنجشنبه", 4], ["جمعه", 5], ["شنبه", 6],
    ];
    const normText = userText.replace(/[\s\u200c]/g, "");
    let matchedJsDay = null;
    for (const [name, jsDay] of weekdayEntries) {
      if (normText.includes(name)) { matchedJsDay = jsDay; break; }
    }
    if (matchedJsDay !== null) {
      for (let offset = 0; offset <= 6; offset++) {
        const cand = new Date(now);
        cand.setDate(now.getDate() + offset);
        if (cand.getDay() === matchedJsDay) { targetDate = cand; isExplicit = true; break; }
      }
    }
  }

  // از targetDate، سال/ماه/روز شمسی + هفته چرخشی پیوسته (شنبه‌محور، ریست‌نشونده در مرز ماه)
  const tp = persianPartsOf(targetDate);
  const weekNumber = getContinuousWeekNumber(targetDate);

  return {
    targetDay: tp.d, isExplicit, weekdayFa: weekdayNamesFa[targetDate.getDay()],
    weekLabel: "هفته " + weekNamesFa[weekNumber - 1],
    dateLabel: `${tp.d} ${monthNamesFa[tp.m - 1]} ${tp.y}`,
  };
};

// توی متن یه شیت (CSV چندبلاکه: هفته/روز/پیش‌غذا/اصلی/متفرقه برای منوی عادی + همون ستون‌ها برای رژیمی) دنبال ردیف هدف می‌گرده
const extractMenuRowFromSheetBody = (sheetBody, weekLabel, weekdayFa) => {
  const lines = (sheetBody || "").split("\n").map(l => l.trim()).filter(Boolean);
  let currentWeek = null;
  const targetWeekdayNorm = normalizeWeekdayStr(weekdayFa);
  for (const line of lines) {
    const cols = parseCsvLine(line);
    if (!cols.length) continue;
    const weekCell = (cols[0] || "").trim();
    if (weekCell && weekCell.includes("هفته")) currentWeek = weekCell;
    const dayCell = (cols[1] || "").trim();
    if (!dayCell || !currentWeek) continue;
    if (normalizeWeekdayStr(dayCell) === targetWeekdayNorm && currentWeek.trim() === weekLabel.trim()) {
      return {
        week: currentWeek, day: dayCell,
        normal: { starter: (cols[2] || "").trim(), main: (cols[3] || "").trim(), extra: (cols[4] || "").trim() },
        diet: { starter: (cols[8] || "").trim(), main: (cols[9] || "").trim(), extra: (cols[10] || "").trim() },
      };
    }
  }
  return null;
};

const cleanMenuField = (v) => (!v || v === "***" ? "ثبت نشده" : v);

const formatMenuReply = (target, sheetTitle, row) => {
  const lines = [`🍽️ منوی غذای ${target.dateLabel} (${row.week}، ${row.day}):`, ""];
  lines.push("🔹 منوی عادی:");
  lines.push(`- پیش‌غذا: ${cleanMenuField(row.normal.starter)}`);
  lines.push(`- غذای اصلی: ${cleanMenuField(row.normal.main)}`);
  lines.push(`- مواد متفرقه: ${cleanMenuField(row.normal.extra)}`);
  if (row.diet.starter || row.diet.main || row.diet.extra) {
    lines.push("");
    lines.push("🔹 منوی رژیمی/سلامت:");
    lines.push(`- پیش‌غذا: ${cleanMenuField(row.diet.starter)}`);
    lines.push(`- غذای اصلی: ${cleanMenuField(row.diet.main)}`);
    lines.push(`- مواد متفرقه: ${cleanMenuField(row.diet.extra)}`);
  }
  lines.push("");
  lines.push(`(بر اساس شیت «${sheetTitle}»)`);
  return lines.join("\n");
};

// 🎚️ ۱۳ اوت ۲۰۲۶: لیست پیش‌فرض اولویت provider ها — دقیقاً باید با DEFAULT_PROVIDER_ORDER
// توی main.py هم‌ارز باشه (همون ۵ کلید، هر ترتیبی). لیبل‌ها فقط برای نمایش توی پنل مدیریتن.
const PROVIDER_LABELS = {
  groq: "⚡ Groq",
  lmstudio: "🖥️ LM Studio (VM محلی)",
  gemini: "✨ Gemini",
  openrouter: "🔀 OpenRouter",
  nvidia: "💚 NVIDIA",
};
const DEFAULT_PROVIDER_ORDER = ["groq", "lmstudio", "gemini", "openrouter", "nvidia"];

function AdminPanel({ onClose, onDataChanged }) {
  const [tab, setTab] = useState("buttons");
  const [buttons, setButtons] = useState([]);
  const [qaList, setQaList] = useState([]);
  const [btnLabel, setBtnLabel] = useState("");
  const [btnQ, setBtnQ] = useState("");
  const [btnEditId, setBtnEditId] = useState(null);
  const [qaQ, setQaQ] = useState("");
  const [qaA, setQaA] = useState("");
  const [qaEditId, setQaEditId] = useState(null);
  const [annList, setAnnList] = useState([]);
  const [annTitle, setAnnTitle] = useState("");
  const [annContent, setAnnContent] = useState("");
  const [annEditId, setAnnEditId] = useState(null);
  const [forceLocalAI, setForceLocalAI] = useState(false);
  const [forceLocalAILoading, setForceLocalAILoading] = useState(false);
  const [providerOrder, setProviderOrder] = useState(DEFAULT_PROVIDER_ORDER);
  const [providerOrderLoading, setProviderOrderLoading] = useState(false);
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);
  // ── منابع وب (۱۶ اوت ۲۰۲۶) ──
  const [webSources, setWebSources] = useState([]);
  const [wsLabel, setWsLabel] = useState("");
  const [wsUrl, setWsUrl] = useState("");
  const [wsKeywords, setWsKeywords] = useState("");
  const [wsPriority, setWsPriority] = useState("0");
  const [wsEditId, setWsEditId] = useState(null);
  const [wsRefreshingId, setWsRefreshingId] = useState(null);

  const showMsg = (m) => { setMsg(m); setTimeout(() => setMsg(""), 2500); };

  useEffect(() => {
    loadButtons();
    loadQA();
    loadAnn();
    loadForceLocalAI();
    loadProviderOrder();
    loadWebSources();
  }, []);

  // 🎚️ ۱۳ اوت ۲۰۲۶: اولویت provider ها — دقیقاً همون الگوی force_lmstudio_only (کلید/مقدار توی
  // app_settings)، فقط این‌بار مقدار یه JSON array سریالایز‌شده به‌جای "true"/"false" هست.
  const loadProviderOrder = async () => {
    try {
      const data = await sbFetch("app_settings?key=eq.provider_priority&select=value");
      const raw = data?.[0]?.value;
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length === DEFAULT_PROVIDER_ORDER.length
            && new Set(parsed).size === DEFAULT_PROVIDER_ORDER.length
            && parsed.every(p => DEFAULT_PROVIDER_ORDER.includes(p))) {
          setProviderOrder(parsed);
          return;
        }
      }
      setProviderOrder(DEFAULT_PROVIDER_ORDER);
    } catch { setProviderOrder(DEFAULT_PROVIDER_ORDER); }
  };

  const saveProviderOrder = async (nextOrder) => {
    setProviderOrderLoading(true);
    try {
      await sbFetch("app_settings", {
        method: "POST",
        headers: { "Prefer": "resolution=merge-duplicates,return=minimal" },
        body: JSON.stringify({ key: "provider_priority", value: JSON.stringify(nextOrder) }),
      });
      setProviderOrder(nextOrder);
      showMsg("✅ اولویت هوش مصنوعی‌ها ذخیره شد");
    } catch (e) {
      showMsg("⚠️ خطا در ذخیره‌ی اولویت: " + e.message);
    }
    setProviderOrderLoading(false);
  };

  const moveProvider = (idx, dir) => {
    const next = [...providerOrder];
    const target = idx + dir;
    if (target < 0 || target >= next.length) return;
    [next[idx], next[target]] = [next[target], next[idx]];
    saveProviderOrder(next);
  };

  const loadForceLocalAI = async () => {
    try {
      const data = await sbFetch("app_settings?key=eq.force_lmstudio_only&select=value");
      setForceLocalAI(data?.[0]?.value === "true");
    } catch {}
  };

  const toggleForceLocalAI = async () => {
    setForceLocalAILoading(true);
    const next = !forceLocalAI;
    try {
      // از upsert استفاده می‌کنیم (نه PATCH ساده) چون اگه ردیف هنوز توی جدول ساخته نشده باشه،
      // PATCH بی‌خطا ولی بدون هیچ تاثیری برمی‌گرده (صفر ردیف مچ میشه) و مقدار هیچ‌وقت ذخیره نمیشه —
      // upsert در هر دو حالت (ردیف هست/نیست) درست کار می‌کنه.
      await sbFetch("app_settings", {
        method: "POST",
        headers: { "Prefer": "resolution=merge-duplicates,return=minimal" },
        body: JSON.stringify({ key: "force_lmstudio_only", value: String(next) }),
      });
      setForceLocalAI(next);
      showMsg(next ? "✅ فقط هوش مصنوعی محلی فعال شد" : "✅ برگشت به حالت عادی (همه‌ی provider ها)");
    } catch (e) {
      showMsg("⚠️ خطا در تغییر تنظیمات: " + e.message);
    }
    setForceLocalAILoading(false);
  };

  const loadButtons = async () => {
    try {
      const data = await sbFetch("buttons?order=sort_order");
      setButtons(data);
    } catch { showMsg("⚠️ خطا در بارگذاری دکمه‌ها"); }
  };

  const loadQA = async () => {
    try {
      const data = await sbFetch("custom_qa?order=id");
      setQaList(data);
    } catch { showMsg("⚠️ خطا در بارگذاری سوال‌ها"); }
  };

  const saveBtn = async () => {
    if (!btnLabel.trim() || !btnQ.trim()) { showMsg("⚠️ لیبل و سوال را پر کنید"); return; }
    setLoading(true);
    try {
      if (btnEditId !== null) {
        await sbFetch(`buttons?id=eq.${btnEditId}`, {
          method: "PATCH",
          body: JSON.stringify({ label: btnLabel, question: btnQ })
        });
        setBtnEditId(null);
      } else {
        await sbFetch("buttons", {
          method: "POST",
          body: JSON.stringify({ label: btnLabel, question: btnQ, sort_order: buttons.length + 1 })
        });
      }
      setBtnLabel(""); setBtnQ("");
      await loadButtons();
      onDataChanged();
      showMsg("✅ ذخیره شد");
    } catch { showMsg("⚠️ خطا در ذخیره"); }
    setLoading(false);
  };

  const deleteBtn = async (id) => {
    try {
      await sbFetch(`buttons?id=eq.${id}`, { method: "DELETE" });
      await loadButtons();
      onDataChanged();
      showMsg("✅ حذف شد");
    } catch { showMsg("⚠️ خطا در حذف"); }
  };

  const moveBtn = async (index, direction) => {
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= buttons.length) return;
    const a = buttons[index], b = buttons[newIndex];
    try {
      await sbFetch(`buttons?id=eq.${a.id}`, { method: "PATCH", body: JSON.stringify({ sort_order: b.sort_order }) });
      await sbFetch(`buttons?id=eq.${b.id}`, { method: "PATCH", body: JSON.stringify({ sort_order: a.sort_order }) });
      await loadButtons();
      onDataChanged();
    } catch { showMsg("⚠️ خطا در تغییر ترتیب"); }
  };

  const saveQA = async () => {
    if (!qaQ.trim() || !qaA.trim()) { showMsg("⚠️ سوال و جواب را پر کنید"); return; }
    setLoading(true);
    try {
      if (qaEditId !== null) {
        await sbFetch(`custom_qa?id=eq.${qaEditId}`, {
          method: "PATCH",
          body: JSON.stringify({ question: qaQ, answer: qaA })
        });
        setQaEditId(null);
      } else {
        await sbFetch("custom_qa", {
          method: "POST",
          body: JSON.stringify({ question: qaQ, answer: qaA })
        });
      }
      setQaQ(""); setQaA("");
      await loadQA();
      showMsg("✅ ذخیره شد");
    } catch { showMsg("⚠️ خطا در ذخیره"); }
    setLoading(false);
  };

  const deleteQA = async (id) => {
    try {
      await sbFetch(`custom_qa?id=eq.${id}`, { method: "DELETE" });
      await loadQA();
      showMsg("✅ حذف شد");
    } catch { showMsg("⚠️ خطا در حذف"); }
  };

  // نهم اوت ۲۰۲۶ — فیچر اطلاعیه‌ها: همون الگوی CRUD سوال/جواب، فقط جدول announcements
  const loadAnn = async () => {
    try {
      const data = await sbFetch("announcements?order=created_at.desc");
      setAnnList(data);
    } catch { showMsg("⚠️ خطا در بارگذاری اطلاعیه‌ها"); }
  };

  const saveAnn = async () => {
    if (!annTitle.trim() || !annContent.trim()) { showMsg("⚠️ عنوان و متن اطلاعیه را پر کنید"); return; }
    setLoading(true);
    try {
      if (annEditId !== null) {
        await sbFetch(`announcements?id=eq.${annEditId}`, {
          method: "PATCH",
          body: JSON.stringify({ title: annTitle, content: annContent })
        });
        setAnnEditId(null);
      } else {
        await sbFetch("announcements", {
          method: "POST",
          body: JSON.stringify({ title: annTitle, content: annContent })
        });
      }
      setAnnTitle(""); setAnnContent("");
      await loadAnn();
      showMsg("✅ ذخیره شد");
    } catch { showMsg("⚠️ خطا در ذخیره"); }
    setLoading(false);
  };

  const deleteAnn = async (id) => {
    try {
      await sbFetch(`announcements?id=eq.${id}`, { method: "DELETE" });
      await loadAnn();
      showMsg("✅ حذف شد");
    } catch { showMsg("⚠️ خطا در حذف"); }
  };

  // ── اسناد آموزشی ──
  const [docs, setDocs] = useState([]);
  const [docTitle, setDocTitle] = useState("");
  const [docContent, setDocContent] = useState("");
  const [docCategory, setDocCategory] = useState("general");
  const [docEditId, setDocEditId] = useState(null);

  useEffect(() => { loadDocs(); }, []);

  const loadDocs = async () => {
    try {
      const data = await sbFetch("knowledge_docs?order=created_at.desc");
      setDocs(data);
    } catch { showMsg("⚠️ خطا در بارگذاری اسناد"); }
  };

  const saveDoc = async () => {
    if (!docTitle.trim() || !docContent.trim()) { showMsg("⚠️ عنوان و محتوا را پر کنید"); return; }
    setLoading(true);
    try {
      if (docEditId !== null) {
        await sbFetch(`knowledge_docs?id=eq.${docEditId}`, {
          method: "PATCH",
          body: JSON.stringify({ title: docTitle, content: docContent, category: docCategory })
        });
        setDocEditId(null);
      } else {
        await sbFetch("knowledge_docs", {
          method: "POST",
          body: JSON.stringify({ title: docTitle, content: docContent, category: docCategory })
        });
      }
      setDocTitle(""); setDocContent(""); setDocCategory("general");
      await loadDocs();
      showMsg("✅ سند ذخیره شد");
    } catch { showMsg("⚠️ خطا در ذخیره"); }
    setLoading(false);
  };

  const deleteDoc = async (id) => {
    if (!window.confirm("این سند حذف شود؟")) return;
    try {
      await sbFetch(`knowledge_docs?id=eq.${id}`, { method: "DELETE" });
      setDocs(prev => prev.filter(d => d.id !== id));
      showMsg("✅ سند حذف شد");
    } catch (err) {
      console.error("Delete error:", err);
      showMsg("⚠️ خطا در حذف: " + err.message);
    }
  };

  // ── منابع وب — یه URL دلخواه که با کلیدواژه‌ی خودش، محتوای بلادرنگش به AI داده می‌شه ──
  const loadWebSources = async () => {
    try {
      const data = await sbFetch("web_sources?order=priority.asc,id.asc");
      setWebSources(data);
    } catch { showMsg("⚠️ خطا در بارگذاری منابع وب (احتمالاً جدول web_sources هنوز توی Supabase ساخته نشده)"); }
  };

  const saveWebSource = async () => {
    if (!wsLabel.trim() || !wsUrl.trim() || !wsKeywords.trim()) { showMsg("⚠️ لیبل، URL و کلیدواژه‌ها را پر کنید"); return; }
    if (!/^https?:\/\//i.test(wsUrl.trim())) { showMsg("⚠️ URL باید با http:// یا https:// شروع بشه"); return; }
    const priorityNum = parseInt(wsPriority, 10);
    setLoading(true);
    try {
      if (wsEditId !== null) {
        await sbFetch(`web_sources?id=eq.${wsEditId}`, {
          method: "PATCH",
          body: JSON.stringify({ label: wsLabel, url: wsUrl, keywords: wsKeywords, priority: isNaN(priorityNum) ? 0 : priorityNum })
        });
        setWsEditId(null);
      } else {
        await sbFetch("web_sources", {
          method: "POST",
          body: JSON.stringify({ label: wsLabel, url: wsUrl, keywords: wsKeywords, priority: isNaN(priorityNum) ? 0 : priorityNum })
        });
      }
      setWsLabel(""); setWsUrl(""); setWsKeywords(""); setWsPriority("0");
      await loadWebSources();
      showMsg("✅ منبع وب ذخیره شد");
    } catch (e) { showMsg("⚠️ خطا در ذخیره: " + e.message); }
    setLoading(false);
  };

  const deleteWebSource = async (id) => {
    if (!window.confirm("این منبع وب حذف شود؟")) return;
    try {
      await sbFetch(`web_sources?id=eq.${id}`, { method: "DELETE" });
      await loadWebSources();
      showMsg("✅ حذف شد");
    } catch { showMsg("⚠️ خطا در حذف"); }
  };

  // تست/بروزرسانی دستی — همون فچی که موقع سوال کاربر بلادرنگ انجام می‌شه، اینجا هم برای اطمینان
  // ادمین از این‌که سایت درست خونده می‌شه (قبل از این‌که کاربر واقعی سوال بپرسه) قابل‌اجراست.
  const refreshWebSource = async (src) => {
    setWsRefreshingId(src.id);
    try {
      const res = await fetchWithFallback("/fetch-web-source", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: src.url }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) { showMsg("⚠️ خطا در خوندن سایت: " + (data.error || "نامشخص")); setWsRefreshingId(null); return; }
      await sbFetch(`web_sources?id=eq.${src.id}`, {
        method: "PATCH",
        body: JSON.stringify({ last_content: data.content, last_fetched_at: new Date().toISOString() })
      });
      await loadWebSources();
      showMsg("✅ محتوای سایت بروزرسانی شد");
    } catch (e) { showMsg("⚠️ خطا در بروزرسانی: " + e.message); }
    setWsRefreshingId(null);
  };

  // تشخیص و مسطح‌سازی جدول‌های چندبلاکی مثل لیست تلفن داخلی (اسم/داخلی که چند بار پهلوی هم تکرار شده)
  // خروجی: آرایه‌ای از خط‌های "اسم — داخلی: شماره — ..." یا null اگه فرمت دایرکتوری تشخیص داده نشد
  const parseDirectoryLikeSheet = (rows) => {
    const isExtCell = (v) => {
      if (typeof v === "number") return true;
      if (typeof v === "string") {
        const t = v.trim();
        return /^\d{1,6}(\s*(و|,)\s*\d{1,6})*$/.test(t);
      }
      return false;
    };

    // ستون‌هایی که مقدار شماره‌مانند دارن رو پیدا کن، و فاصله بین ستون‌های عددی متوالی رو داخل هر ردیف حساب کن
    // (نه در کل شیت — چون یکی دو ردیف نامنظم نباید الگوی غالب رو خراب کنه)
    const gapCounts = {};
    rows.forEach((row) => {
      const numIdx = [];
      row.forEach((cell, idx) => { if (isExtCell(cell) && String(cell).trim() !== "") numIdx.push(idx); });
      for (let i = 1; i < numIdx.length; i++) {
        const gap = numIdx[i] - numIdx[i - 1];
        if (gap > 0) gapCounts[gap] = (gapCounts[gap] || 0) + 1;
      }
    });
    const sortedGaps = Object.entries(gapCounts).sort((a, b) => b[1] - a[1]);
    if (!sortedGaps.length) return null;
    const blockWidth = Number(sortedGaps[0][0]);
    if (blockWidth < 2) return null;

    const entries = [];
    rows.forEach((row) => {
      for (let start = 0; start + 1 < row.length; start += blockWidth) {
        const name = row[start];
        const ext = row[start + 1];
        if (typeof name === "string" && name.trim() && isExtCell(ext) && String(ext).trim() !== "") {
          const extras = row.slice(start + 2, start + blockWidth)
            .map((c) => (c === undefined || c === null ? "" : String(c).trim()))
            .filter(Boolean);
          entries.push(`${name.trim()} — داخلی: ${String(ext).trim()}${extras.length ? " — " + extras.join(" — ") : ""}`);
        }
      }
    });

    // اگه تعداد ردیف‌های معتبر خیلی کم بود، این احتمالاً یه لیست تلفن نیست — بذار fallback عادی اجرا بشه
    if (entries.length < Math.max(3, rows.length * 0.3)) return null;
    return entries;
  };

  // ۱۳ اوت ۲۰۲۶: تشخیص جدول‌های عمومی «با سرستون» (مثل خروجی Active Directory: Display name/
  // User principal name/Title/Department) و تبدیل هر ردیف به یه خط خودکفا با برچسب فیلد
  // ("Display name: Omid Gohari — User principal name: omid.gohari@...")، به‌جای CSV خام.
  // چرا لازم بود: CSV خام وقتی طولانیه (چندصد ردیف) هم توسط سقف کاراکتری بک‌اند (GROQ_BUDGET و
  // سقف کلی ۲۴۰۰۰ کاراکتری system_prompt) از وسط قطع می‌شه و ردیف‌های آخر گم می‌شن، هم مدل‌ها
  // توی تطبیق ستون‌به‌ستون یه ردیف CSV طولانی قابل‌اعتماد نیستن. جدول با سرستون از این جدول
  // تلفن (parseDirectoryLikeSheet، که فقط برای ستون عددی مثل داخلی طراحی شده) جداست چون اینجا
  // هیچ ستونی لزوماً عددی نیست.
  const HEADER_KEYWORDS = /نام|name|ایمیل|email|mail|تلفن|phone|mobile|شماره|سمت|title|واحد|دپارتمان|department|شرکت|company|سازمان/i;
  const parseHeaderTableSheet = (rows) => {
    if (!rows.length) return null;
    const header = rows[0].map((h) => (h === undefined || h === null ? "" : String(h).trim()));
    const nonEmptyHeaders = header.filter(Boolean);
    if (nonEmptyHeaders.length < 2) return null;
    if (!nonEmptyHeaders.some((h) => HEADER_KEYWORDS.test(h))) return null;
    // اگه اکثر ستون‌ها اصلاً عنوان ندارن، این احتمالاً یه جدول واقعی با سرستون نیست
    if (nonEmptyHeaders.length < header.length * 0.5) return null;

    const dataRows = rows.slice(1);
    const entries = [];
    dataRows.forEach((row) => {
      const parts = [];
      header.forEach((h, idx) => {
        if (!h) return;
        const v = row[idx];
        const vStr = v === undefined || v === null ? "" : String(v).trim();
        if (vStr) parts.push(`${h}: ${vStr}`);
      });
      if (parts.length >= 2) entries.push(parts.join(" — "));
    });
    // اگه تعداد ردیف‌های معتبر خیلی کم بود، این احتمالاً یه جدول با سرستون واقعی نیست — بذار fallback عادی (CSV) اجرا بشه
    if (entries.length < Math.max(3, dataRows.length * 0.3)) return null;
    return entries;
  };

  // یه فایل رو می‌خونه و متن استخراج‌شده‌ش رو برمی‌گردونه (بدون تغییر docContent — برای استفاده در آپلود چندتایی)
  const extractSingleFileContent = async (file) => {
    const ext = file.name.split(".").pop().toLowerCase();
    if (["jpg", "jpeg", "png", "webp"].includes(ext)) {
      try {
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });
        const [header, base64Data] = dataUrl.split(",");
        const mimeMatch = header.match(/data:(.*?);base64/);
        const mimeType = mimeMatch ? mimeMatch[1] : (file.type || "image/jpeg");
        const res = await fetchWithFallback("/extract-image", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ image_base64: base64Data, mime_type: mimeType }),
          timeoutMs: 45000,
        });
        const data = await res.json();
        if (data.success) return { success: true, text: data.text };
        return { success: false, error: data.error || "نامشخص" };
      } catch {
        return { success: false, error: "خطا در ارتباط با سرور برای خواندن تصویر" };
      }
    } else if (ext === "pdf") {
      try {
        const arrayBuffer = await file.arrayBuffer();
        const uint8 = new Uint8Array(arrayBuffer);
        const pdfjsLib = window.pdfjsLib;
        if (!pdfjsLib) return { success: false, error: "کتابخانه PDF هنوز لود نشده — چند ثانیه صبر کن و دوباره امتحان کن" };
        const pdf = await pdfjsLib.getDocument({ data: uint8 }).promise;
        let fullText = "";
        const numPages = pdf.numPages;
        for (let i = 1; i <= numPages; i++) {
          const page = await pdf.getPage(i);
          const content = await page.getTextContent();
          fullText += content.items.map(item => item.str).join(" ") + "\n";
        }
        const cleaned = fullText.replace(/\s+/g, " ").trim();
        // تشخیص PDF اسکن‌شده / بدون لایه متن: اگر متن خیلی کم باشد نسبت به تعداد صفحات
        const charsPerPage = numPages > 0 ? cleaned.length / numPages : 0;
        if (cleaned.length < 80 || charsPerPage < 40) {
          return {
            success: true,
            text: cleaned || "(متن قابل استخراج یافت نشد)",
            warning: "⚠️ این PDF احتمالاً اسکن یا تصویر است و لایه متن کمی دارد. برای دقت بیشتر، صفحات مهم را به‌صورت عکس (JPG/PNG) جداگانه آپلود کنید تا با Vision خوانده شوند."
          };
        }
        return { success: true, text: fullText };
      } catch {
        return { success: false, error: "خطا در خواندن PDF" };
      }
    } else if (ext === "docx") {
      try {
        const arrayBuffer = await file.arrayBuffer();
        const mammoth = window.mammoth;
        if (!mammoth) return { success: false, error: "کتابخانه Word هنوز لود نشده — چند ثانیه صبر کن و دوباره امتحان کن" };
        const result = await mammoth.extractRawText({ arrayBuffer });
        return { success: true, text: result.value };
      } catch {
        return { success: false, error: "خطا در خواندن فایل Word" };
      }
    } else if (ext === "doc") {
      return { success: false, error: "فرمت قدیمی .doc پشتیبانی نمیشه — فایل رو با Word به .docx تبدیل کن" };
    } else if (ext === "xlsx" || ext === "xls") {
      try {
        const arrayBuffer = await file.arrayBuffer();
        const XLSX = window.XLSX;
        if (!XLSX) return { success: false, error: "کتابخانه Excel هنوز لود نشده — چند ثانیه صبر کن و دوباره امتحان کن" };
        const wb = XLSX.read(arrayBuffer, { type: "array" });
        let fullText = "";
        wb.SheetNames.forEach(name => {
          const sheet = wb.Sheets[name];
          const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: "", raw: true });
          const directoryEntries = parseDirectoryLikeSheet(rows);
          if (directoryEntries) {
            fullText += `=== شیت: ${name} (لیست تلفن/داخلی) ===\n${directoryEntries.join("\n")}\n\n`;
          } else {
            const headerEntries = parseHeaderTableSheet(rows);
            if (headerEntries) {
              fullText += `=== شیت: ${name} (جدول با هدر) ===\n${headerEntries.join("\n")}\n\n`;
            } else {
              const csv = XLSX.utils.sheet_to_csv(sheet);
              fullText += `=== شیت: ${name} ===\n${csv}\n\n`;
            }
          }
        });
        return { success: true, text: fullText.trim() };
      } catch {
        return { success: false, error: "خطا در خواندن فایل Excel" };
      }
    } else {
      try {
        const text = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = (ev) => resolve(ev.target.result);
          reader.onerror = reject;
          reader.readAsText(file, "UTF-8");
        });
        return { success: true, text };
      } catch {
        return { success: false, error: "خطا در خواندن فایل" };
      }
    }
  };

  // تشخیص و مسطح‌سازی جدول‌های «برنامه هفتگی دوبلاکی» مثل منوی غذا (چند بلاک ستونی که هر کدوم هفته/روز/چند ستون توضیح دارن)
// این جدول‌ها با ستون تکراری «هفته های ماه» شناسایی می‌شن — با جدول تلفن (parseDirectoryLikeSheet) فرق دارن چون ستون‌هاشون عددی نیست
const parseWeeklyMenuSheet = (rows) => {
  let headerRowIdx = -1;
  let blockStarts = [];
  for (let r = 0; r < Math.min(rows.length, 5); r++) {
    const cols = [];
    (rows[r] || []).forEach((cell, idx) => {
      if (typeof cell === "string" && cell.trim() === "هفته های ماه") cols.push(idx);
    });
    if (cols.length >= 1) { headerRowIdx = r; blockStarts = cols; break; }
  }
  if (headerRowIdx === -1) return null;

  const labelRow = rows[headerRowIdx - 1] || [];
  const blocks = blockStarts.map((start) => ({
    start,
    label: (labelRow[start] && String(labelRow[start]).trim()) || "منو",
    currentWeek: "",
  }));

  const clean = (v) => {
    const s = (v === undefined || v === null) ? "" : String(v).trim();
    return (!s || s === "***" || s === "--") ? "ثبت نشده" : s;
  };

  const lines = [];
  for (let r = headerRowIdx + 1; r < rows.length; r++) {
    const row = rows[r];
    if (!row || row.every((c) => !String(c || "").trim())) continue;
    for (const block of blocks) {
      const weekCell = row[block.start];
      if (weekCell && String(weekCell).trim()) block.currentWeek = String(weekCell).trim();
      const day = row[block.start + 1];
      if (!day || !String(day).trim()) continue;
      const appetizer = clean(row[block.start + 2]);
      const main = clean(row[block.start + 3]);
      const extra = clean(row[block.start + 4]);
      lines.push(`[${block.label}] ${block.currentWeek || "؟"} - ${String(day).trim()}: پیش‌غذا: ${appetizer} — غذای اصلی: ${main} — مواد متفرقه: ${extra}`);
    }
  }
  if (lines.length < 5) return null;
  return lines;
};

const handleFileUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    // عنوان خودکار از اسم اولین فایل (برای آپلود چندتایی، پسوند صفحه رو هم حذف می‌کنه)
    if (!docTitle) {
      const base = files[0].name.replace(/\.[^/.]+$/, "").replace(/[-_ ]?(page|صفحه)[-_ ]?\d+$/i, "");
      setDocTitle(base);
    }

    let combined = docContent ? docContent + "\n\n" : "";
    let lastWarning = "";
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const label = files.length > 1 ? `فایل ${i + 1} از ${files.length} (${file.name})` : file.name;
      showMsg(`⏳ در حال خواندن ${label}...`);
      const result = await extractSingleFileContent(file);
      if (result.success) {
        combined += (files.length > 1 ? `\n--- ${file.name} ---\n` : "") + result.text + "\n";
        setDocContent(combined.trim());
        if (result.warning) lastWarning = result.warning;
      } else {
        showMsg(`⚠️ خطا در خواندن ${file.name}: ${result.error}`);
      }
    }
    if (lastWarning) {
      showMsg(`✅ فایل خونده شد — ${lastWarning}`);
    } else {
      showMsg(`✅ ${files.length > 1 ? `${files.length} فایل خونده شد` : "فایل خونده شد"} — لطفاً یه نگاه بنداز و مطمئن شو درست بوده`);
    }
    e.target.value = "";
  };

  const [stats, setStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(false);
  // ۲۱ اوت ۲۰۲۶: سهمیه‌ی تخمینی روزانه‌ی provider ها
  const [quotaStatus, setQuotaStatus] = useState(null);
  const [quotaLoading, setQuotaLoading] = useState(false);
  const loadQuotaStatus = async () => {
    setQuotaLoading(true);
    try {
      const res = await fetchWithFallback("/quota-status", { method: "GET", timeoutMs: 15000 });
      const data = await res.json();
      if (res.ok) setQuotaStatus(data);
    } catch { /* اگه لود نشد، بخش سهمیه خالی می‌مونه ولی بقیه‌ی آمار مشکلی نداره */ }
    setQuotaLoading(false);
  };

  const loadStats = async () => {
    setStatsLoading(true);
    try {
      const logs = await sbFetch("chat_logs?order=created_at.desc&limit=1000");

      // شمارش واقعی کل ردیف‌ها — قبلاً total از همون ۱۰۰۰ ردیفِ نمونه محاسبه می‌شد
      // و همیشه دقیقاً روی ۱۰۰۰ گیر می‌کرد. حالا با Prefer: count=exact یه کوئری جدا
      // فقط برای شمارش دقیق (بدون دانلود کل داده) می‌زنیم.
      let realTotal = logs.length;
      try {
        const countRes = await fetch(`${SUPABASE_URL}/rest/v1/chat_logs?select=id`, {
          method: "HEAD",
          headers: { ...sbHeaders, "Prefer": "count=exact" }
        });
        const range = countRes.headers.get("content-range"); // فرمت: "0-999/12345"
        if (range && range.includes("/")) {
          const total = range.split("/")[1];
          if (total && total !== "*") realTotal = parseInt(total, 10);
        }
      } catch { /* اگه شمارش دقیق fail شد، همون logs.length رو نگه دار */ }

      const now = new Date();
      const today = now.toISOString().slice(0, 10);
      const todayLogs = logs.filter(l => l.created_at.slice(0, 10) === today);
      
      // آمار کلی
      const totalAI = logs.filter(l => l.type === "ai").length;
      const totalDB = logs.filter(l => l.type === "database").length;
      const totalGreeting = logs.filter(l => l.type === "system" && l.source === "greeting").length;
      const totalOOS = logs.filter(l => l.source === "out_of_scope").length;

      // آمار امروز
      const todayAI = todayLogs.filter(l => l.type === "ai").length;
      const todayDB = todayLogs.filter(l => l.type === "database").length;

      // منابع AI
      const sources = {};
      logs.filter(l => l.type === "ai").forEach(l => {
        const src = l.source || "unknown";
        const key = src.startsWith("groq") ? "Groq" : 
                    src.startsWith("gemini") ? "Gemini" :
                    src.startsWith("nvidia") ? "NVIDIA" : src;
        sources[key] = (sources[key] || 0) + 1;
      });

      // آمار ۷ روز اخیر
      const daily = {};
      for (let i = 6; i >= 0; i--) {
        const d = new Date(now);
        d.setDate(d.getDate() - i);
        const key = d.toISOString().slice(0, 10);
        daily[key] = logs.filter(l => l.created_at.slice(0, 10) === key).length;
      }

      setStats({ totalAI, totalDB, totalGreeting, totalOOS, todayAI, todayDB, sources, daily, total: realTotal });
    } catch { showMsg("⚠️ خطا در بارگذاری آمار"); }
    setStatsLoading(false);
  };

  const tabStyle = (t) => ({
    padding: "10px 20px", border: "none", cursor: "pointer",
    fontFamily: "inherit", fontSize: 14, fontWeight: 600,
    borderBottom: tab === t ? "3px solid #0078d4" : "3px solid transparent",
    background: "none", color: tab === t ? "#0078d4" : "#666"
  });

  const inputStyle = {
    width: "100%", padding: "10px 12px", borderRadius: 8,
    border: "1.5px solid #ddd", marginBottom: 10,
    fontFamily: "inherit", fontSize: 14, direction: "rtl", boxSizing: "border-box"
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div data-admin-scroll style={{ background: "white", borderRadius: 12, width: "92%", maxWidth: 720, maxHeight: "92vh", overflowY: "auto", direction: "rtl", boxShadow: "0 8px 32px rgba(0,0,0,0.2)" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid #eee", display: "flex", justifyContent: "space-between", alignItems: "center", position: "sticky", top: 0, background: "white", zIndex: 10 }}>
          <h2 style={{ margin: 0, color: "#0078d4", fontSize: 18 }}>⚙️ پنل مدیریت</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 22, cursor: "pointer", color: "#666" }}>✕</button>
        </div>

        <div style={{ borderBottom: "1px solid #eee", display: "flex", padding: "0 16px" }}>
          <button style={tabStyle("buttons")} onClick={() => setTab("buttons")}>🔘 دکمه‌های سریع</button>
          <button style={tabStyle("qa")} onClick={() => setTab("qa")}>💬 سوال و جواب اختصاصی</button>
          <button style={tabStyle("docs")} onClick={() => setTab("docs")}>📚 اسناد آموزشی</button>
          <button style={tabStyle("websources")} onClick={() => setTab("websources")}>🌐 منابع وب</button>
          <button style={tabStyle("announcements")} onClick={() => setTab("announcements")}>📢 اطلاعیه‌ها</button>
          <button style={tabStyle("stats")} onClick={() => { setTab("stats"); loadStats(); loadQuotaStatus(); }}>📊 آمار</button>
        </div>

        <div style={{ padding: 20 }}>
          {msg && <div style={{ padding: "10px 16px", borderRadius: 8, marginBottom: 16, background: msg.includes("✅") ? "#d4edda" : "#fff3cd", color: msg.includes("✅") ? "#155724" : "#856404", fontSize: 14 }}>{msg}</div>}

          {tab === "buttons" && (
            <>
              <div style={{ background: "#f8f9fa", borderRadius: 8, padding: 16, marginBottom: 20 }}>
                <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>{btnEditId !== null ? "✏️ ویرایش دکمه" : "➕ افزودن دکمه جدید"}</h3>
                <input value={btnLabel} onChange={e => setBtnLabel(e.target.value)} placeholder="متن دکمه" style={inputStyle} />
                <input value={btnQ} onChange={e => setBtnQ(e.target.value)} placeholder="سوالی که ارسال میشه" style={inputStyle} />
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={saveBtn} disabled={loading} style={{ padding: "9px 20px", background: "#0078d4", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontFamily: "inherit", fontSize: 14 }}>
                    {loading ? "..." : btnEditId !== null ? "ویرایش" : "افزودن"}
                  </button>
                  {btnEditId !== null && <button onClick={() => { setBtnEditId(null); setBtnLabel(""); setBtnQ(""); }} style={{ padding: "9px 20px", background: "#6c757d", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontFamily: "inherit", fontSize: 14 }}>انصراف</button>}
                </div>
              </div>
              <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>دکمه‌های فعلی ({buttons.length})</h3>
              {buttons.map((btn, idx) => (
                <div key={btn.id} style={{ border: "1px solid #e0e0e0", borderRadius: 8, padding: "12px 14px", marginBottom: 8, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <button onClick={() => moveBtn(idx, -1)} disabled={idx === 0} style={{ padding: "2px 8px", background: idx === 0 ? "#eee" : "#f0f0f0", border: "1px solid #ddd", borderRadius: 4, cursor: idx === 0 ? "default" : "pointer", fontSize: 11 }}>▲</button>
                    <button onClick={() => moveBtn(idx, 1)} disabled={idx === buttons.length - 1} style={{ padding: "2px 8px", background: idx === buttons.length - 1 ? "#eee" : "#f0f0f0", border: "1px solid #ddd", borderRadius: 4, cursor: idx === buttons.length - 1 ? "default" : "pointer", fontSize: 11 }}>▼</button>
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, color: "#0078d4", marginBottom: 4 }}>🔘 {btn.label}</div>
                    <div style={{ color: "#666", fontSize: 12 }}>↪ {btn.question}</div>
                  </div>
                  <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    <button onClick={() => { setBtnLabel(btn.label); setBtnQ(btn.question); setBtnEditId(btn.id); }} style={{ padding: "6px 14px", background: "#ffc107", color: "#333", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", fontSize: 12 }}>ویرایش</button>
                    <button onClick={() => deleteBtn(btn.id)} style={{ padding: "6px 14px", background: "#dc3545", color: "white", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", fontSize: 12 }}>حذف</button>
                  </div>
                </div>
              ))}
            </>
          )}

          {tab === "stats" && (
            <>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: forceLocalAI ? "#fff4e5" : "#f0f7ff", border: `2px solid ${forceLocalAI ? "#f0a500" : "#0078d4"}33`, borderRadius: 10, padding: "14px 16px", marginBottom: 20 }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: forceLocalAI ? "#a05a00" : "#0078d4" }}>
                    🖥️ فقط هوش مصنوعی محلی (LM Studio روی سرور خودمون)
                  </div>
                  <div style={{ fontSize: 12, color: "#666", marginTop: 4 }}>
                    {forceLocalAI
                      ? "فعال — همه‌ی سوال‌ها فقط به مدل محلی می‌رن، بدون Groq/Gemini/OpenRouter. اگه VM آفلاین باشه، پیام خطا نشون داده می‌شه."
                      : "غیرفعال — زنجیره‌ی عادی (Groq → LM Studio → Gemini → ...) استفاده می‌شه."}
                  </div>
                </div>
                <button onClick={toggleForceLocalAI} disabled={forceLocalAILoading}
                  style={{ flexShrink: 0, background: forceLocalAI ? "#f0a500" : "#ccc", border: "none", borderRadius: 20, width: 52, height: 28, position: "relative", cursor: forceLocalAILoading ? "wait" : "pointer", transition: "background 0.2s" }}>
                  <span style={{ position: "absolute", top: 3, [forceLocalAI ? "right" : "left"]: 3, width: 22, height: 22, borderRadius: "50%", background: "white", transition: "all 0.2s", boxShadow: "0 1px 3px rgba(0,0,0,0.3)" }} />
                </button>
              </div>

              <div style={{ background: "#f8f9fa", border: "2px solid #0078d422", borderRadius: 10, padding: "14px 16px", marginBottom: 20 }}>
                <div style={{ fontWeight: 700, fontSize: 14, color: "#0078d4", marginBottom: 4 }}>
                  🎚️ اولویت هوش مصنوعی‌ها
                </div>
                <div style={{ fontSize: 12, color: "#666", marginBottom: 12 }}>
                  اولین موردی که در دسترس باشه و جواب بده استفاده میشه؛ با فلش‌ها ترتیب رو عوض کنید.
                  {forceLocalAI && " (توجه: چون «فقط هوش مصنوعی محلی» فعاله، این ترتیب فعلاً نادیده گرفته میشه.)"}
                </div>
                {providerOrder.map((p, idx) => (
                  <div key={p} style={{ display: "flex", alignItems: "center", gap: 10, background: "white", border: "1px solid #e0e0e0", borderRadius: 8, padding: "8px 12px", marginBottom: 6 }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <button onClick={() => moveProvider(idx, -1)} disabled={idx === 0 || providerOrderLoading}
                        style={{ padding: "2px 8px", background: idx === 0 ? "#eee" : "#f0f0f0", border: "1px solid #ddd", borderRadius: 4, cursor: idx === 0 ? "default" : "pointer", fontSize: 11 }}>▲</button>
                      <button onClick={() => moveProvider(idx, 1)} disabled={idx === providerOrder.length - 1 || providerOrderLoading}
                        style={{ padding: "2px 8px", background: idx === providerOrder.length - 1 ? "#eee" : "#f0f0f0", border: "1px solid #ddd", borderRadius: 4, cursor: idx === providerOrder.length - 1 ? "default" : "pointer", fontSize: 11 }}>▼</button>
                    </div>
                    <div style={{ fontWeight: 600, color: "#333", flex: 1 }}>{idx + 1}. {PROVIDER_LABELS[p] || p}</div>
                  </div>
                ))}
              </div>

              {/* ۲۱ اوت ۲۰۲۶: سهمیه‌ی تخمینی روزانه‌ی provider ها — دقت هر بخش کنارش نوشته شده،
                  چون بعضی‌ها واقعاً زنده‌ن (Groq تعداد درخواست، OpenRouter اعتبار) و بعضی‌ها فقط
                  تخمین شمارش خودمونه (Gemini/NVIDIA، و توکن روزانه‌ی Groq) — این provider ها
                  endpoint رسمی برای «سهمیه‌ی باقیمونده» ندارن. */}
              <div style={{ background: "#f8f9fa", border: "2px solid #0078d422", borderRadius: 10, padding: "14px 16px", marginBottom: 20 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                  <div style={{ fontWeight: 700, fontSize: 14, color: "#0078d4" }}>🔋 سهمیه‌ی روزانه‌ی هوش مصنوعی‌ها</div>
                  <button onClick={loadQuotaStatus} disabled={quotaLoading} style={{ padding: "4px 10px", background: "#0078d4", color: "white", border: "none", borderRadius: 14, cursor: "pointer", fontSize: 11, fontFamily: "inherit" }}>
                    {quotaLoading ? "..." : "🔄 بروزرسانی"}
                  </button>
                </div>
                <div style={{ fontSize: 11, color: "#999", marginBottom: 12 }}>
                  Groq (تعداد درخواست) و OpenRouter زنده و رسمی‌ان؛ Gemini/NVIDIA و توکن روزانه‌ی Groq فقط تخمینِ شمارش خودمون از آخرین ری‌استارت سرورن (این دو provider endpoint رسمی برای سهمیه ندارن).
                </div>
                {quotaLoading && !quotaStatus ? (
                  <div style={{ textAlign: "center", padding: 16, color: "#999", fontSize: 12 }}>در حال بارگذاری...</div>
                ) : quotaStatus ? (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
                    {Object.entries(quotaStatus.groq || {}).map(([label, g]) => {
                      const reqPct = g.remaining_requests != null && g.limit_requests ? Math.round((g.remaining_requests / g.limit_requests) * 100) : null;
                      const tpdPct = g.tpd_known_limit ? Math.max(0, Math.round(((g.tpd_known_limit - g.tokens_used_today_estimate) / g.tpd_known_limit) * 100)) : null;
                      return (
                        <div key={label} style={{ background: "white", border: "1px solid #e0e0e0", borderRadius: 8, padding: "10px 12px" }}>
                          <div style={{ fontWeight: 700, fontSize: 12, color: "#333", marginBottom: 6 }}>⚡ Groq {label}</div>
                          <div style={{ fontSize: 11, color: "#666" }}>
                            درخواست امروز: {g.remaining_requests != null ? `${g.remaining_requests} / ${g.limit_requests} باقیمونده${reqPct != null ? ` (${reqPct}٪)` : ""}` : "هنوز درخواستی نرفته"}
                          </div>
                          <div style={{ fontSize: 11, color: "#999", marginTop: 2 }}>
                            توکن امروز (تخمینی): ~{g.tokens_used_today_estimate.toLocaleString("fa-IR")} از {g.tpd_known_limit.toLocaleString("fa-IR")}{tpdPct != null ? ` (${tpdPct}٪ باقی)` : ""}
                          </div>
                        </div>
                      );
                    })}
                    {quotaStatus.openrouter && (
                      <div style={{ background: "white", border: "1px solid #e0e0e0", borderRadius: 8, padding: "10px 12px" }}>
                        <div style={{ fontWeight: 700, fontSize: 12, color: "#333", marginBottom: 6 }}>🔀 OpenRouter</div>
                        <div style={{ fontSize: 11, color: "#666" }}>
                          اعتبار: {quotaStatus.openrouter.limit != null ? `${quotaStatus.openrouter.usage ?? 0} / ${quotaStatus.openrouter.limit}` : "نامحدود/رایگان"}
                        </div>
                        {quotaStatus.openrouter.rate_limit && (
                          <div style={{ fontSize: 11, color: "#999", marginTop: 2 }}>
                            محدودیت نرخ: {quotaStatus.openrouter.rate_limit.requests} درخواست / {quotaStatus.openrouter.rate_limit.interval}
                          </div>
                        )}
                      </div>
                    )}
                    <div style={{ background: "white", border: "1px solid #e0e0e0", borderRadius: 8, padding: "10px 12px" }}>
                      <div style={{ fontWeight: 700, fontSize: 12, color: "#333", marginBottom: 6 }}>✨ Gemini</div>
                      <div style={{ fontSize: 11, color: "#666" }}>درخواست امروز (تخمینی): {quotaStatus.gemini_requests_today_estimate}</div>
                    </div>
                    <div style={{ background: "white", border: "1px solid #e0e0e0", borderRadius: 8, padding: "10px 12px" }}>
                      <div style={{ fontWeight: 700, fontSize: 12, color: "#333", marginBottom: 6 }}>💚 NVIDIA</div>
                      <div style={{ fontSize: 11, color: "#666" }}>درخواست امروز (تخمینی): {quotaStatus.nvidia_requests_today_estimate}</div>
                    </div>
                  </div>
                ) : (
                  <div style={{ textAlign: "center", padding: 16, color: "#999", fontSize: 12 }}>دکمه‌ی بروزرسانی رو بزن</div>
                )}
              </div>

              {statsLoading ? (
                <div style={{textAlign:"center",padding:40,color:"#666"}}>در حال بارگذاری...</div>
              ) : stats ? (
                <>
                  {/* کارت‌های خلاصه */}
                  <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12,marginBottom:24}}>
                    {[
                      {label:"کل پیام‌ها",value:stats.total,color:"#0078d4",icon:"💬"},
                      {label:"جواب AI امروز",value:stats.todayAI,color:"#0d9488",icon:"🤖"},
                      {label:"از دیتابیس امروز",value:stats.todayDB,color:"#6d28d9",icon:"🗄️"},
                      {label:"خارج از حوزه",value:stats.totalOOS,color:"#dc3545",icon:"🚫"},
                    ].map((c,i) => (
                      <div key={i} style={{background:"white",borderRadius:10,padding:"16px 14px",textAlign:"center",boxShadow:"0 2px 8px rgba(0,0,0,0.08)",border:`2px solid ${c.color}22`}}>
                        <div style={{fontSize:24}}>{c.icon}</div>
                        <div style={{fontSize:26,fontWeight:700,color:c.color,margin:"4px 0"}}>{c.value}</div>
                        <div style={{fontSize:11,color:"#666"}}>{c.label}</div>
                      </div>
                    ))}
                  </div>

                  {/* آمار کلی */}
                  <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16,marginBottom:20}}>
                    <div style={{background:"white",borderRadius:10,padding:16,boxShadow:"0 2px 8px rgba(0,0,0,0.08)"}}>
                      <h4 style={{margin:"0 0 12px",color:"#0078d4",fontSize:14}}>📊 کل آمار</h4>
                      {[
                        {label:"جواب‌های AI",value:stats.totalAI,color:"#0078d4"},
                        {label:"جواب‌های دیتابیس",value:stats.totalDB,color:"#0d9488"},
                        {label:"احوال‌پرسی",value:stats.totalGreeting,color:"#6d28d9"},
                        {label:"خارج از حوزه",value:stats.totalOOS,color:"#dc3545"},
                      ].map((r,i) => (
                        <div key={i} style={{display:"flex",justifyContent:"space-between",padding:"6px 0",borderBottom:"1px solid #f0f0f0"}}>
                          <span style={{fontWeight:600,color:r.color}}>{r.value}</span>
                          <span style={{fontSize:13,color:"#444"}}>{r.label}</span>
                        </div>
                      ))}
                    </div>

                    <div style={{background:"white",borderRadius:10,padding:16,boxShadow:"0 2px 8px rgba(0,0,0,0.08)"}}>
                      <h4 style={{margin:"0 0 12px",color:"#0078d4",fontSize:14}}>🤖 منابع AI</h4>
                      {Object.entries(stats.sources).sort((a,b)=>b[1]-a[1]).map(([src,cnt],i) => (
                        <div key={i} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"6px 0",borderBottom:"1px solid #f0f0f0"}}>
                          <span style={{fontWeight:600,color:"#0078d4"}}>{cnt}</span>
                          <span style={{fontSize:12,color:"#444"}}>{src}</span>
                        </div>
                      ))}
                      {Object.keys(stats.sources).length === 0 && <p style={{color:"#999",fontSize:13,textAlign:"center"}}>هنوز داده‌ای نیست</p>}
                    </div>
                  </div>

                  {/* ۷ روز اخیر */}
                  <div style={{background:"white",borderRadius:10,padding:16,boxShadow:"0 2px 8px rgba(0,0,0,0.08)"}}>
                    <h4 style={{margin:"0 0 12px",color:"#0078d4",fontSize:14}}>📅 ۷ روز اخیر</h4>
                    <div style={{display:"flex",gap:8,alignItems:"flex-end",height:80}}>
                      {Object.entries(stats.daily).map(([date,cnt],i) => {
                        const max = Math.max(...Object.values(stats.daily), 1);
                        const h = Math.max((cnt/max)*70, cnt>0?4:0);
                        return (
                          <div key={i} style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",gap:4}}>
                            <div style={{fontSize:10,color:"#666",fontWeight:600}}>{cnt}</div>
                            <div style={{width:"100%",height:`${h}px`,background:"#0078d4",borderRadius:"4px 4px 0 0",transition:"height 0.3s"}}/>
                            <div style={{fontSize:9,color:"#999",writingMode:"vertical-rl",transform:"rotate(180deg)"}}>{date.slice(5)}</div>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  <div style={{textAlign:"center",marginTop:16}}>
                    <button onClick={loadStats} style={{padding:"8px 20px",background:"#0078d4",color:"white",border:"none",borderRadius:8,cursor:"pointer",fontFamily:"inherit",fontSize:13}}>🔄 بروزرسانی</button>
                  </div>
                </>
              ) : (
                <div style={{textAlign:"center",padding:40}}>
                  <button onClick={loadStats} style={{padding:"10px 24px",background:"#0078d4",color:"white",border:"none",borderRadius:8,cursor:"pointer",fontFamily:"inherit",fontSize:14}}>📊 نمایش آمار</button>
                </div>
              )}
            </>
          )}

          {tab === "docs" && (
            <>
              <div style={{ background: "#f8f9fa", borderRadius: 8, padding: 16, marginBottom: 20 }}>
                <h3 style={{ margin: "0 0 14px", fontSize: 15, color: "#333" }}>{docEditId !== null ? "✏️ ویرایش سند" : "➕ افزودن سند آموزشی"}</h3>

                <input
                  value={docTitle}
                  onChange={e => setDocTitle(e.target.value)}
                  placeholder="عنوان سند (فارسی یا انگلیسی)..."
                  style={{width:"100%",padding:"10px 12px",borderRadius:8,border:"1.5px solid #ddd",marginBottom:10,fontFamily:"inherit",fontSize:14,direction:"rtl",boxSizing:"border-box"}}
                />

                <select
                  value={docCategory}
                  onChange={e => setDocCategory(e.target.value)}
                  style={{width:"100%",padding:"10px 12px",borderRadius:8,border:"1.5px solid #ddd",marginBottom:10,fontFamily:"inherit",fontSize:14,direction:"rtl",boxSizing:"border-box"}}
                >
                  <option value="general">عمومی</option>
                  <option value="windows">ویندوز</option>
                  <option value="office">آفیس</option>
                  <option value="network">شبکه</option>
                  <option value="erp">راهکاران / ERP</option>
                  <option value="domain">دامین</option>
                  <option value="other">سایر</option>
                </select>

                <div style={{background:"#fff",border:"2px dashed #0078d4",borderRadius:8,padding:14,marginBottom:10,textAlign:"center"}}>
                  <div style={{fontSize:13,color:"#555",marginBottom:8}}>📁 آپلود فایل</div>
                  <input
                    type="file"
                    accept=".md,.txt,.pdf,.docx,.xlsx,.xls,.jpg,.jpeg,.png,.webp"
                    multiple
                    onChange={handleFileUpload}
                    style={{fontSize:13,cursor:"pointer"}}
                  />
                  <div style={{fontSize:11,color:"#999",marginTop:6}}>فرمت‌های مجاز: TXT، MD، PDF، Word (.docx)، Excel (.xlsx/.xls)، عکس (JPG/PNG/WebP) — می‌تونی چند فایل رو با هم انتخاب کنی</div>
                </div>

                <div style={{position:"relative"}}>
                  <textarea
                    value={docContent}
                    onChange={e => setDocContent(e.target.value)}
                    placeholder="یا متن را اینجا paste کنید..."
                    rows={8}
                    style={{width:"100%",padding:"10px 12px",borderRadius:8,border:"1.5px solid #ddd",marginBottom:4,fontFamily:"inherit",fontSize:13,direction:"rtl",resize:"vertical",boxSizing:"border-box"}}
                  />
                </div>
                <div style={{fontSize:12,color:"#999",marginBottom:10,textAlign:"right"}}>
                  📊 {docContent.length.toLocaleString()} کاراکتر
                  {docContent.length > 10000 && <span style={{color:"#e67e22",marginRight:8}}>⚠️ فایل بزرگ — فقط ۳۰۰۰ کاراکتر اول به AI ارسال می‌شه</span>}
                </div>

                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={saveDoc}
                    disabled={loading}
                    style={{padding:"9px 20px",background:"#0078d4",color:"white",border:"none",borderRadius:8,cursor:"pointer",fontFamily:"inherit",fontSize:14,opacity:loading?0.6:1}}
                  >
                    {loading ? "در حال ذخیره..." : docEditId !== null ? "✅ ذخیره ویرایش" : "✅ افزودن سند"}
                  </button>
                  {docEditId !== null && (
                    <button
                      onClick={() => { setDocEditId(null); setDocTitle(""); setDocContent(""); setDocCategory("general"); }}
                      style={{padding:"9px 20px",background:"#6c757d",color:"white",border:"none",borderRadius:8,cursor:"pointer",fontFamily:"inherit",fontSize:14}}
                    >
                      ❌ انصراف
                    </button>
                  )}
                </div>
              </div>

              <h3 style={{ margin: "0 0 12px", fontSize: 15, color: "#333" }}>📚 اسناد ذخیره شده ({docs.length})</h3>
              {docs.length === 0 ? (
                <p style={{color:"#999",textAlign:"center",padding:30}}>هنوز سندی اضافه نشده</p>
              ) : docs.map((doc) => (
                <div key={doc.id} style={{border:"1px solid #e0e0e0",borderRadius:8,padding:"12px 14px",marginBottom:10,background:"#fff"}}>
                  <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:6}}>
                    <div style={{display:"flex",gap:6}}>
                      <button
                        onClick={() => {
                          setDocTitle(doc.title);
                          setDocContent(doc.content);
                          setDocCategory(doc.category || "general");
                          setDocEditId(doc.id);
                          // اسکرول به بالا
                          document.querySelector("[data-admin-scroll]")?.scrollTo({top:0,behavior:"smooth"});
                        }}
                        style={{padding:"6px 14px",background:"#ffc107",color:"#333",border:"none",borderRadius:6,cursor:"pointer",fontFamily:"inherit",fontSize:12,fontWeight:600}}
                      >
                        ✏️ ویرایش
                      </button>
                      <button
                        onClick={() => deleteDoc(doc.id)}
                        style={{padding:"6px 14px",background:"#dc3545",color:"white",border:"none",borderRadius:6,cursor:"pointer",fontFamily:"inherit",fontSize:12,fontWeight:600}}
                      >
                        🗑️ حذف
                      </button>
                    </div>
                    <div style={{textAlign:"right"}}>
                      <span style={{fontWeight:700,color:"#0078d4",fontSize:14}}>📄 {doc.title}</span>
                      <span style={{marginRight:8,fontSize:11,background:"#e8f4fd",color:"#0078d4",padding:"2px 8px",borderRadius:10}}>{doc.category || "general"}</span>
                    </div>
                  </div>
                  <div style={{color:"#666",fontSize:12,textAlign:"right",marginBottom:4}}>{(doc.content || "").slice(0,150)}...</div>
                  <div style={{color:"#aaa",fontSize:11,textAlign:"right"}}>{(doc.content || "").length.toLocaleString()} کاراکتر · {new Date(doc.created_at).toLocaleDateString("fa-IR")}</div>
                </div>
              ))}
            </>
          )}

          {tab === "websources" && (
            <>
              <div style={{ background: "#f8f9fa", borderRadius: 8, padding: 16, marginBottom: 20 }}>
                <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>{wsEditId !== null ? "✏️ ویرایش منبع وب" : "➕ افزودن منبع وب جدید"}</h3>
                <input value={wsLabel} onChange={e => setWsLabel(e.target.value)} placeholder="لیبل (مثلاً: نرخ ارز نوسان‌پلاس)" style={inputStyle} />
                <input value={wsUrl} onChange={e => setWsUrl(e.target.value)} placeholder="آدرس صفحه (مثلاً: https://www.navasanplus.net/)" style={{ ...inputStyle, direction: "ltr", textAlign: "left" }} />
                <input value={wsKeywords} onChange={e => setWsKeywords(e.target.value)} placeholder="کلیدواژه‌ها با ویرگول جدا کنید (مثلاً: دلار، نرخ ارز، یورو، حواله)" style={inputStyle} />
                <input type="number" value={wsPriority} onChange={e => setWsPriority(e.target.value)} placeholder="اولویت (عدد کوچیک‌تر = مهم‌تر، پیش‌فرض ۰)" style={inputStyle} />
                <div style={{ fontSize: 12, color: "#999", marginBottom: 10, textAlign: "right" }}>
                  وقتی سوال کاربر یکی از این کلیدواژه‌ها رو داشته باشه، محتوای همین صفحه (بلادرنگ یا با کش تا ۱۰ دقیقه) به هوش مصنوعی داده می‌شه تا دقیقاً از روی همون متن جواب بده — با ذکر منبع و ساعت دریافت زیر جواب. اگه یه سوال با چندتا منبع هم‌زمان مچ بشه، منبعی که عدد اولویتش کوچیک‌تره برنده می‌شه.
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={saveWebSource} disabled={loading} style={{ padding: "9px 20px", background: "#0078d4", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontFamily: "inherit", fontSize: 14 }}>
                    {loading ? "..." : wsEditId !== null ? "ذخیره ویرایش" : "افزودن"}
                  </button>
                  {wsEditId !== null && <button onClick={() => { setWsEditId(null); setWsLabel(""); setWsUrl(""); setWsKeywords(""); setWsPriority("0"); }} style={{ padding: "9px 20px", background: "#6c757d", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontFamily: "inherit", fontSize: 14 }}>انصراف</button>}
                </div>
              </div>
              <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>منابع وب ثبت‌شده ({webSources.length})</h3>
              {webSources.length === 0 ? <p style={{ color: "#999", textAlign: "center", padding: 30 }}>هنوز منبع وبی اضافه نشده</p> : webSources.map((src) => (
                <div key={src.id} style={{ border: "1px solid #e0e0e0", borderRadius: 8, padding: "12px 14px", marginBottom: 10, background: "#fff" }}>
                  <div style={{ fontWeight: 700, color: "#0078d4", fontSize: 14, marginBottom: 4 }}>🌐 {src.label} <span style={{ fontWeight: 400, fontSize: 11, color: "#999" }}>(اولویت: {src.priority ?? 0})</span></div>
                  <div style={{ color: "#0078d4", fontSize: 12, direction: "ltr", textAlign: "left", marginBottom: 6, wordBreak: "break-all" }}>{src.url}</div>
                  <div style={{ color: "#666", fontSize: 12, marginBottom: 6 }}>🔑 کلیدواژه‌ها: {src.keywords}</div>
                  <div style={{ color: "#aaa", fontSize: 11, marginBottom: 10 }}>
                    {src.last_fetched_at ? `آخرین دریافت: ${new Date(src.last_fetched_at).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" })}` : "هنوز دریافت نشده"}
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <button onClick={() => refreshWebSource(src)} disabled={wsRefreshingId === src.id} style={{ padding: "6px 14px", background: "#28a745", color: "white", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", fontSize: 12, fontWeight: 600, opacity: wsRefreshingId === src.id ? 0.6 : 1 }}>
                      {wsRefreshingId === src.id ? "⏳ در حال خواندن..." : "🔄 بروزرسانی دستی"}
                    </button>
                    <button onClick={() => { setWsLabel(src.label); setWsUrl(src.url); setWsKeywords(src.keywords); setWsPriority(String(src.priority ?? 0)); setWsEditId(src.id); document.querySelector("[data-admin-scroll]")?.scrollTo({ top: 0, behavior: "smooth" }); }} style={{ padding: "6px 14px", background: "#ffc107", color: "#333", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", fontSize: 12, fontWeight: 600 }}>✏️ ویرایش</button>
                    <button onClick={() => deleteWebSource(src.id)} style={{ padding: "6px 14px", background: "#dc3545", color: "white", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", fontSize: 12, fontWeight: 600 }}>🗑️ حذف</button>
                  </div>
                </div>
              ))}
            </>
          )}

          {tab === "qa" && (
            <>
              <div style={{ background: "#f8f9fa", borderRadius: 8, padding: 16, marginBottom: 20 }}>
                <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>{qaEditId !== null ? "✏️ ویرایش سوال" : "➕ افزودن سوال جدید"}</h3>
                <input value={qaQ} onChange={e => setQaQ(e.target.value)} placeholder="سوال را بنویسید..." style={inputStyle} />
                <textarea value={qaA} onChange={e => setQaA(e.target.value)} placeholder="جواب را بنویسید..." rows={4} style={{ ...inputStyle, resize: "vertical" }} />
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={saveQA} disabled={loading} style={{ padding: "9px 20px", background: "#0078d4", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontFamily: "inherit", fontSize: 14 }}>
                    {loading ? "..." : qaEditId !== null ? "ویرایش" : "افزودن"}
                  </button>
                  {qaEditId !== null && <button onClick={() => { setQaEditId(null); setQaQ(""); setQaA(""); }} style={{ padding: "9px 20px", background: "#6c757d", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontFamily: "inherit", fontSize: 14 }}>انصراف</button>}
                </div>
              </div>
              <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>سوال‌های ذخیره شده ({qaList.length})</h3>
              {qaList.length === 0 ? <p style={{ color: "#999", textAlign: "center", padding: 30 }}>هنوز سوالی اضافه نشده</p> : qaList.map((item) => (
                <div key={item.id} style={{ border: "1px solid #e0e0e0", borderRadius: 8, padding: "12px 14px", marginBottom: 8 }}>
                  <div style={{ fontWeight: 600, color: "#0078d4", marginBottom: 6 }}>❓ {item.question}</div>
                  <div style={{ color: "#444", fontSize: 13, marginBottom: 10, lineHeight: 1.6 }}>💬 {item.answer}</div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button onClick={() => { setQaQ(item.question); setQaA(item.answer); setQaEditId(item.id); }} style={{ padding: "6px 14px", background: "#ffc107", color: "#333", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", fontSize: 12 }}>ویرایش</button>
                    <button onClick={() => deleteQA(item.id)} style={{ padding: "6px 14px", background: "#dc3545", color: "white", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", fontSize: 12 }}>حذف</button>
                  </div>
                </div>
              ))}
            </>
          )}

          {tab === "announcements" && (
            <>
              <div style={{ background: "#f8f9fa", borderRadius: 8, padding: 16, marginBottom: 20 }}>
                <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>{annEditId !== null ? "✏️ ویرایش اطلاعیه" : "➕ افزودن اطلاعیه جدید"}</h3>
                <input value={annTitle} onChange={e => setAnnTitle(e.target.value)} placeholder="عنوان اطلاعیه..." style={inputStyle} />
                <textarea value={annContent} onChange={e => setAnnContent(e.target.value)} placeholder="متن اطلاعیه را بنویسید..." rows={4} style={{ ...inputStyle, resize: "vertical" }} />
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={saveAnn} disabled={loading} style={{ padding: "9px 20px", background: "#0078d4", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontFamily: "inherit", fontSize: 14 }}>
                    {loading ? "..." : annEditId !== null ? "ویرایش" : "افزودن"}
                  </button>
                  {annEditId !== null && <button onClick={() => { setAnnEditId(null); setAnnTitle(""); setAnnContent(""); }} style={{ padding: "9px 20px", background: "#6c757d", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontFamily: "inherit", fontSize: 14 }}>انصراف</button>}
                </div>
              </div>
              <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>اطلاعیه‌های ثبت‌شده ({annList.length})</h3>
              {annList.length === 0 ? <p style={{ color: "#999", textAlign: "center", padding: 30 }}>هنوز اطلاعیه‌ای اضافه نشده</p> : annList.map((item) => (
                <div key={item.id} style={{ border: "1px solid #e0e0e0", borderRadius: 8, padding: "12px 14px", marginBottom: 8 }}>
                  <div style={{ fontWeight: 600, color: "#0078d4", marginBottom: 6 }}>📢 {item.title}</div>
                  <div style={{ color: "#444", fontSize: 13, marginBottom: 6, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{item.content}</div>
                  <div style={{ color: "#aaa", fontSize: 11, marginBottom: 10 }}>{new Date(item.created_at).toLocaleDateString("fa-IR-u-ca-persian")}</div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button onClick={() => { setAnnTitle(item.title); setAnnContent(item.content); setAnnEditId(item.id); }} style={{ padding: "6px 14px", background: "#ffc107", color: "#333", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", fontSize: 12 }}>ویرایش</button>
                    <button onClick={() => deleteAnn(item.id)} style={{ padding: "6px 14px", background: "#dc3545", color: "white", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", fontSize: 12 }}>حذف</button>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// === تشخیص مسیر شبکه‌ای (UNC path مثل \\server\share\file) توی متن اطلاعیه و نمایش جدا با دکمه‌ی کپی ===
// چون مرورگرها به دلایل امنیتی اجازه‌ی باز شدن لینک \\server\... رو از یه صفحه‌ی وب نمی‌دن،
// این‌جوری حداقل مسیر رو مرتب و قابل‌کپی نشون می‌دیم.
const UNC_PATH_REGEX = /^\\{1,2}[^\s\\]+(?:\\[^\s\\]+){2,}\\{0,2}$/;
// ۱۳ اوت ۲۰۲۶: لینک‌های http(s) توی اطلاعیه‌ها قبلاً فقط متن ساده بودن (قابل کلیک نبودن، کاربر
// باید دستی کپی/پیست می‌کرد). این regex هر URL داخل یه خط رو پیدا می‌کنه (نه فقط وقتی کل خط
// خودِ لینکه) و به <a target="_blank"> تبدیلش می‌کنه؛ بقیه‌ی متن همون خط دست‌نخورده می‌مونه.
const URL_REGEX = /(https?:\/\/[^\s<>"')]+)/g;
function renderLineWithLinks(line, keyPrefix) {
  const parts = line.split(URL_REGEX);
  if (parts.length === 1) return line || "\u00A0";
  return parts.map((part, idx) => {
    if (/^https?:\/\//.test(part)) {
      // علائم نگارشی انتهای جمله (نقطه/ویرگول/پرانتز بسته) که گاهی به لینک می‌چسبن رو از خودِ href جدا می‌کنیم
      const trailingMatch = part.match(/[.,;:!?)\]]+$/);
      const trailing = trailingMatch ? trailingMatch[0] : "";
      const href = trailing ? part.slice(0, -trailing.length) : part;
      // ۱۳ اوت ۲۰۲۶: قبلاً لینک با word-break می‌شکست، ولی بازم بخشیش بیرون کادر می‌افتاد (چون
      // خودِ کادر flex بود و به عرض محتوای بدون‌شکست کشیده می‌شد). حالا لینک با فونت کوچیک‌تر
      // توی یه خط جا میشه؛ اگه بازم جا نشد (URL خیلی بلند)، به‌جای شکستن/سرریز، خودِ لینک
      // اسکرول افقی داخلی می‌گیره — هیچ‌وقت از مرز کادر بیرون نمی‌زنه.
      return (
        <span key={keyPrefix + "-" + idx} dir="ltr" style={{ unicodeBidi: "isolate", display: "inline-block", maxWidth: "100%", verticalAlign: "bottom" }}>
          <a href={href} target="_blank" rel="noopener noreferrer"
            style={{ display: "block", maxWidth: "100%", overflowX: "auto", whiteSpace: "nowrap", color: "#0078d4", fontWeight: 700, textDecoration: "underline", fontSize: 11 }}>
            {href}
          </a>
          {trailing}
        </span>
      );
    }
    return <span key={keyPrefix + "-" + idx}>{part}</span>;
  });
}
function AnnouncementContentBlock({ content }) {
  const [copiedIdx, setCopiedIdx] = useState(null);
  const lines = (content || "").split("\n");
  return (
    <>
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (UNC_PATH_REGEX.test(trimmed)) {
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, background: "#eef3f8", border: "1px solid #d6e2ec", borderRadius: 8, padding: "8px 10px", margin: "6px 0" }}>
              <code dir="ltr" style={{ flex: 1, fontFamily: "Consolas, monospace", fontSize: 13, color: "#2c3e50", direction: "ltr", textAlign: "left", overflowWrap: "anywhere" }}>{trimmed}</code>
              <button onClick={() => {
                navigator.clipboard.writeText(trimmed).catch(() => {});
                setCopiedIdx(i);
                setTimeout(() => setCopiedIdx(null), 1500);
              }} style={{ flexShrink: 0, background: copiedIdx === i ? "#28a745" : "#0078d4", color: "white", border: "none", borderRadius: 6, padding: "4px 10px", fontSize: 12, cursor: "pointer", fontFamily: "inherit" }}>
                {copiedIdx === i ? "✓ کپی شد" : "📋 کپی مسیر"}
              </button>
            </div>
          );
        }
        return <div key={i} style={{ overflowWrap: "anywhere" }}>{renderLineWithLinks(line, "l" + i)}</div>;
      })}
    </>
  );
}

export default function ITAssistant() {
  const welcomeContent = (lang) =>
    lang === "en"
      ? "Hello! I'm the Nutricia-MMP IT AI Assistant 👋\nAsk me anything about Windows, Office, software, network, or IT requests."
      : "سلام! من دستیار هوش مصنوعی واحد IT شرکت Nutricia-MMP هستم 👋\nهر سوالی درباره ویندوز، آفیس، نرم‌افزارها، شبکه یا درخواست‌های IT دارید بپرسید.";
  const WELCOME = (lang = "fa") => ({ role: "assistant", content: welcomeContent(lang) });

  const loadMessages = (lang) => {
    try {
      const saved = sessionStorage.getItem("it_assistant_messages");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {}
    return [WELCOME(lang || "fa")];
  };

  const [uiLang, setUiLang] = useState(() => { try { return localStorage.getItem("it_assistant_lang") || "fa"; } catch { return "fa"; } });
  const isEn = uiLang === "en";
  const toggleUiLang = () => setUiLang((prev) => { const next = prev === "en" ? "fa" : "en"; try { localStorage.setItem("it_assistant_lang", next); } catch {} return next; });
  const [messages, setMessages] = useState(() => loadMessages(typeof localStorage !== "undefined" ? (localStorage.getItem("it_assistant_lang") || "fa") : "fa"));
  const [userId, setUserId] = useState(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [showAdminLogin, setShowAdminLogin] = useState(false);
  const [showAdminPanel, setShowAdminPanel] = useState(false);
  const [showAnnouncements, setShowAnnouncements] = useState(false);
  const [showQuickButtons, setShowQuickButtons] = useState(true);
  const [announcements, setAnnouncements] = useState([]);
  const [adminPass, setAdminPass] = useState("");
  const [adminError, setAdminError] = useState("");
  const [buttons, setButtons] = useState([]);
  const bottomRef = useRef(null);
  const abortControllerRef = useRef(null); // ۱۸ اوت ۲۰۲۶: برای دکمه‌ی «توقف» موقع لود جواب AI
  const stoppedByUserRef = useRef(false); // تا پیام «متوقف شد» دوبار (هم از دکمه، هم از catch) اضافه نشه

  useEffect(() => { loadButtons(); loadAnnouncements(); loadForceLocalAI(); loadProviderOrder(); }, []);
  // با تعویض FA/EN متن خوش‌آمدگویی هم هم‌زبان شود (اگر هنوز فقط پیام خوش‌آمد است)
  useEffect(() => {
    setMessages((prev) => {
      if (!prev || prev.length === 0) return [WELCOME(uiLang)];
      if (prev.length === 1 && prev[0]?.role === "assistant") {
        return [WELCOME(uiLang)];
      }
      // اگر اولین پیام همان خوش‌آمد قدیمی است، فقط همان را عوض کن
      const first = prev[0];
      if (first?.role === "assistant" && /دستیار هوش مصنوعی|IT AI Assistant/i.test(first.content || "")) {
        return [WELCOME(uiLang), ...prev.slice(1)];
      }
      return prev;
    });
  }, [uiLang]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    try { sessionStorage.setItem("it_assistant_messages", JSON.stringify(messages)); } catch {}
  }, [messages]);

  useEffect(() => {
    const init = async () => {
      const uid = await getUserId();
      setUserId(uid);
      try {
        const history = await sbFetch(`chat_history?user_id=eq.${encodeURIComponent(uid)}&order=id&limit=100`);
        if (history.length > 0) {
          setMessages(history.map(h => ({ role: h.role, content: h.content })));
        }
      } catch {}
    };
    init();
  }, []);

  const getUserId = async () => {
    try {
      if (window.microsoftTeams) {
        await window.microsoftTeams.app.initialize();
        const context = await window.microsoftTeams.app.getContext();
        const id = context?.user?.userPrincipalName || context?.user?.id;
        if (id) return id;
      }
    } catch {}
    let id = localStorage.getItem("it_assistant_user_id");
    if (!id) {
      id = "guest_" + Math.random().toString(36).slice(2);
      localStorage.setItem("it_assistant_user_id", id);
    }
    return id;
  };

  const saveMessage = async (uid, role, content) => {
    try {
      await sbFetch("chat_history", { method: "POST", body: JSON.stringify({ user_id: uid, role, content }) });
    } catch {}
  };

  const loadButtons = async () => {
    try {
      const data = await sbFetch("buttons?order=sort_order");
      setButtons(data);
    } catch {}
  };

  const loadAnnouncements = async () => {
    try {
      const data = await sbFetch("announcements?order=created_at.desc");
      setAnnouncements(data);
    } catch {}
  };

  const [forceLocalAI, setForceLocalAI] = useState(false);
  const loadForceLocalAI = async () => {
    try {
      const data = await sbFetch("app_settings?key=eq.force_lmstudio_only&select=value");
      setForceLocalAI(data?.[0]?.value === "true");
    } catch {}
  };

  // 🎚️ ۱۳ اوت ۲۰۲۶: همون کلید provider_priority که پنل مدیریت ذخیره می‌کنه، اینجا خونده و
  // همراه هر درخواست /chat فرستاده میشه؛ اگه نبود/نامعتبر بود، بک‌اند خودش ترتیب پیش‌فرض رو استفاده می‌کنه.
  const [providerOrder, setProviderOrder] = useState(DEFAULT_PROVIDER_ORDER);
  const loadProviderOrder = async () => {
    try {
      const data = await sbFetch("app_settings?key=eq.provider_priority&select=value");
      const raw = data?.[0]?.value;
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length === DEFAULT_PROVIDER_ORDER.length
            && new Set(parsed).size === DEFAULT_PROVIDER_ORDER.length
            && parsed.every(p => DEFAULT_PROVIDER_ORDER.includes(p))) {
          setProviderOrder(parsed);
          return;
        }
      }
      setProviderOrder(DEFAULT_PROVIDER_ORDER);
    } catch { setProviderOrder(DEFAULT_PROVIDER_ORDER); }
  };

  const sendButtonMessage = async (question) => {
    await loadButtons();
    sendMessage(question);
  };

  // جستجوی هوشمند در اسناد — بر اساس عنوان و محتوا
  // ۲۱ اوت ۲۰۲۶: جستجوی اسناد آموزشی تقویت شد — امتیازدهی عمیق‌تر روی محتوا،
  // مچ مرزی کلمه‌ای (نه substring خام)، اولویت بالاتر برای تطابق چندکلمه‌ای، و بودجه بیشتر
  // برای سندهای با امتیاز بالا. pure JS و بدون API اضافه → سرعت و سازگاری با اینترنت ایران حفظ شد.
  const searchDocsWithAI = (userText, docs) => {
    if (!docs || docs.length === 0) return "";
    const q = normalizeText(userText);
    const words = q.split(/\s+/).filter(w => w.length > 1);
    if (words.length === 0) return "";

    const scored = docs.map(doc => {
      const titleNorm = normalizeText(doc.title || "");
      const catNorm = normalizeText(doc.category || "");
      // بخش بیشتری از محتوا امتیازدهی می‌شود (تا ~۴۰۰۰ کاراکتر) تا اسناد بلندتر هم پیدا شوند
      const contentNorm = normalizeText((doc.content || "").slice(0, 4000));
      let score = 0;
      let matchedWords = 0;
      for (const w of words) {
        let hit = false;
        if (wordBoundaryIncludes(titleNorm, w) || titleNorm.includes(w)) {
          score += 12;
          hit = true;
        }
        if (wordBoundaryIncludes(catNorm, w) || catNorm.includes(w)) {
          score += 5;
          hit = true;
        }
        if (wordBoundaryIncludes(contentNorm, w) || contentNorm.includes(w)) {
          score += 3;
          hit = true;
        }
        if (hit) matchedWords += 1;
      }
      // تطابق چندکلمه‌ای (پوشش بیشتر سوال) امتیاز اضافی می‌گیرد
      if (matchedWords >= 2) score += matchedWords * 4;
      if (matchedWords >= 3) score += 8;
      return { doc, score, matchedWords };
    }).sort((a, b) => b.score - a.score);

    // اگه سند چند شیت داره (مثل آرشیو چندماهه)، فقط نزدیک‌ترین شیت به تاریخ امروز رو بده
    const getContentForDoc = (doc, isTopHit) => {
      const maxChars = isTopHit ? 7500 : 5000; // سند رتبه ۱ فضای بیشتری می‌گیرد
      const relevant = pickRelevantSheet(doc.content || "");
      if (relevant) {
        return `(توجه مهم: این سند آرشیو چندماهه/چندساله‌ست و شامل چند شیت جداست. شیت «${relevant.title}» به‌عنوان نزدیک‌ترین شیت به تاریخ امروز انتخاب شده. این‌جور جدول‌های شرکتی («هفته اول» تا «هفته چهارم») معمولاً یه الگوی تکرارشونده‌ان که برای یه بازه‌ی چندماهه معتبرن (نه فقط ماهی که تو اسم شیت اومده) — پس حتی اگه اسم این شیت با ماه سوال کاربر فرق داشت، بازم باید از همین داده به‌عنوان دقیق‌ترین اطلاعات موجود جواب بدی. هرگز نگو «این ماه رو ندارم» یا «اطلاعات در دسترس نیست» — همیشه بر اساس هفته‌ای که کاربر پرسیده (طبق جدول تاریخ بالای پرامپت) از همین داده جواب بده. فقط اگه لازم دیدی، در پایان جواب یه اشاره‌ی کوتاه بکن که این داده از نزدیک‌ترین ماه موجود (${relevant.title}) برداشته شده.)\n=== بخش انتخاب‌شده: ${relevant.title} ===\n${relevant.body.slice(0, maxChars)}`;
      }
      return (doc.content || "").slice(0, maxChars);
    };

    const topDocs = scored.filter(x => x.score > 0).slice(0, 3);
    const otherDocs = scored.filter(x => x.score === 0);

    let result = "";
    if (topDocs.length > 0) {
      result = topDocs.map((x, idx) =>
        "=== سند مرتبط: " + x.doc.title + " [دسته: " + (x.doc.category || "general") + "] ===\n" + getContentForDoc(x.doc, idx === 0)
      ).join("\n\n");
      // دستور صریح برای مدل: فقط از محتوای سند جواب بده
      result = "⚠️ دستور مهم: سوال کاربر با اسناد زیر مرتبط تشخیص داده شد. جواب را دقیقاً و فقط بر اساس محتوای همین اسناد بده. اگر اطلاعات کافی نبود صریح بگو «در اسناد موجود پیدا نشد» — هرگز از دانش عمومی خودت جایگزین نساز.\n\n" + result;
    } else {
      result = "=== اسناد آموزشی موجود (هیچ‌کدوم به سوال فعلی مرتبط تشخیص داده نشد) ===\n" + docs.map(d =>
        "📄 " + d.title + " [" + (d.category || "general") + "]"
      ).join("\n") + "\n(اگه سوال کاربر به یکی از این عنوان‌ها مرتبطه، بگو کدومو می‌خواد تا محتواش رو بیارم.)";
    }

    if (otherDocs.length > 0 && topDocs.length > 0) {
      result += "\n\n=== سایر اسناد موجود ===\n" + otherDocs.map(x => "📄 " + x.doc.title).join("، ");
    }

    return result;
  };

    const buildSystemPrompt = async (userText) => {
    try {
      // cache برای custom_qa — هر 5 دقیقه یه بار از Supabase میخونه
      if (!_qaCache || Date.now() - _qaCacheTime > 300000) {
        _qaCache = await sbFetch("custom_qa?order=id");
        _qaCacheTime = Date.now();
      }
      const allDocs = await sbFetch("knowledge_docs?select=id,title,category,content&order=created_at.desc").catch(() => []);
      const [customQA, docsContext] = await Promise.all([
        Promise.resolve(_qaCache),
        userText && allDocs.length > 0 ? searchDocsWithAI(userText, allDocs) : Promise.resolve("")
      ]);
      let prompt = BASE_KNOWLEDGE + "\n\n=== اطلاعات تاریخ امروز ===\n" + getPersianDateContext();
      if (isEn) {
        prompt = "UI language is English. Answer the user in clear English unless they write in Persian.\n\n" + prompt;
      }
      if (customQA.length > 0) {
        const customSection = customQA.map(item => "سوال: " + item.question + "\nجواب: " + item.answer).join("\n\n");
        prompt += "\n\n=== سوال و جواب‌های اختصاصی شرکت ===\n" + customSection;
      }
      if (docsContext) {
        prompt += "\n\n=== اسناد آموزشی مرتبط ===\n" + docsContext;
      }
      return { prompt, qaList: customQA };
    } catch { return { prompt: BASE_KNOWLEDGE, qaList: [] }; }
  };

  const findExactQA = (userText, qaList) => {
    if (!qaList || qaList.length === 0) return null;
    const normalize = (s) => s.trim().replace(/[\s،,؟?!.]+/g, " ").toLowerCase();
    const userNorm = normalize(userText);
    // exact match
    const exact = qaList.find(item => normalize(item.question) === userNorm);
    if (exact) return exact.answer;
    // چهارم اوت ۲۰۲۶: قبلاً partial match با substring خام بود (userNorm.includes(qNorm) یا برعکس).
    // این باعث می‌شد یه سوال ذخیره‌شده‌ی تک‌کلمه‌ای مثل "excel" داخل هر سوال دیگه‌ای که همون کلمه رو
    // داشت (مثلاً "what is excel?") match بشه و جواب فارسیِ از‌پیش‌نوشته‌شده رو مستقیم برگردونه — بدون
    // این‌که اصلاً از هوش مصنوعی (و قانون «به زبان سوال جواب بده») رد بشه. حالا دو محافظ اضافه شده:
    // ۱) هر دو طرف باید حداقل ۲ کلمه داشته باشن (یه کلمه‌ی تنها خیلی مبهمه برای partial match امنه)
    // ۲) match باید مرز کلمه (word boundary) باشه، نه substring خام وسط یه کلمه‌ی دیگه
    const partial = qaList.find(item => {
      const qNorm = normalize(item.question);
      const qWords = qNorm.split(" ").filter(Boolean);
      const userWords = userNorm.split(" ").filter(Boolean);
      if (qWords.length < 2 || userWords.length < 2) return false;
      const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const qInUser = new RegExp(`(^|\\s)${esc(qNorm)}(\\s|$)`).test(userNorm);
      const userInQ = new RegExp(`(^|\\s)${esc(userNorm)}(\\s|$)`).test(qNorm);
      return qInUser || userInQ;
    });
    return partial ? partial.answer : null;
  };

  const renderMessage = (text) => {
    // این چت فقط متن ساده نشون می‌ده (نه Markdown رندرشده)؛ اگه مدل به‌اشتباه از ** یا # استفاده کنه، پاکش کن
    const cleaned = text
      .replace(/\*\*\*/g, "—")      // *** (نشونه‌ی خالی بودن سلول در اسناد اکسل) → خط تیره خوانا
      .replace(/\*\*/g, "")          // **بولد** → بدون نشونه
      .replace(/^#{1,6}\s*/gm, "")   // # هدر → بدون #
      // لایه‌ی دفاعی: گاهی مدل‌ها (به‌خصوص Groq) سرسری کاراکتر/کلمه از زبان‌های دیگه قاطی جواب فارسی می‌کنن
      .replace(/[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\u0900-\u097f]/g, "") // چینی/ژاپنی/کره‌ای/هندی
      .replace(/[أإ]/g, "ا").replace(/ؤ/g, "و").replace(/[ئي]/g, "ی").replace(/ة/g, "ه").replace(/ك/g, "ک"); // حروف عربی که فارسی نیست
    // ۱۳ اوت ۲۰۲۶: نتایج جستجوی ایمیل کارمند (searchEmployeeDirectory) شامل آدرس ایمیل خام
    // (بدون http://) هست؛ regex قبلی فقط لینک‌های http(s) رو تشخیص می‌داد. حالا ایمیل هم جدا
    // تشخیص داده می‌شه و به‌جای متن ساده، لینک mailto: با استایل پررنگ/آبی نشون داده می‌شه —
    // هم قابل کلیک (باز کردن کلاینت ایمیل)، هم چون متن انتخاب‌پذیره قابل کپی.
    const EMAIL_REGEX = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
    const parts = cleaned.split(new RegExp(`(https?:\\/\\/\\S+|${EMAIL_REGEX.source})`, "g"));
    return parts.map((part, i) => {
      if (part.startsWith("http://") || part.startsWith("https://")) {
        const cleanUrl = part.replace(/[.,،؟!)\]]+$/, "");
        const isDownload = cleanUrl.match(/\.(cmd|exe|zip|msi|bat)$/i);
        return (
          <a key={i} href={cleanUrl} target="_blank" rel="noopener noreferrer"
            download={isDownload ? true : undefined}
            style={{ color: "#0078d4", textDecoration: "underline", fontWeight: 600 }}>
            {isDownload ? "📥 دانلود فایل" : cleanUrl}
          </a>
        );
      }
      if (new RegExp(`^${EMAIL_REGEX.source}$`).test(part)) {
        return (
          <a key={i} href={`mailto:${part}`} dir="ltr" style={{ color: "#0078d4", fontWeight: 700, textDecoration: "underline", unicodeBidi: "isolate" }}>
            {part}
          </a>
        );
      }
      return part;
    });
  };

  const logChat = async (source, type) => {
    try {
      await sbFetch("chat_logs", {
        method: "POST",
        body: JSON.stringify({ source, type })
      });
    } catch {}
  };

  const cleanText = (text) => text.replace(/[\u3000-\u9fff\uac00-\ud7af\u3040-\u30ff\u0900-\u097f\u0e00-\u0e7f\u1e00-\u1eff\u0100-\u024f\u0400-\u04ff]/g, "");

  // نهم اوت ۲۰۲۶: برچسب فارسی خوانا برای منبع هر جواب AI — زیر هر جواب نشون داده میشه
  const sourceLabel = (source) => {
    if (!source) return "هوش مصنوعی";
    if (source.startsWith("groq")) return "Groq (openai/gpt-oss-120b)";
    // ⚠️ ۱۳ اوت ۲۰۲۶: قبلاً اینجا با === "lmstudio_relay" چک می‌شد، ولی source واقعی همیشه
    // به‌شکل "lmstudio_relay:اسم‌مدل" برمی‌گرده (نه دقیقاً "lmstudio_relay") — پس این چک هیچ‌وقت
    // مچ نمی‌شد و به‌جاش رشته‌ی خام فنی مثل "lmstudio_relay:?" مستقیم نمایش داده می‌شد. حالا
    // startsWith چک می‌کنه و یه برچسب خوانا با اسم مدل (اگه بک‌اند فرستاده باشه) می‌سازه.
    if (source.startsWith("lmstudio_relay")) {
      const model = source.split(":")[1];
      return model ? `گرفته شده از سرور لوکال (مدل: ${model})` : "گرفته شده از سرور لوکال";
    }
    if (source === "gemini") return "Gemini";
    if (source.startsWith("openrouter")) return "OpenRouter (" + source.split(":")[1] + ")";
    if (source === "nvidia") return "NVIDIA (llama-3.3-70b)";
    return source;
  };

  // نهم اوت ۲۰۲۶: تشخیص جمله‌ی دقیق امتناع (قانون ۲ توی BASE_KNOWLEDGE) — برای این‌که آمار
  // «خارج از حوزه» توی پنل مدیریت واقعاً چیزی غیر از صفر نشون بده، باید این امتناع رو جدا از
  // بقیه‌ی جواب‌های AI لاگ کنیم.
  const isOutOfScopeReply = (text) => (text || "").includes("این موضوع در حوزه پشتیبانی IT نیست");

  // چهارم اوت ۲۰۲۶: کاربر گزارش داد جواب‌های انگلیسی قبلاً چپ‌چین بودن، الان همیشه راست‌چین/RTL
  // نشون داده می‌شن (چون استایل بابل پیام قبلاً همیشه direction:"rtl" ثابت بود). این تابع تشخیص
  // می‌ده متن غالباً لاتین (انگلیسی) هست یا فارسی/عربی، تا بابل پیام بتونه جهت مناسب رو بگیره.
  // ۵ اوت ۲۰۲۶: محافظه‌کارتر شد — همون دلیل رفع باگ backend (is_english_question) رو ببین.
  // یه پیام خطای انگلیسی طولانی وسط یه جمله‌ی فارسی نباید کل بابل رو چپ‌چین کنه.
  const isLatinText = (text) => {
    const persianArabicChars = (text.match(/[\u0600-\u06FF\u0750-\u077F]/g) || []).length;
    const latinChars = (text.match(/[A-Za-z]/g) || []).length;
    if (latinChars === 0) return false;
    return persianArabicChars <= 3;
  };

  // منابع وب: صفحه رو از طریق بک‌اند (فقط بک‌اند به سایت‌های خارجی بدون محدودیت CORS دسترسی داره)
  // بلادرنگ می‌خونه و نسخه‌ی تازه رو توی همون ردیف Supabase کش می‌کنه تا سوال‌های بعدی (تا سقف
  // WEB_SOURCE_CACHE_MS) این فچ رو دوباره انجام ندن. query (متن سوال کاربر) هم پاس داده می‌شه تا
  // برای منابعی مثل Navasan، بک‌اند بتونه فقط همون آیتم خاص (مثلاً فقط دلار) رو بگیره، نه کل لیست.
  const fetchAndCacheWebSource = async (src, query, signal) => {
    try {
      const res = await fetchWithFallback("/fetch-web-source", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: src.url, query: query || "" }),
        signal,
      });
      const data = await res.json();
      if (!res.ok || !data.success) return null;
      const fetchedAtIso = new Date().toISOString();
      try {
        await sbFetch(`web_sources?id=eq.${src.id}`, {
          method: "PATCH",
          body: JSON.stringify({ last_content: data.content, last_fetched_at: fetchedAtIso }),
        });
      } catch { /* اگه ذخیره‌ی کش توی Supabase خطا داد، بازم می‌تونیم از همون محتوای تازه‌خونده‌شده برای همین یه سوال استفاده کنیم */ }
      return {
        content: data.content,
        fetched_at: fetchedAtIso,
        deterministic_reply: data.deterministic_reply || null,
      };
    } catch {
      return null;
    }
  };

  // ۱۸ اوت ۲۰۲۶: کلیک روی دکمه‌ی توقف باید فوری حس بشه — به‌جای این‌که منتظر بمونیم fetch واقعاً
  // abort بشه (روی بعضی محیط‌ها مثل Teams webview این می‌تونه کند/متغیر باشه)، UI رو همینجا
  // (synchronous، بدون async) فوراً آپدیت می‌کنیم؛ خودِ abort() هم صدا زده می‌شه تا درخواست شبکه
  // هرچه زودتر پس‌زمینه قطع بشه، ولی کاربر منتظرش نمی‌مونه.
  const stopGeneration = () => {
    if (!abortControllerRef.current || stoppedByUserRef.current) return;
    stoppedByUserRef.current = true;
    setLoading(false);
    setMessages(prev => [...prev, { role: "assistant", content: isEn ? "⏹️ Request stopped." : "⏹️ درخواست شما متوقف شد." }]);
    abortControllerRef.current.abort();
  };

  const sendMessage = async (text) => {
    const userText = (text || input).trim();
    if (!userText || loading) return;
    setInput("");
    const newMessages = [...messages, { role: "user", content: userText }];
    setMessages(newMessages);
    if (userId) saveMessage(userId, "user", userText);
    setLoading(true);
    stoppedByUserRef.current = false;
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    // اگه کاربر داشت به سوال «وصل به شبکه داخلی هستید؟» جواب بله می‌داد، مستقیم دستورات KMS مشروع شرکت رو بده (بدون AI، بدون دانلود فایل)
    {
      const lastMsg = messages[messages.length - 1];
      if (lastMsg && lastMsg.role === "assistant" && lastMsg.content === ACTIVATION_NETWORK_QUESTION && isYesReply(userText)) {
        setMessages([...newMessages, { role: "assistant", content: ACTIVATION_INTERNAL_ANSWER }]);
        if (userId) saveMessage(userId, "assistant", ACTIVATION_INTERNAL_ANSWER);
        logChat("activation_internal", "deterministic");
        setLoading(false);
        return;
      }
    }

    // اگه سوال درباره اکتیو نبودن ویندوز/آفیس بود، مستقیم و بدون AI سوال وضعیت شبکه رو بپرس
    if (isActivationQuery(userText)) {
      setMessages([...newMessages, { role: "assistant", content: ACTIVATION_NETWORK_QUESTION }]);
      if (userId) saveMessage(userId, "assistant", ACTIVATION_NETWORK_QUESTION);
      logChat("activation_question", "deterministic");
      setLoading(false);
      return;
    }

    // اگه سوال درباره داخلی/شماره تلفن بود، مستقیم توی سندها بگرد (بدون AI) — چون مدل‌ها توی partial match قابل‌اعتماد نیستن
    if (isPhoneQuery(userText)) {
      try {
        const docs = await sbFetch("knowledge_docs?select=id,title,category,content&order=created_at.desc").catch(() => []);
        const term = resolveFollowupSearchTerm(extractPhoneSearchTerm(userText), messages);
        const matches = searchPhoneDirectory(docs, term);
        if (matches.length > 0) {
          const reply = "📞 نتایج جستجو برای «" + term + "»:\n\n" + matches.map(m => "- " + m).join("\n");
          setMessages([...newMessages, { role: "assistant", content: reply }]);
          if (userId) saveMessage(userId, "assistant", reply);
          logChat("phone_lookup", "deterministic");
          setLoading(false);
          return;
        }
        // اگه هیچ match‌ای نبود، بذار جریان عادی AI ادامه پیدا کنه
      } catch (e) {
        // بذار جریان عادی AI ادامه پیدا کنه
      }
    }

    // اگه سوال درباره ایمیل کارمند بود، مستقیم توی سندهای «جدول با هدر» (خروجی اکسل AD/HR) بگرد —
    // چون اسم فارسی تایپ‌شده با اسم لاتین توی رکورد فرق داره، اینجا تطبیق تقریبی (transliteration) هم انجام میشه
    if (isEmployeeLookupQuery(userText)) {
      try {
        const docs = await sbFetch("knowledge_docs?select=id,title,category,content&order=created_at.desc").catch(() => []);
        const term = resolveFollowupSearchTerm(extractEmployeeSearchTerm(userText), messages);
        let matches = searchEmployeeDirectory(docs, term);
        const phoneMatches = searchPhoneDirectory(docs, term);
        // اگر ایمیل با نام فارسی پیدا نشد، از روی خط داخلی دوباره در AD بگرد (عمومی)
        if (!matches.length && phoneMatches.length) {
          matches = findEmailsFromPhoneLines(docs, phoneMatches);
        }
        const extraMatches = searchColleagueExtraInfo(docs, term);
        if (matches.length > 0 || phoneMatches.length > 0) {
          // اگر صریحاً ایمیل خواسته و پیدا شد، ایمیل را برجسته کن؛ داخلی را هم به‌عنوان مکمل بگذار
          const reply = (phoneMatches.length || extraMatches.length || matches.length)
            ? buildColleagueProfileReply(term, phoneMatches, matches, extraMatches)
            : `📧 نتایج جستجو برای «${term}»:\n\n` + matches.map(m => "- " + m).join("\n");
          setMessages([...newMessages, { role: "assistant", content: reply }]);
          if (userId) saveMessage(userId, "assistant", reply);
          logChat("employee_lookup", "deterministic");
          setLoading(false);
          return;
        }
      } catch (e) {
        // بذار جریان عادی AI ادامه پیدا کنه
      }
    }


    // ۳۰ اوت ۲۰۲۶: فقط اسم همکار → داخلی + ایمیل + هر اطلاعات دیگر در اسناد
    if (isLikelyPersonNameQuery(userText)) {
      try {
        const docs = await sbFetch("knowledge_docs?select=id,title,category,content&order=created_at.desc").catch(() => []);
        const term = resolveFollowupSearchTerm(extractGenericNameTerm(userText), messages);
        if (term && term.trim().length >= 2) {
          const phoneMatches = searchPhoneDirectory(docs, term);
          let emailMatches = searchEmployeeDirectory(docs, term);
          // اگر ایمیل با نام فارسی پیدا نشد، از روی خط داخلی دوباره در AD بگرد (عمومی)
          if (!emailMatches.length && phoneMatches.length) {
            emailMatches = findEmailsFromPhoneLines(docs, phoneMatches);
          }
          const extraMatches = searchColleagueExtraInfo(docs, term);
          if (phoneMatches.length || emailMatches.length || extraMatches.length) {
            const reply = buildColleagueProfileReply(term, phoneMatches, emailMatches, extraMatches);
            setMessages([...newMessages, { role: "assistant", content: reply }]);
            if (userId) saveMessage(userId, "assistant", reply);
            logChat("colleague_profile", "deterministic");
            setLoading(false);
            return;
          }
        }
      } catch (e) {
        // ادامه جریان عادی
      }
    }

    // اگه سوال درباره منوی غذا بود، مستقیم و بدون AI از روی سند منو محاسبه کن (چون مدل‌ها در تطبیق تاریخ قابل‌اعتماد نیستن)
    if (isMenuQuery(userText)) {
      try {
        const docs = await sbFetch("knowledge_docs?select=id,title,category,content&order=created_at.desc").catch(() => []);
        const menuDoc = (docs || []).find(d => /غذا|منو|کانتین|ناهار/i.test(((d.title || "") + " " + (d.category || ""))));
        if (menuDoc && menuDoc.content) {
          const relevantSheet = pickRelevantSheet(menuDoc.content) || { title: menuDoc.title, body: menuDoc.content };
          const target = computeMenuTargetInfo(userText);
          const row = extractMenuRowFromSheetBody(relevantSheet.body, target.weekLabel, target.weekdayFa);
          if (row) {
            const reply = formatMenuReply(target, relevantSheet.title, row);
            setMessages([...newMessages, { role: "assistant", content: reply }]);
            if (userId) saveMessage(userId, "assistant", reply);
            logChat("menu_lookup", "deterministic");
            setLoading(false);
            return;
          }
        }
      } catch (e) {
        // اگه چیزی خطا داد، بذار جریان عادی AI ادامه پیدا کنه (با همون جدول تاریخ توی prompt)
      }
    }


    // تاریخ امروز/فردا/دیروز + هفته میلادی — قطعی بدون AI
    if (isDateQuery(userText)) {
      const reply = formatDateReply(userText, uiLang);
      setMessages([...newMessages, { role: "assistant", content: reply }]);
      if (userId) saveMessage(userId, "assistant", reply);
      logChat("date_lookup", "deterministic");
      setLoading(false);
      return;
    }

    // اگه سوال درباره آب و هوا بود، مستقیم از OpenWeatherMap جواب بده (بدون AI)
    if (isWeatherQuery(userText)) {
      const city = extractCity(userText);
      if (city) {
        try {
          const res = await fetchWithFallback(`/weather?city=${encodeURIComponent(city)}`, { method: "GET", signal: abortController.signal });
          const data = await res.json();
          if (data.success) {
            const reply = formatWeatherReply(data);
            setMessages([...newMessages, { role: "assistant", content: reply }]);
            if (userId) saveMessage(userId, "assistant", reply);
            logChat("openweathermap", "weather");
            setLoading(false);
            return;
          }
        } catch (e) {
          // اگه weather API در دسترس نبود، بذار جریان عادی AI ادامه پیدا کنه
        }
      }
    }

    // اخبار روز — قبل از منابع وب تا «اخبار کریپتو» اشتباهاً به Navasan نرود
    // ۳۰ اوت ۲۰۲۶: اگر /news خطا بدهد هرگز به AI نرو (قانون حوزه IT اخبار را رد می‌کند)
    if (isNewsQuery(userText)) {
      try {
        const cat = guessNewsCategory(userText);
        const res = await fetchWithFallback(
          `/news?category=${encodeURIComponent(cat)}&q=${encodeURIComponent(userText)}`,
          { method: "GET", signal: abortController.signal, timeoutMs: 25000 }
        );
        const data = await res.json();
        if (data.success && data.reply) {
          setMessages([...newMessages, { role: "assistant", content: data.reply }]);
          if (userId) saveMessage(userId, "assistant", data.reply);
          logChat("news:" + (data.category || cat), "deterministic");
          setLoading(false);
          return;
        }
        const reply = `⚠️ ${data.error || "الان نتونستم اخبار رو دریافت کنم. چند لحظه دیگه دوباره امتحان کنید."}`;
        setMessages([...newMessages, { role: "assistant", content: reply }]);
        if (userId) saveMessage(userId, "assistant", reply);
        logChat("news_failed", "deterministic");
        setLoading(false);
        return;
      } catch (e) {
        if (e.name === "AbortError") { setLoading(false); return; }
        const reply = "⚠️ الان سرویس اخبار در دسترس نیست (یا بک‌اند آپدیت نشده). چند لحظه دیگر دوباره امتحان کنید.";
        setMessages([...newMessages, { role: "assistant", content: reply }]);
        if (userId) saveMessage(userId, "assistant", reply);
        logChat("news_failed", "deterministic");
        setLoading(false);
        return;
      }
    }

    // اگه سوال با کلیدواژه‌ی یکی از «منابع وب» (پنل مدیریت) مچ شد، محتوای واقعی همون سایت رو
    // بلادرنگ بگیر. برای قیمت‌های Navasan جواب قطعی (بدون AI) برمی‌گرده تا عدد اشتباه ساخته نشه.
    // ۲۳ اوت ۲۰۲۶: اگه چندتا منبع مچ بشن، دیگه فقط بهترین (اولویت ۰) امتحان نمی‌شه — اگه فچش
    // شکست بخوره، یا AI جواب نده، یا AI صادقانه بگه «توی این صفحه پیدا نشد» (یعنی این منبع خاص
    // اون آیتم رو نداره)، سریع می‌ره سراغ منبع بعدی؛ فقط وقتی همه شکست خوردن خطا نشون داده می‌شه.
    try {
      const webSources = await sbFetch("web_sources?order=priority.asc,id.asc").catch(() => []);
      // دلار/تتر/ارز/رمزارز → Navasan اجباری
      // طلای ۱۸ / عیار / گرم → Navasan اول (deterministic روی 18ayar درست است؛ estjt با AI عدد اشتباه می‌داد مثل 881617)
      // سکه / نقره → اولویت ۰ غیر-Navasan اول، Navasan fallback
      const isFxCryptoQ = /دلار|تتر|یورو|پوند|درهم|لیر|حواله|بیت\s*کوین|بیتکوین|bitcoin|btc|اتریوم|رمزارز|ارز\s*دیجیتال/i.test(userText);
      // «طلایی» فامیلی است؛ فقط «طلا» / «طلای ۱۸» کالای قیمتی‌اند
      const isMetalQ = /طلا(?!یی)|سکه|نقره|مثقال|آب\s*شده|آبشده|اونس/i.test(userText);
      const isGold18Q = /طلا(?!یی)|عیار|گرم/i.test(userText) && !/سکه|نقره/i.test(userText);
      const isCoinOrSilverQ = /سکه|نقره/i.test(userText);
      // سوال ترکیبی (فلز + ارز/رمزارز) مثل «قیمت طلا سکه دلار بیت‌کوین» → فقط Navasan همه را یکجا دارد
      const isMixedPriceQ = isFxCryptoQ && isMetalQ;
      const isPriceQ = isFxCryptoQ || isMetalQ;
      // «قیمت» / «نرخ» به‌تنهایی بدون نام ارز/فلز → وارد مسیر منابع وب نشو (وگرنه دلار پیش‌فرض می‌شد)
      const isBarePriceOnly = /^\s*(قیمت|نرخ|چند|چنده)(\s+چ[یه])?\s*[؟?!.]*\s*$/i.test(userText);
      let matchedSources = isBarePriceOnly ? [] : matchWebSource(userText, webSources);
      const byId = (a, b) => (a.id ?? a.url) === (b.id ?? b.url);
      // ضایعات آهن → فقط/اول iranzayeat.com (دقیق‌تر از tgju نقره)
      const isScrapQ = /ضایعات|قراضه|آهن\s*قراضه|iron\s*scrap/i.test(userText);
      if (isScrapQ && webSources?.length) {
        const scrapSources = webSources.filter((s) =>
          /iranzayeat|ضایعات/i.test((s.url || "") + " " + (s.label || "") + " " + (s.keywords || ""))
        );
        if (scrapSources.length) {
          matchedSources = [
            ...scrapSources,
            ...matchedSources.filter((s) => !scrapSources.some((x) => byId(x, s))),
          ];
        }
        // حذف منابع نقره/tgju silver از لیست ضایعات
        matchedSources = matchedSources.filter((s) => {
          const blob = ((s.url || "") + " " + (s.label || "")).toLowerCase();
          if (/silver|نقره/.test(blob) && !/ضایعات|iranzayeat/.test(blob)) return false;
          return true;
        });
      }
      // Navasan اول: ارز/رمزارز، طلای ۱۸، نقره، یا ترکیب فلز+ارز (نقره = تومان/گرم از silver)
      const isSilverQ = /نقره/i.test(userText) && !isScrapQ;
      if ((isFxCryptoQ || isGold18Q || isMixedPriceQ || isSilverQ) && webSources?.length) {
        const navasan = webSources.find(s => (s.url || "").includes("navasan.tech"));
        if (navasan) matchedSources = [navasan, ...matchedSources.filter(s => !byId(s, navasan))];
      }
      // سکه خالص (بدون دلار/رمزارز و بدون نقره) → اولویت ۰ غیر-Navasan اول، بعد Navasan
      if (isCoinOrSilverQ && !isFxCryptoQ && !isSilverQ && webSources?.length) {
        const nonNav = webSources.filter(s => !(s.url || "").includes("navasan.tech"));
        const metalMatches = matchWebSource(userText, nonNav.length ? nonNav : webSources);
        if (metalMatches.length > 0) {
          matchedSources = [...metalMatches, ...matchedSources.filter(s => !metalMatches.some(m => byId(m, s)))];
        } else if (nonNav.length) {
          const fallbackMetal = [...nonNav].sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0))[0];
          matchedSources = [fallbackMetal, ...matchedSources.filter(s => !byId(s, fallbackMetal))];
        }
      }
      for (let msIdx = 0; msIdx < matchedSources.length; msIdx++) {
        const matchedSource = matchedSources[msIdx];
        const isLastCandidate = msIdx === matchedSources.length - 1;
        let content = matchedSource.last_content;
        let fetchedAt = matchedSource.last_fetched_at;
        let deterministicReply = null;
        // همیشه fresh برای قیمت و ضایعات (کش خالی/ناقص باعث «پیدا نشد» تکراری می‌شد)
        if (isWebSourceStale(matchedSource) || isPriceQ || isScrapQ) {
          const fresh = await fetchAndCacheWebSource(matchedSource, userText, abortController.signal);
          if (fresh && (fresh.content || "").trim()) {
            content = fresh.content;
            fetchedAt = fresh.fetched_at;
            deterministicReply = fresh.deterministic_reply || null;
          }
        }
        // ضایعات: اول از خود متن صفحه ردیف قیمت را دربیاور — وابسته به AI نباش
        if (isScrapQ && (content || "").trim()) {
          const scrapLines = extractRelevantPriceLines(content, userText);
          if (scrapLines.length >= 1) {
            const reply = formatScrapReply(scrapLines, matchedSource, fetchedAt);
            setMessages([...newMessages, { role: "assistant", content: reply }]);
            if (userId) saveMessage(userId, "assistant", reply);
            logChat("scrap_lines", "deterministic");
            setLoading(false);
            return;
          }
        }
        // جواب قطعی Navasan — بدون AI
        if (deterministicReply) {
          const reply = `${deterministicReply}\n\n—\nمنبع: ${matchedSource.label} (${matchedSource.url})\nساعت دریافت اطلاعات: ${formatFetchTime(fetchedAt)}`;
          setMessages([...newMessages, { role: "assistant", content: reply }]);
          if (userId) saveMessage(userId, "assistant", reply);
          logChat("web_source_deterministic:" + matchedSource.label, "deterministic");
          setLoading(false);
          return;
        }
        if (!content) {
          if (stoppedByUserRef.current) { setLoading(false); return; }
          if (!isLastCandidate) continue; // برو سراغ منبع بعدی (اولویت پایین‌تر)
          const reply = `⚠️ الان نتونستم اطلاعات «${matchedSource.label}» رو از سایت بخونم. لطفاً چند لحظه دیگه دوباره امتحان کنید یا مستقیم به آدرس زیر مراجعه کنید:\n${matchedSource.url}`;
          setMessages([...newMessages, { role: "assistant", content: reply }]);
          if (userId) saveMessage(userId, "assistant", reply);
          logChat("web_source_fetch_failed", "deterministic");
          setLoading(false);
          return;
        }
        const wsSystemPrompt =
          "تو داری بر اساس محتوای واقعیِ همین الانِ یک صفحه‌ی وب به سوال کاربر جواب می‌دی. فقط و فقط از متن زیر استفاده کن؛ " +
          "هیچ عدد یا اطلاعاتی از حافظه‌ی خودت یا حدس اضافه نکن. اگه جواب دقیق سوال کاربر توی این متن نبود، صادقانه بگو توی " +
          "این صفحه پیدا نشد. جواب رو کوتاه و مستقیم بده: عدد + واحد، در یک یا دو خط.\n\n" +
          "قوانین قطعی واحد و انتخاب عدد:\n" +
          "۱) طلا / طلای ۱۸ / گرم طلا → قیمت «طلای ۱۸ عیار (هر گرم)» به تومان. عدد کامل را بنویس.\n" +
          "۲) سکه / سکه امامی / تمام / طرح جدید → قیمت «سکه امامی» به تومان (معمولاً صدها میلیون). هرگز قیمت دلار را به‌جای سکه نده.\n" +
          "۳) دلار / تتر → به تومان.\n" +
          "۴) بیت‌کوین و رمزارزها (به‌جز تتر) → به دلار. اگر هم تومان و هم دلار بود فقط دلار را بده.\n" +
          "۵) هرگز عدد ناقص یا بدون واحد نده. هرگز از حافظه عدد نساز.\n\n" +
          `=== محتوای صفحه (${matchedSource.label} — ${matchedSource.url}) ===\n${content}`;
        const wsApiMsgs = newMessages.slice(-6).map(m => ({ role: m.role, content: m.content }));
        try {
          const res = await fetchWithFallback("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ messages: wsApiMsgs, system_prompt: wsSystemPrompt, force_lmstudio: forceLocalAI, provider_order: providerOrder }),
            timeoutMs: 70000,
            signal: abortController.signal,
          });
          const data = await res.json();
          if (res.ok && data.reply) {
            const replyText = cleanText(data.reply);
            // اگه AI گفت پیدا نشد، یا برای طلا عدد غیرواقعی (< ۱ میلیون) داد، منبع بعدی را امتحان کن
            if (looksLikeSuspiciousGoldPrice(replyText, userText) && !isLastCandidate) { continue; }
            if (looksLikeWebSourceNotFound(replyText)) {
              const recovered = extractRelevantPriceLines(content, userText);
              if (recovered.length > 0) {
                const reply = recovered.join("\n") + "\n\n—\nمنبع: " + (matchedSource.label || matchedSource.url) + (matchedSource.url ? " (" + matchedSource.url + ")" : "") + "\nساعت دریافت اطلاعات: " + formatFetchTime(fetchedAt);
                setMessages([...newMessages, { role: "assistant", content: reply }]);
                if (userId) saveMessage(userId, "assistant", reply);
                logChat("web_source_lines", "deterministic");
                setLoading(false);
                return;
              }
              if (!isLastCandidate) continue;
            }
            const reply = `${replyText}\n\n—\nمنبع: ${matchedSource.label} (${matchedSource.url})\nساعت دریافت اطلاعات: ${formatFetchTime(fetchedAt)}`;
            setMessages([...newMessages, { role: "assistant", content: reply }]);
            if (userId) saveMessage(userId, "assistant", reply);
            logChat("web_source:" + matchedSource.label, "ai");
            setLoading(false);
            return;
          }
        } catch (e) {
          if (e.name === "AbortError") { setLoading(false); return; }
          // وگرنه (اگه منبع بعدی هست) برو سراغش؛ وگرنه پایین یه پیام خطای صریح نشون داده می‌شه
        }
        if (!isLastCandidate) continue; // اولویت بعدی رو امتحان کن
        const reply = `⚠️ الان نتونستم بر اساس اطلاعات «${matchedSource.label}» جواب بدم. لطفاً دوباره امتحان کنید.`;
        setMessages([...newMessages, { role: "assistant", content: reply }]);
        if (userId) saveMessage(userId, "assistant", reply);
        logChat("web_source_ai_failed", "deterministic");
        setLoading(false);
        return;
      }
    } catch (e) {
      // اگه خوندن web_sources خطا داد، بذار جریان عادی AI ادامه پیدا کنه
    }

    try {
      const { prompt: systemPrompt, qaList } = await buildSystemPrompt(userText);

      // اول چک کن سوال اختصاصی داره یا نه
      const exactAnswer = findExactQA(userText, qaList);
      if (exactAnswer) {
        setMessages([...newMessages, { role: "assistant", content: exactAnswer }]);
        if (userId) saveMessage(userId, "assistant", exactAnswer);
        logChat("custom_qa", "database");
        setLoading(false);
        return;
      }

      // پیام کوتاه → context بیشتر بفرست
      const wordCount = userText.trim().split(/\s+/).length;
      const isShortMsg = wordCount <= 3;
      const contextCount = isShortMsg ? 14 : 6;
      const apiMsgs = newMessages.slice(-contextCount).map(m => ({ role: m.role, content: m.content }));

      // اگه پیام خیلی کوتاه بود و هیچ context قبلی IT نداشت، از کاربر بخواه سوالش رو کامل کنه
      const ambiguousWords = ["no", "yes", "آره", "نه", "خیر", "بله", "اوکی", "ok", "okay", "ها", "نه نه", "یا", "آوکی", "ممنون", "مرسی", "باشه", "چشم", "اوکیه", "یس", "نوپ", "nope", "yep", "yup"];
      const isAmbiguous = ambiguousWords.includes(userText.trim().toLowerCase());
      const hasPrevContext = newMessages.slice(-6, -1).some(m => m.role === "assistant" && m.content.length > 50);
      if (isAmbiguous && !hasPrevContext) {
        const msg = "لطفاً سوال خود را کامل‌تر بنویسید تا بتوانم بهتر کمک کنم. 😊";
        setMessages([...newMessages, { role: "assistant", content: msg }]);
        if (userId) saveMessage(userId, "assistant", msg);
        setLoading(false);
        return;
      }

      // اگه پیام ambiguous بود و context داشت، به AI بگو این جواب سوال قبلیه
      let finalMessages = apiMsgs;
      if (isAmbiguous && hasPrevContext) {
        const lastAssistantMsg = [...newMessages].slice(0, -1).reverse().find(m => m.role === "assistant");
        if (lastAssistantMsg && lastAssistantMsg.content.includes("؟")) {
          // آخرین پیام assistant سوال داشته — یه hint اضافه کن
          finalMessages = [
            ...apiMsgs.slice(0, -1),
            { role: "user", content: `[پاسخ به سوال قبلی شما]: ${userText}` }
          ];
        }
      }
      const res = await fetchWithFallback("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: finalMessages, system_prompt: systemPrompt, force_lmstudio: forceLocalAI, provider_order: providerOrder }),
        // ⏱️ چهارم اوت ۲۰۲۶: با شناسه‌ی rid توی بک‌اند دیدیم بعضی جواب‌های موفق واقعی ۶۰ تا ۹۶
        // ثانیه طول کشیدن (نه به‌خاطر timeout هر provider، بلکه ازدحام CPU/شبکه‌ی رایگان HF وقتی
        // چند درخواست هم‌زمان میان). با timeoutMs قبلی (۴۵s) + retries:1 این اتفاق می‌افتاد:
        // فرانت‌اند در ۴۵ ثانیه تسلیم می‌شد و «خطا در اتصال» نشون می‌داد، بعد یه تلاش دوم می‌فرستاد —
        // در حالی که تلاش اول داشت پشت صحنه به یه جواب واقعی می‌رسید! این هم به کاربر خطای دروغین
        // نشون می‌داد، هم با ارسال دو درخواست هم‌زمان روی همون ۳ کلید Groq، rate limit رو بدتر می‌کرد.
        // راه‌حل: به یه تلاش با سقف واقع‌بینانه‌تر (۷۰ ثانیه) برگشتیم و retry خودکار رو برداشتیم.
        // ⏱️ نهم اوت ۲۰۲۶: وقتی «فقط هوش مصنوعی محلی» فعاله، بک‌اند تا ۹۰ ثانیه منتظر جواب VM
        // می‌مونه (بخش LM Studio Relay رو ببین) — سقف اینجا رو به ۱۰۰ ثانیه بردیم تا زودتر از
        // بک‌اند خودش تسلیم نشه.
        timeoutMs: forceLocalAI ? 130000 : 70000,
        signal: abortController.signal,
      });
      const data = await res.json();
            if (!res.ok || !data.reply) throw new Error(data?.error || "خطا از سرور");
      const reply = cleanText(data.reply);
      const outOfScope = isOutOfScopeReply(reply);
      // منبع فقط زیر جواب‌های واقعی AI نشون داده میشه، نه زیر پیام امتناع (که خودش گویاست)
      const replyWithSource = outOfScope ? reply : `${reply}\n\n—\nمنبع: ${sourceLabel(data.source)}`;
      setMessages([...newMessages, { role: "assistant", content: replyWithSource }]);
      if (userId) saveMessage(userId, "assistant", replyWithSource);
      logChat(outOfScope ? "out_of_scope" : (data.source || "ai"), "ai");
    } catch (err) {
      // ۱۸ اوت ۲۰۲۶: اگه کاربر خودش با دکمه‌ی «توقف» درخواست رو لغو کرده، دکمه همون لحظه‌ی کلیک
      // (نه اینجا، که ممکنه دیر برسه) پیام رو اضافه کرده — دوباره اضافه نکن. برای خطاهای واقعی
      // (نه لغو کاربر)، همون پیام قبلی «خطا در اتصال» نشون داده می‌شه.
      if (err.name !== "AbortError") {
        setMessages([...newMessages, { role: "assistant", content: isEn ? `⚠️ Connection error: ${err.message}` : `⚠️ خطا در اتصال: ${err.message}` }]);
      }
    } finally { setLoading(false); }
  };

  const handleAdminLogin = async () => {
    try {
      const res = await fetchWithFallback("/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: adminPass })
      });
      if (res.ok) {
        setShowAdminLogin(false);
        setShowAdminPanel(true);
        setAdminPass("");
        setAdminError("");
      } else {
        setAdminError("پسورد اشتباه است");
      }
    } catch {
      setAdminError("خطا در اتصال به سرور");
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", maxHeight: "-webkit-fill-available", background: "#f0f2f5", fontFamily: "'Segoe UI', Tahoma, sans-serif", direction: isEn ? "ltr" : "rtl", overflow: "hidden" }}>
      <div style={{ background: "linear-gradient(135deg, #0078d4, #005a9e)", color: "white", padding: "16px 20px", display: "flex", alignItems: "center", gap: "12px", boxShadow: "0 2px 8px rgba(0,0,0,0.2)" }}>
        <div style={{ width: 42, height: 42, borderRadius: "50%", background: "rgba(255,255,255,0.2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22 }}>🖥️</div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 17 }}>{isEn ? "Nutricia-MMP IT AI Assistant" : "دستیار هوش مصنوعی واحد IT شرکت Nutricia-MMP"}</div>
          <div style={{ fontSize: 12, opacity: 0.85 }}>{isEn ? "Smart IT support • Online" : "پشتیبانی هوشمند فناوری اطلاعات • آنلاین"}</div>
        </div>
        <button onClick={async () => {
          setMessages([WELCOME(uiLang)]);
          try { sessionStorage.removeItem("it_assistant_messages"); } catch {}
          if (userId) {
            try { await sbFetch(`chat_history?user_id=eq.${encodeURIComponent(userId)}`, { method: "DELETE" }); } catch {}
          }
        }} style={{ marginRight: "auto", background: "rgba(255,255,255,0.15)", border: "1px solid rgba(255,255,255,0.3)", color: "white", padding: "4px 10px", borderRadius: 16, cursor: "pointer", fontSize: 11, fontWeight: 600, fontFamily: "inherit" }}>{isEn ? "🗑️ Clear chat" : "🗑️ پاک کردن چت"}</button>
        <button onClick={() => { setShowAnnouncements(true); loadAnnouncements(); }} style={{ background: "rgba(255,255,255,0.15)", border: "1px solid rgba(255,255,255,0.3)", color: "white", padding: "4px 10px", borderRadius: 16, cursor: "pointer", fontSize: 11, fontWeight: 600, fontFamily: "inherit" }}>{isEn ? `📢 Announcements${announcements.length > 0 ? ` (${announcements.length})` : ""}` : `📢 اطلاعیه‌ها${announcements.length > 0 ? ` (${announcements.length})` : ""}`}</button>
        {/* ۱۸ اوت ۲۰۲۶: نسخه‌ی position:absolute یه فاصله‌ی سفید بالای کادر آبی ایجاد می‌کرد (احتمالاً
            به‌خاطر تداخل با اسکرول/استکینگ کانتینر بیرونی). حالا Login عضو عادی همون ردیف flex
            هدره (نه absolute) — با alignSelf:flex-start فقط بالای همون ردیف (نه وسط‌چین مثل بقیه)
            قرار می‌گیره، پس همیشه داخل کادر آبی، دقیقاً گوشه‌ی بالا-چپش می‌مونه. */}
        <span
          onClick={toggleUiLang}
          title={isEn ? "Switch to Persian" : "Switch to English"}
          style={{ alignSelf: "flex-start", fontSize: 11, color: "rgba(255,255,255,0.95)", background: "rgba(255,255,255,0.18)", border: "1px solid rgba(255,255,255,0.35)", borderRadius: 12, padding: "2px 8px", cursor: "pointer", flexShrink: 0, fontWeight: 700 }}
        >{isEn ? "FA" : "EN"}</span>
        <span
          onClick={() => setShowAdminLogin(true)}
          title={isEn ? "Admin login" : "ورود مدیر"}
          style={{ alignSelf: "flex-start", fontSize: 11, color: "rgba(255,255,255,0.6)", textDecoration: "underline", cursor: "pointer", flexShrink: 0 }}
        >Login</span>
      </div>

      {buttons.length > 0 && (
        <div style={{ background: "#fff", borderBottom: showQuickButtons ? "1px solid #e0e0e0" : "none" }}>
          <div
            onClick={() => setShowQuickButtons(v => !v)}
            title={showQuickButtons ? "پنهان کردن دکمه‌های سریع" : "نمایش دکمه‌های سریع"}
            style={{ display: "flex", justifyContent: "center", alignItems: "center", padding: "3px 0", cursor: "pointer", color: "#8a8a8a", background: "#fafbfc", borderBottom: "1px solid #eee" }}
          >
            <span style={{ fontSize: 12, transition: "transform 0.2s", transform: showQuickButtons ? "rotate(0deg)" : "rotate(180deg)" }}>▲</span>
          </div>
          {showQuickButtons && (
            <div style={{ padding: "clamp(4px,1vw,7px) clamp(8px,2vw,12px)", display: "flex", gap: "clamp(3px,0.7vw,6px)", flexWrap: "wrap" }}>
              {buttons.map((q) => (
                <button key={q.id} onClick={() => sendButtonMessage(q.question)} style={{ padding: "clamp(2px,0.5vw,4px) clamp(6px,1.2vw,9px)", borderRadius: 16, border: "1px solid #0078d4", background: "white", color: "#0078d4", cursor: "pointer", fontSize: "clamp(9px,1.2vw,10.5px)", fontWeight: 600, fontFamily: "inherit", whiteSpace: "nowrap" }}
                  onMouseEnter={e => { e.target.style.background = "#0078d4"; e.target.style.color = "white"; }}
                  onMouseLeave={e => { e.target.style.background = "white"; e.target.style.color = "#0078d4"; }}
                >{q.label}</button>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden", WebkitOverflowScrolling: "touch", touchAction: "pan-y", padding: "20px 16px", display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
        {messages.map((msg, i) => (
          <div key={i} style={{ display: "flex", justifyContent: msg.role === "user" ? "flex-start" : "flex-end", alignItems: "flex-end", gap: 8 }}>
            {msg.role === "assistant" && <div style={{ width: 32, height: 32, borderRadius: "50%", background: "#0078d4", color: "white", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, flexShrink: 0 }}>🖥️</div>}
            <div style={{ maxWidth: "72%", padding: "10px 14px", borderRadius: msg.role === "user" ? "18px 18px 18px 4px" : "18px 18px 4px 18px", background: msg.role === "user" ? "#0078d4" : "#ffffff", color: msg.role === "user" ? "white" : "#1a1a1a", boxShadow: "0 1px 4px rgba(0,0,0,0.1)", fontSize: 14, lineHeight: 1.7, whiteSpace: "pre-wrap", direction: isLatinText(msg.content) ? "ltr" : "rtl", textAlign: isLatinText(msg.content) ? "left" : "right" }}>{msg.role === "user" ? msg.content : renderMessage(msg.content)}</div>
            {msg.role === "user" && <div style={{ width: 32, height: 32, borderRadius: "50%", background: "#6c757d", color: "white", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, flexShrink: 0 }}>👤</div>}
          </div>
        ))}
        {loading && (
          <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8 }}>
            <button
              onClick={stopGeneration}
              title="توقف پاسخ"
              style={{ width: 20, height: 20, padding: 0, border: "none", background: "transparent", color: "#999", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: 15, flexShrink: 0 }}
            >⏹️</button>
            <div style={{ width: 32, height: 32, borderRadius: "50%", background: "#0078d4", color: "white", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>🖥️</div>
            <div style={{ padding: "12px 16px", borderRadius: "18px 18px 4px 18px", background: "white", boxShadow: "0 1px 4px rgba(0,0,0,0.1)", display: "flex", gap: 4, alignItems: "center" }}>
              {[0, 1, 2].map(j => <div key={j} style={{ width: 8, height: 8, borderRadius: "50%", background: "#0078d4", opacity: 0.6, animation: `bounce 1.2s ease-in-out ${j * 0.2}s infinite` }} />)}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div style={{ padding: "12px 16px", background: "#fff", borderTop: "1px solid #e0e0e0", display: "flex", gap: 10, alignItems: "flex-end" }}>
        <textarea value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }} placeholder={isEn ? "Type your IT question..." : "سوال IT خود را بنویسید..."} rows={1}
          style={{ flex: 1, padding: "10px 14px", borderRadius: 22, border: "1.5px solid #d0d0d0", outline: "none", resize: "none", fontFamily: "inherit", fontSize: 14, direction: isEn ? "ltr" : "rtl", textAlign: isEn ? "left" : "right", lineHeight: 1.5, maxHeight: 120, overflowY: "auto", transition: "border-color 0.2s" }}
          onFocus={e => e.target.style.borderColor = "#0078d4"} onBlur={e => e.target.style.borderColor = "#d0d0d0"} />
        <button onClick={() => sendMessage()} disabled={!input.trim() || loading} style={{ width: 44, height: 44, borderRadius: "50%", background: input.trim() && !loading ? "#0078d4" : "#ccc", border: "none", cursor: input.trim() && !loading ? "pointer" : "default", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, flexShrink: 0 }}>➤</button>
      </div>

      {showAdminLogin && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 999, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ background: "white", borderRadius: 12, padding: 28, width: 320, direction: "rtl", boxShadow: "0 8px 32px rgba(0,0,0,0.2)" }}>
            <h3 style={{ margin: "0 0 16px", color: "#0078d4" }}>🔐 ورود به پنل مدیریت</h3>
            <input type="password" value={adminPass} onChange={e => setAdminPass(e.target.value)} onKeyDown={e => e.key === "Enter" && handleAdminLogin()} placeholder="پسورد را وارد کنید..."
              style={{ width: "100%", padding: "10px 12px", borderRadius: 8, border: "1.5px solid #ddd", marginBottom: 8, fontFamily: "inherit", fontSize: 14, boxSizing: "border-box" }} />
            {adminError && <p style={{ color: "red", margin: "0 0 8px", fontSize: 13 }}>{adminError}</p>}
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={handleAdminLogin} style={{ flex: 1, padding: 10, background: "#0078d4", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontFamily: "inherit", fontSize: 14 }}>ورود</button>
              <button onClick={() => { setShowAdminLogin(false); setAdminPass(""); setAdminError(""); }} style={{ flex: 1, padding: 10, background: "#6c757d", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontFamily: "inherit", fontSize: 14 }}>انصراف</button>
            </div>
          </div>
        </div>
      )}

      {showAdminPanel && <AdminPanel onClose={() => { setShowAdminPanel(false); loadButtons(); loadForceLocalAI(); loadProviderOrder(); }} onDataChanged={() => { loadButtons(); loadForceLocalAI(); loadProviderOrder(); }} />}

      {showAnnouncements && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: 16 }} onClick={() => setShowAnnouncements(false)}>
          <div style={{ background: "white", borderRadius: 14, width: "100%", maxWidth: 480, maxHeight: "80vh", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 10px 40px rgba(0,0,0,0.3)" }} onClick={e => e.stopPropagation()}>
            <div style={{ background: "linear-gradient(135deg, #0078d4, #005a9e)", color: "white", padding: "16px 20px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontWeight: 700, fontSize: 16 }}>📢 اطلاعیه‌ها</div>
              <button onClick={() => setShowAnnouncements(false)} style={{ background: "transparent", border: "none", color: "white", fontSize: 20, cursor: "pointer", lineHeight: 1 }}>×</button>
            </div>
            <div style={{ overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
              {announcements.length === 0 && <p style={{ color: "#999", textAlign: "center", padding: 30 }}>اطلاعیه‌ای ثبت نشده است</p>}
              {announcements.map(item => (
                <div key={item.id} style={{ border: "1px solid #e0e0e0", borderRadius: 10, padding: 14, background: "#fafbfc", minWidth: 0 }}>
                  <div style={{ fontWeight: 700, color: "#0078d4", fontSize: 15, marginBottom: 6 }}>{item.title}</div>
                  <div style={{ fontSize: 14, lineHeight: 1.8, color: "#333", overflowWrap: "anywhere" }}><AnnouncementContentBlock content={item.content} /></div>
                  <div style={{ fontSize: 11, color: "#999", marginTop: 8 }}>{formatPersianDate(item.created_at)}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <style>{`
        * { box-sizing: border-box; }
        html, body { height: 100%; margin: 0; padding: 0; overflow: hidden; }
        @keyframes bounce { 0%, 60%, 100% { transform: translateY(0); } 30% { transform: translateY(-6px); } }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #ccc; border-radius: 10px; }
      `}</style>
    </div>
  );
}
