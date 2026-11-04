from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2"
)

documents = [
    "The minimum password length is 13 characters.",
    "Passwords must contain uppercase and lowercase letters.",
    "Passwords must contain at least one number.",
    "Employees must change their password every 90 days.",
    "Access to company systems requires authentication."
]

# Create document embeddings
embeddings = model.encode(documents)
embeddings = np.array(embeddings).astype("float32")

# Create FAISS database
dimension = embeddings.shape[1]
index = faiss.IndexFlatL2(dimension)
index.add(embeddings)

# User question
question = "How many characters should the password be?"

# Convert question to vector
question_embedding = model.encode([question])
question_embedding = np.array(question_embedding).astype("float32")

# Search
distances, results = index.search(question_embedding, k=2)

print("\nQuestion:")
print(question)

print("\nRelevant documents:")

for i in results[0]:
    print("-", documents[i])
