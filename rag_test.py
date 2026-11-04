from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
from transformers import pipeline


# -------------------------
# 1. Embedding Model
# -------------------------

embedding_model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2"
)


# -------------------------
# 2. Company Documents
# -------------------------

documents = [
    "The minimum password length is 13 characters.",
    "Passwords must contain uppercase and lowercase letters.",
    "Passwords must contain at least one number.",
    "Employees must change their password every 90 days.",
    "Access to company systems requires authentication."
]


# -------------------------
# 3. Create Embeddings
# -------------------------

embeddings = embedding_model.encode(documents)

embeddings = np.array(
    embeddings
).astype("float32")


# -------------------------
# 4. Create FAISS
# -------------------------

dimension = embeddings.shape[1]

index = faiss.IndexFlatL2(dimension)

index.add(embeddings)


# -------------------------
# 5. User Question
# -------------------------

question = input("Question: ")


# -------------------------
# 6. Search
# -------------------------

question_embedding = embedding_model.encode(
    [question]
)

question_embedding = np.array(
    question_embedding
).astype("float32")


distances, results = index.search(
    question_embedding,
    k=2
)


# -------------------------
# 7. Get Context
# -------------------------

context = ""

for i in results[0]:
    context += documents[i] + "\n"


print("Context:")
print(context)


# -------------------------
# 8. Load LLM
# -------------------------

llm = pipeline(
    "text-generation",
    model="Qwen/Qwen2.5-0.5B-Instruct"
)


# -------------------------
# 9. Create Prompt
# -------------------------

prompt = f"""
You are a company document assistant.

Answer the question ONLY using the provided context.

Context:
{context}

Question:
{question}

Answer:
"""


# -------------------------
# 10. Generate Answer
# -------------------------

result = llm(
    prompt,
    max_new_tokens=100
)

print("\nAnswer:")

print(
    result[0]["generated_text"]
)
