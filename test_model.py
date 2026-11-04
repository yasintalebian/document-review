from transformers import pipeline

pipe = pipeline(
    "text-generation",
    model="Qwen/Qwen2.5-0.5B-Instruct"
)

question = "What is ISO 27001?"

result = pipe(question, max_new_tokens=100)

print(result[0]["generated_text"])