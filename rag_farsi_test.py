import os
os.environ.setdefault("OMP_NUM_THREADS", "1")

from sentence_transformers import SentenceTransformer

import faiss
import numpy as np
import pickle


index = faiss.read_index("database/documents.index")

with open("database/documents.pkl", "rb") as file:
    chunks = pickle.load(file)

model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    device="mps"
)

questions = [
    "مرخصی سالانه چند روز است؟",
    "ساعت کاری جمعه چطوره؟",
    "چند روز میتونم دورکاری کنم؟",
    "رمز عبور باید چند کاراکتر باشه؟",
]

question_embeddings = np.array(model.encode(questions)).astype("float32")

distances, results = index.search(question_embeddings, k=1)

correct = 0
expected = ["leave", "working", "remote", "password"]

for question, best, dist, exp in zip(questions, results[:, 0], distances[:, 0], expected):

    chunk = chunks[best]
    hit = exp in chunk["source"]
    correct += hit

    print(("OK " if hit else "WRONG"), "|", question)
    print("   ->", chunk["source"], f"(dist={float(dist):.2f})")

print(f"\nAccuracy: {correct}/{len(questions)}")
