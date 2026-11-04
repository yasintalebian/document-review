import os
os.environ.setdefault("OMP_NUM_THREADS", "1")

from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

import faiss
import numpy as np
import os
import pickle
from runtime_config import EMBEDDING_MODEL, embedding_device


# ==========================================
# 1. Settings
# ==========================================

DOCUMENTS_FOLDER = "documents"
DATABASE_FOLDER = "database"


# ==========================================
# 2. Create database folder
# ==========================================

os.makedirs(DATABASE_FOLDER, exist_ok=True)


# ==========================================
# 3. Read PDF documents
# ==========================================

documents = []

for filename in os.listdir(DOCUMENTS_FOLDER):

    if filename.lower().endswith(".pdf"):

        file_path = os.path.join(
            DOCUMENTS_FOLDER,
            filename
        )

        print("Reading:", filename)

        reader = PdfReader(file_path)

        for page_number, page in enumerate(reader.pages):

            text = page.extract_text()

            if text:

                documents.append({
                    "text": text,
                    "source": filename,
                    "page": page_number + 1
                })


print("\nTotal pages:", len(documents))


# ==========================================
# 4. Split documents into chunks
# ==========================================

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=100
)

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


print("Total chunks:", len(chunks))


# ==========================================
# 5. Load Embedding Model
# ==========================================

print("\nLoading embedding model...")

# Multilingual model - much better for Persian documents
embedding_model = SentenceTransformer(
    EMBEDDING_MODEL,
    device=embedding_device()
)


# ==========================================
# 6. Create embeddings
# ==========================================

texts = [
    chunk["text"]
    for chunk in chunks
]

embeddings = embedding_model.encode(
    texts,
    show_progress_bar=True,
    batch_size=32
)

embeddings = np.array(
    embeddings
).astype("float32")


# ==========================================
# 7. Create FAISS index
# ==========================================

dimension = embeddings.shape[1]

index = faiss.IndexFlatL2(
    dimension
)

index.add(embeddings)


print("\nVectors in database:", index.ntotal)


# ==========================================
# 8. Save FAISS database
# ==========================================

faiss.write_index(
    index,
    f"{DATABASE_FOLDER}/documents.index"
)


# ==========================================
# 9. Save document metadata
# ==========================================

with open(
    f"{DATABASE_FOLDER}/documents.pkl",
    "wb"
) as file:

    pickle.dump(
        chunks,
        file
    )


print("\nDatabase created successfully!")
