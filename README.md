# ISMS Document Review Agent

این پروژه یک نمونه اولیه برای بازبینی کنترل‌شده نسخه‌های DOCX است. نسخه جدید با نسخه تأییدشده مقایسه می‌شود، تغییرات در یک فایل Word با Track Changes ثبت می‌شوند و برای هر تغییر یک گزارش JSON تولید می‌شود.

## ویژگی‌ها

- مقایسه قطعی نسخه قدیمی و جدید سند
- تولید فایل DOCX با `w:ins` و `w:del` برای بازبینی انسانی
- گزارش تغییرات با شماره پاراگراف، نوع تغییر و منبع تصمیم
- طبقه‌بندی اختیاری تغییرات با LLM داخلی شرکت
- استفاده از API سازگار با OpenAI بدون قرار دادن credential در کد
- حالت آفلاین برای تولید Track Changes بدون اتصال به مدل

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

## اجرای بازبینی

```bash
python review_agent.py \
  --old samples/policy-approved.docx \
  --new samples/policy-candidate.docx \
  --output artifacts/policy-review.docx \
  --report artifacts/policy-review.json
```

فایل DOCX خروجی برای بازبینی و قبول یا رد تغییرات در Word آماده است. متن پیشنهادی مدل به‌صورت خودکار وارد سند نمی‌شود و در گزارش JSON ثبت می‌شود تا تصمیم نهایی انسانی باقی بماند.

## تست

```bash
pytest -q
```

## وضعیت RAG موجود

اسکریپت‌های اولیه `build_database.py` و `chatbot.py` برای آزمایش RAG روی PDF نگه داشته شده‌اند. آن‌ها هنوز به یکپارچه‌سازی کامل با Agent بازبینی متصل نیستند. برای استفاده سازمانی باید embedding ثابت، device قابل تنظیم، کنترل دسترسی، نسخه‌بندی سند، لاگ ممیزی و آستانه رد نتایج نامرتبط به آن‌ها اضافه شود.
