# ISMS Document Review Agent

این پروژه یک نمونه اولیه برای بازبینی یک سند DOCX در برابر مجموعه‌ای از اسناد تأییدشده ISMS است. هر بار فقط یک سند جدید وارد می‌شود، تناقض‌های آن با مرجع‌های قبلی پیدا می‌شوند، تغییرات پیشنهادی در یک فایل Word با Track Changes ثبت می‌شوند و نتیجه در یک گزارش JSON ذخیره می‌شود. مسیر اصلی این نیاز `corpus_review.py` است. `review_agent.py` مسیر قدیمی مقایسه دو نسخه از یک سند است.

## ویژگی‌ها

- مقایسه قطعی نسخه قدیمی و جدید سند
- تولید فایل DOCX با `w:ins` و `w:del` برای بازبینی انسانی
- گزارش تغییرات با شماره پاراگراف، نوع تغییر و منبع تصمیم
- طبقه‌بندی اختیاری تغییرات با LLM داخلی شرکت
- استفاده از API سازگار با OpenAI بدون قرار دادن credential در کد
- حالت آفلاین برای تولید Track Changes بدون اتصال به مدل
- نگهداری اسناد تأییدشده در پوشه مرجع برای کنترل تناقض بین اسناد

## نصب

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## اتصال به LLM داخلی

فایل `.env.example` را به تنظیمات محیطی سرور تبدیل کنید. مقدار واقعی API key را در GitHub commit نکنید.

```bash
export INTERNAL_LLM_BASE_URL=http://llm-server:8000/v1
export INTERNAL_LLM_MODEL=your-internal-model-name
export INTERNAL_LLM_API_KEY=
```

سرویس باید endpoint زیر را پشتیبانی کند:

```text
POST {INTERNAL_LLM_BASE_URL}/chat/completions
```

## اجرای بازبینی یک سند در برابر اسناد مرجع

```bash
python corpus_review.py review \
  --document incoming/policy-candidate.docx \
  --corpus references \
  --output artifacts/policy-review.docx \
  --report artifacts/policy-consistency.json
```

فایل DOCX خروجی برای بازبینی و قبول یا رد تغییرات در Word آماده است. متن پیشنهادی مدل به‌صورت خودکار وارد سند نمی‌شود و در گزارش JSON ثبت می‌شود تا تصمیم نهایی انسانی باقی بماند.

بعد از بررسی انسانی و تأیید سند، آن را به مجموعه مرجع اضافه کنید:

```bash
python corpus_review.py promote \
  --document approved/policy-final.docx \
  --corpus references
```

فقط سندی که تأیید شده است باید promote شود. بنابراین سندهای بعدی در برابر آخرین نسخه‌های مورد قبول بررسی می‌شوند.

## تست

```bash
pytest -q
```

## وضعیت RAG موجود

اسکریپت‌های اولیه `build_database.py` و `chatbot.py` برای آزمایش RAG روی PDF نگه داشته شده‌اند. مسیر اصلی کنترل تناقض اکنون `corpus_review.py` است. RAG قدیمی هنوز به کنترل دسترسی، نسخه‌بندی سند و لاگ ممیزی سازمانی متصل نیست.
