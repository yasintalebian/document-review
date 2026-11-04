from sentence_transformers import SentenceTransformer

import faiss
import numpy as np
import pickle
from runtime_config import EMBEDDING_MODEL, embedding_device


# ==========================================
# Load database
# ==========================================

index = faiss.read_index(
    "database/documents.index"
)


with open(
    "database/documents.pkl",
    "rb"
) as file:

    chunks = pickle.load(file)


# ==========================================
# Load embedding model
# ==========================================

model = SentenceTransformer(
    EMBEDDING_MODEL,
    device=embedding_device()
)


# ==========================================
# Ask question
# ==========================================

question = input("\nQuestion: ")


# ==========================================
# Convert question to vector
# ==========================================

question_embedding = model.encode(
    [question]
)

question_embedding = np.array(
    question_embedding
).astype("float32")


# ==========================================
# Search
# ==========================================

distances, results = index.search(
    question_embedding,
    k=3
)


# ==========================================
# Show results
# ==========================================

print("\nRelevant documents:\n")


for position, index_number in enumerate(results[0]):

    chunk = chunks[index_number]

    print(
        f"Result {position + 1}"
    )

    print(
        "Source:",
        chunk["source"]
    )

    print(
        "Page:",
        chunk["page"]
    )

    print(
        "Text:",
        chunk["text"]
    )

    print(
        "Distance:",
        distances[0][position]
    )

    print(
        "-------------------------"
    )
