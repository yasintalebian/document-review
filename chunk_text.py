text = """
Password Policy

The minimum password length is 13 characters.

Passwords must contain uppercase and lowercase letters.

Passwords must contain at least one number.
"""

chunk_size = 100

chunks = []

for i in range(0, len(text), chunk_size):
    chunk = text[i:i + chunk_size]
    chunks.append(chunk)

for number, chunk in enumerate(chunks):
    print("CHUNK", number + 1)
    print(chunk)
    print("----------------")
