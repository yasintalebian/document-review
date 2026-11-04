from pypdf import PdfReader
import os

documents_folder = "documents"

documents = []

for filename in os.listdir(documents_folder):

    if filename.endswith(".pdf"):

        file_path = os.path.join(
            documents_folder,
            filename
        )

        reader = PdfReader(file_path)

        for page_number, page in enumerate(reader.pages):

            text = page.extract_text()

            if text:
                documents.append({
                    "text": text,
                    "source": filename,
                    "page": page_number + 1
                })


print("Number of pages loaded:", len(documents))

for document in documents:

    print("\n--------------------")

    print("Source:", document["source"])

    print("Page:", document["page"])

    print(document["text"][:500])
