import arabic_reshaper
from bidi.algorithm import get_display

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer


# ==========================================
# 1. Register Persian font
# ==========================================

pdfmetrics.registerFont(
    TTFont(
        "Vazirmatn",
        "fonts/Vazirmatn-Regular.ttf"
    )
)


# ==========================================
# 2. RTL text helper
# ==========================================

def rtl(text):

    return get_display(
        arabic_reshaper.reshape(text)
    )


style_title = ParagraphStyle(
    "title",
    fontName="Vazirmatn",
    fontSize=18,
    leading=28,
    alignment=2
)

style_body = ParagraphStyle(
    "body",
    fontName="Vazirmatn",
    fontSize=13,
    leading=24,
    alignment=2
)


# ==========================================
# 3. Document builder
# ==========================================

def make_pdf(filename, title, lines):

    doc = SimpleDocTemplate(
        f"documents/{filename}",
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm
    )

    story = []

    story.append(
        Paragraph(
            rtl(title),
            style_title
        )
    )

    story.append(Spacer(1, 20))

    for line in lines:

        story.append(
            Paragraph(
                rtl(line),
                style_body
            )
        )

        story.append(Spacer(1, 10))

    doc.build(story)

    print("Created:", filename)


# ==========================================
# 4. Document 1: Leave policy
# ==========================================

make_pdf(
    "leave_policy.pdf",
    "سیاست مرخصی شرکت",
    [
        "مرخصی سالانه هر کارمند ۲۶ روز کاری است.",
        "حداکثر مرخصی استحقاقی ذخیره شده ۹ روز است و بیشتر از آن سوخت می‌شود.",
        "برای مرخصی بیش از سه روز کاری، باید حداقل یک هفته قبل به مدیر مستقیم اطلاع داده شود.",
        "مرخصی استعلاجی بیش از دو روز نیاز به ارائه گواهی پزشک دارد.",
        "درخواست مرخصی باید در سامانه منابع انسانی ثبت شود.",
    ]
)


# ==========================================
# 5. Document 2: Working hours
# ==========================================

make_pdf(
    "working_hours.pdf",
    "ساعات کاری شرکت",
    [
        "ساعات کاری شرکت از شنبه تا چهارشنبه از ساعت ۸ تا ۱۷ است.",
        "پنجشنبه‌ها ساعت کاری از ۸ تا ۱۳ است.",
        "جمعه‌ها تعطیل رسمی است.",
        "هر کارمند روزانه یک ساعت ناهار و استراحت دارد.",
        "کارمندان می‌توانند تا ۳۰ دقیقه تاخیر ماهانه بدون کسر حقوق داشته باشند.",
    ]
)


# ==========================================
# 6. Document 3: Remote work policy
# ==========================================

make_pdf(
    "remote_work_policy.pdf",
    "سیاست دورکاری",
    [
        "هر کارمند حداکثر دو روز در هفته می‌تواند دورکاری کند.",
        "دورکاری باید یک روز قبل از طریق سامانه منابع انسانی تایید شود.",
        "در روزهای دورکاری، کارمند باید در ساعات کاری در دسترس و آنلاین باشد.",
        "برای دورکاری، اتصال به شبکه شرکت از طریق VPN الزامی است.",
        "کارمندان جدید تا پایان دوره آزمایشی (سه ماه) اجازه دورکاری ندارند.",
    ]
)


print("\nAll documents created!")
