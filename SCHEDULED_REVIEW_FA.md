# بازنگری خودکار روزانهٔ کتابخانهٔ اسناد

پوشهٔ `references` سامانهٔ بازبینی، کتابخانهٔ نسخهٔ نهایی همهٔ اسناد است؛ هر فایل با نام اصلی خودش (کد سند)، مثل `SMIA.RG.17.Ver2.05.docx`.

روزهای شنبه تا چهارشنبه ساعت ۸ صبح (به وقت تهران)، `scheduled_review.py` دو سند را برمی‌دارد، بازنگری نگارشی را با LLM انجام می‌دهد و خروجی را به کارتابل مدیر پیش‌فرض می‌فرستد. گردش‌کار از همان‌جا مثل قبل ادامه پیدا می‌کند.

## ترتیب و چرخه

- ابتدا سندهایی که هرگز بازنگری نشده‌اند، سپس قدیمی‌ترین بازنگری. در حالت برابر، به ترتیب نام.
- هر سند سالی یک‌بار بازنگری می‌شود (`SCHEDULED_REVIEW_INTERVAL_DAYS=365`). وقتی همه انجام شدند، تا یک سال پس از قدیمی‌ترین بازنگری چیزی فرستاده نمی‌شود.
- اگر سندی خطا بدهد (مثلاً تاریخ‌ها پیدا نشوند یا Track Changes داشته باشد)، ثبت می‌شود و سند بعدی جایگزینش می‌شود. همان سند ۷ روز بعد یا به‌محض تغییر فایل دوباره امتحان می‌شود.
- اگر LLM در دسترس نباشد، اجرا متوقف می‌شود و هیچ سندی خطادار ثبت نمی‌شود.

## پس از تأیید نهایی مدیر

سامانهٔ بازبینی تغییرات ردیابی‌شدهٔ باقی‌مانده را می‌پذیرد و نسخهٔ تمیز را با **همان نام اصلی** در `references` جایگزین می‌کند. نسخهٔ دارای Track Changes برای ممیزی در سامانه می‌ماند. برای رد یک پیشنهاد، آن را در Word رد کنید و پیش از تأیید، نسخهٔ ویرایش‌شده را بارگذاری کنید.

## دستورها

```bash
cd /opt/document-review/app
set -a; source /opt/document-review/config/document-review.env; set +a

# بررسی همهٔ اسناد کتابخانه بدون LLM (تاریخ‌ها، Track Changes)
/opt/document-review/venv/bin/python scheduled_review.py --check

# اجرای بعدی چه چیزی را می‌فرستد؟ (هیچ تغییری نمی‌دهد)
/opt/document-review/venv/bin/python scheduled_review.py --dry-run

# اجرای دستی خارج از زمان‌بندی
systemctl start document-review-scheduled.service
journalctl -u document-review-scheduled.service -n 50 --no-pager
```

وضعیت هر سند (آخرین ارسال، شناسهٔ اجرا، آخرین خطا) در `/opt/document-review/state/scheduled_review.json` نگهداری می‌شود. خروجی‌ها در `/opt/document-review/artifacts/scheduled/` می‌مانند.

تنظیمات اختیاری (در `document-review.env`): `SCHEDULED_REVIEW_PER_RUN` (پیش‌فرض ۲)، `SCHEDULED_REVIEW_INTERVAL_DAYS` (۳۶۵)، `SCHEDULED_REVIEW_RETRY_DAYS` (۷)، `SCHEDULED_REVIEW_LIBRARY`، `SCHEDULED_REVIEW_OUTBOX`.
