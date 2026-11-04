from sentence_transformers import SentenceTransformer

model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2"
)

text = "The minimum password length is 13 characters."

embedding = model.encode(text)

print(embedding)
print("Number of dimensions:", len(embedding))
