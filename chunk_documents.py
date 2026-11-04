from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import os


# -------------------------
# Read PDF files
# -------------------------

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


# -------------------------
# Create Text Splitter
# -------------------------

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=100
)


# -------------------------
# Create chunks
# -------------------------

chunks = []

for document in documents:

    split_texts = splitter.split_text(
        document["text"]
    )

    for text in split_texts:

        chunks.append({
            "text": text,
            "source": document["source"],
            "page": document["page"]
        })


# -------------------------
# Show results
# -------------------------

print("Total chunks:", len(chunks))

for i, chunk in enumerate(chunks[:10]):

    print("\n====================")

    print("Chunk:", i + 1)

    print("Source:", chunk["source"])

    print("Page:", chunk["page"])

    print(chunk["text"])
