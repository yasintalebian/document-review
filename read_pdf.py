from pypdf import PdfReader

reader = PdfReader("documents/password_policy.pdf")

for page in reader.pages:
    text = page.extract_text()
    print(text)