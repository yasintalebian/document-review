# راهنمای استقرار Agent بازبینی اسناد روی سرور تستی

این راهنما برای استقرار نسخه CLI پروژه `document-review` روی یک سرور تستی Linux نوشته شده است. برنامه در وضعیت فعلی یک سرویس HTTP نیست. هر بازبینی با اجرای یک فرمان انجام می‌شود و خروجی آن یک فایل DOCX دارای Track Changes و یک گزارش JSON است.

## پیش‌نیازهای سرور

مقادیر زیر فرض‌های این راهنما هستند و در صورت تفاوت محیط شرکت باید تغییر کنند.

- Ubuntu 22.04 یا 24.04
- Python 3.11 یا 3.12
- دسترسی خروجی Git به GitHub برای دریافت کد
- دسترسی شبکه سرور به endpoint مدل داخلی
- فضای کافی برای محیط Python، مدل embedding و فایل‌های ورودی و خروجی
- یک حساب سرویس جداگانه برای اجرای برنامه

متن واقعی اسناد ISMS و credential مدل داخلی نباید در مخزن عمومی GitHub قرار بگیرد. پوشه‌های ورودی، مرجع و خروجی را خارج از checkout عمومی نگه دارید.

## ساخت حساب و مسیرهای برنامه

با حساب مدیر سرور:

```bash
sudo useradd --system --create-home --home-dir /opt/document-review \
  --shell /usr/sbin/nologin document-review

sudo mkdir -p /opt/document-review/{incoming,approved,references,artifacts,config}
sudo chown -R document-review:document-review /opt/document-review
sudo chmod 750 /opt/document-review/{incoming,approved,references,artifacts,config}
```

اگر چند کاربر از Agent استفاده می‌کنند، دسترسی آن‌ها را از طریق یک گروه محدود سازمانی مدیریت کنید.

## دریافت کد

```bash
sudo -u document-review git clone \
  https://github.com/yasintalebian/document-review.git \
  /opt/document-review/app

cd /opt/document-review/app
```

برای محیط تست، یک commit یا tag مشخص را checkout کنید تا نسخه اجرایی قابل ردیابی باشد:

```bash
sudo -u document-review git checkout 5de7eeca704d7061770355b6de5fd3e1e6436ef7
```

در محیطی که GitHub عمومی از آن قابل دسترسی نیست، سورس را از مسیر داخلی مورد تأیید شرکت منتقل کنید و hash commit را در گزارش استقرار ثبت کنید.

## ساخت محیط Python

```bash
sudo -u document-review python3 -m venv /opt/document-review/venv
sudo -u document-review /opt/document-review/venv/bin/python -m pip install --upgrade pip
sudo -u document-review /opt/document-review/venv/bin/pip install \
  -r /opt/document-review/app/requirements.txt
```

در اولین نصب، مدل embedding ممکن است از منبعی که در محیط شرکت مجاز است دریافت شود. اگر سرور به اینترنت دسترسی ندارد، wheelها و مدل‌ها را از mirror داخلی آماده کنید و مقدار `EMBEDDING_MODEL` را به مسیر مدل محلی تغییر دهید.

## ایجاد baseline و تنظیمات داخلی

فایل baseline نمونه را به فایل محیط تست تبدیل کنید:

```bash
sudo -u document-review cp \
  /opt/document-review/app/standards/iso27001_2022_baseline.example.json \
  /opt/document-review/config/iso27001_2022_baseline.json
```

سپس خلاصه الزامات مجاز شرکت و ارجاع‌های Statement of Applicability را در فایل محیط تست تکمیل کنید. این فایل را در GitHub عمومی commit نکنید.

فایل تنظیمات مدل را بسازید:

```bash
sudo install -o document-review -g document-review -m 640 /dev/null \
  /opt/document-review/config/document-review.env
sudo sh -c 'cat > /opt/document-review/config/document-review.env' <<'EOF'
INTERNAL_LLM_BASE_URL=http://llm-server.internal:8000/v1
INTERNAL_LLM_MODEL=your-internal-model-name
INTERNAL_LLM_API_KEY=
INTERNAL_LLM_TIMEOUT_SECONDS=120
EMBEDDING_DEVICE=cpu
EOF
sudo chown document-review:document-review /opt/document-review/config/document-review.env
sudo chmod 640 /opt/document-review/config/document-review.env
```

مقدار واقعی API key را در shell history، issue، log یا GitHub قرار ندهید. اگر سرویس داخلی با شبکه مجاز احراز هویت می‌شود، API key را خالی بگذارید.

## آماده‌سازی اسناد مرجع

فقط نسخه‌هایی را در `references` قرار دهید که مسئول مربوطه بررسی و تأیید کرده است:

```bash
sudo install -o document-review -g document-review -m 640 \
  approved/policy-final.docx \
  /opt/document-review/references/policy-final.docx
```

نام فایل‌ها را پایدار نگه دارید و نسخه سند، مالک، تاریخ تأیید و محدوده کاربرد را در سیستم مدیریت اسناد سازمان ثبت کنید. خود فایل DOCX مرجع، به‌تنهایی جایگزین ثبت متادیتا و سوابق تأیید نیست.

