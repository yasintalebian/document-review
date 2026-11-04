import os
os.environ.setdefault("OMP_NUM_THREADS", "1")

from sentence_transformers import SentenceTransformer

import faiss
import numpy as np
import pickle

from transformers import pipeline


# ==========================================
# 1. Load database
# ==========================================

index = faiss.read_index(
    "database/documents.index"
)

with open(
    "database/documents.pkl",
    "rb"
) as file:

    chunks = pickle.load(file)


print("Loaded chunks:", len(chunks))


# ==========================================
# 2. Load embedding model (multilingual)
# ==========================================

embedding_model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    device="mps"
)


# ==========================================
# 3. Load LLM (prefer 3B, fall back to 0.5B)
# ==========================================

print("\nLoading LLM...")

LLM_MODELS = [
    "Qwen/Qwen2.5-3B-Instruct",
    "Qwen/Qwen2.5-0.5B-Instruct",
]

llm = None

for model_name in LLM_MODELS:

    try:
        llm = pipeline(
            "text-generation",
            model=model_name,
            dtype="bfloat16",
            device="mps"
        )
        print(f"Loaded LLM: {model_name}")
        break
    except Exception as exc:
        print(f"Could not load {model_name}: {exc}")
        continue

if llm is None:
    raise RuntimeError("No LLM model could be loaded.")


# ==========================================
# 4. Search function
# ==========================================

def search_documents(question, k=3):

    question_embedding = embedding_model.encode(
        [question]
    )

    question_embedding = np.array(
        question_embedding
    ).astype("float32")

    distances, results = index.search(
        question_embedding,
        k=k
    )

    found_chunks = []

    for i in results[0]:

        found_chunks.append(
            chunks[i]
        )

    return found_chunks


# ==========================================
# 5. Build prompt
# ==========================================

def build_prompt(question, context_chunks):

    context = ""

    for chunk in context_chunks:

        context += chunk["text"] + "\n"

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful company document assistant. "
                "Answer the user's question using ONLY the provided context. "
                "If the answer is not in the context, say you don't know. "
                "Answer in the same language as the question "
                "(e.g. answer in Persian if the question is in Persian). "
                "Be concise and accurate."
            )
        },
        {
            "role": "user",
            "content": (
                f"Context:\n{context}\n\n"
                f"Question: {question}"
            )
        }
    ]

    return messages


# ==========================================
# 6. Answer function
# ==========================================

def answer_question(question):

    context_chunks = search_documents(question)

    messages = build_prompt(
        question,
        context_chunks
    )

    result = llm(
        messages,
        max_new_tokens=300,
        do_sample=False
    )

    generated = result[0]["generated_text"]

    # The pipeline returns the full chat history,
    # the answer is the last message content

    answer = generated[-1]["content"]

    sources = []

    for chunk in context_chunks:

        source = f"{chunk['source']} (page {chunk['page']})"

        if source not in sources:
            sources.append(source)

    return answer, sources


# ==========================================
# 7. Chat loop
# ==========================================

print("\nCompany Chatbot is ready! (type 'exit' to quit)\n")

while True:

    question = input("You: ")

    if question.strip().lower() in ("exit", "quit"):
        print("Goodbye!")
        break

    if not question.strip():
        continue

    answer, sources = answer_question(question)

    print("\nBot:", answer)
    print("Sources:", ", ".join(sources))
    print()