## اجرای یک بازبینی

یک سند ورودی را در مسیر تست قرار دهید:

```bash
sudo install -o document-review -g document-review -m 640 \
  incoming/policy-candidate.docx \
  /opt/document-review/incoming/policy-candidate.docx
```

سپس بازبینی را اجرا کنید:

```bash
sudo -u document-review sh -c '
  set -a
  . /opt/document-review/config/document-review.env
  set +a
  cd /opt/document-review/app
  /opt/document-review/venv/bin/python corpus_review.py review \
    --document /opt/document-review/incoming/policy-candidate.docx \
    --corpus /opt/document-review/references \
    --iso-baseline /opt/document-review/config/iso27001_2022_baseline.json \
    --output /opt/document-review/artifacts/policy-review.docx \
    --report /opt/document-review/artifacts/policy-review.json
'
```

خروجی‌ها در `artifacts` ایجاد می‌شوند. فایل DOCX باید در Word بررسی شود و وضعیت Track Changes آن به‌صورت دستی تأیید یا رد شود.

بعد از تأیید انسانی، نسخه نهایی را به مرجع‌ها اضافه کنید:

```bash
sudo -u document-review /opt/document-review/venv/bin/python \
  /opt/document-review/app/corpus_review.py promote \
  --document /opt/document-review/approved/policy-final.docx \
  --corpus /opt/document-review/references
```

خودکار کردن `promote` بدون تأیید انسانی توصیه نمی‌شود، چون سند جدید را به مرجع بررسی اسناد بعدی تبدیل می‌کند.

## بررسی اولیه نصب

```bash
sudo -u document-review /opt/document-review/venv/bin/python -m compileall -q \
  /opt/document-review/app

sudo -u document-review /opt/document-review/venv/bin/python -c \
  'from docx import Document; print("python-docx: OK")'

sudo -u document-review sh -c '
  cd /opt/document-review/app
  /opt/document-review/venv/bin/python -c \
    "from iso_review import load_baseline; print(load_baseline(\"/opt/document-review/config/iso27001_2022_baseline.json\")[0])"
'
```

برای تست اتصال مدل، یک بازبینی واقعی با سند آزمایشی اجرا کنید. برنامه برای endpoint داخلی از مسیر زیر استفاده می‌کند:

```text
POST {INTERNAL_LLM_BASE_URL}/chat/completions
```

پاسخ باید شامل `choices[0].message.content` باشد. اگر مدل در دسترس نباشد، برنامه گزارش `needs_evidence` تولید می‌کند و پیشنهاد LLM به سند اضافه نمی‌شود.

## اجرای زمان‌بندی‌شده اختیاری

نسخه فعلی ورودی فایل و خروجی فایل دارد. برای اجرای زمان‌بندی‌شده، یک wrapper داخلی بسازید که فقط فایل‌های جدید را انتخاب کند و قبل از هر اجرا نام فایل، commit، زمان اجرا و hash سند را در لاگ ممیزی ثبت کند. سپس آن wrapper را با systemd timer یا scheduler مورد تأیید شرکت اجرا کنید.

از اجرای هم‌زمان دو بازبینی روی یک پوشه خروجی جلوگیری کنید. برای هر اجرا یک شناسه یا پوشه جدا بسازید تا گزارش‌ها و فایل‌های Word روی هم نوشته نشوند.

## دسترسی شبکه و لاگ‌ها

- دسترسی خروجی سرور را فقط به Git یا mirror داخلی و endpoint مدل داخلی محدود کنید.
- دسترسی ورودی به endpoint مدل را به سرور تستی و حساب سرویس محدود کنید.
- متن کامل اسناد را در log چاپ نکنید.
- logها را در مسیر دارای دسترسی محدود نگه دارید و دوره نگهداری را با سیاست سازمان هماهنگ کنید.
- API key را در systemd unit، command line یا خروجی خطا چاپ نکنید.

## به‌روزرسانی نسخه

قبل از به‌روزرسانی:

1. اجرای جاری را متوقف کنید.
2. خروجی‌ها و گزارش‌های مهم را به محل مجاز منتقل کنید.
3. hash نسخه فعلی و نسخه جدید را ثبت کنید.
4. محیط virtualenv یا lockfile را در صورت تغییر وابستگی‌ها بازسازی کنید.
5. یک سند آزمایشی را اجرا و خروجی DOCX و JSON را بررسی کنید.

در صورت خطا، commit قبلی را checkout کنید و baseline، references و artifacts را جداگانه نگه دارید. rollback کد نباید نسخه سندهای تأییدشده را حذف کند.

## حدود این استقرار

این برنامه یک ابزار کمک‌کار بازبینی است. نتیجه `covered`، `partial` یا `gap` به‌تنهایی گواهی انطباق ISO/IEC 27001 نیست. نتیجه نهایی به دامنه ISMS، ارزیابی ریسک، Statement of Applicability، شواهد اجرایی و بررسی مسئول ISMS یا ممیز وابسته است.
