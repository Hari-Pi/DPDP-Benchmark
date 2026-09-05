from ollama import Client
from dpdp_rag import config, query

q = "What is the minimum net worth required for Consent Manager registration?"
hits = query.retrieve(q, k=6)
ctx = query.build_context(hits)
client = Client(host="http://localhost:11434")
for model in ["llama3.1:8b", "qwen2.5:7b-instruct"]:
    r = client.chat(model=model, messages=[
        {"role": "system", "content": query.SYSTEM_PROMPT},
        {"role": "user", "content": f"Context:\n\n{ctx}\n\nQuestion: {q}"},
    ], options={"temperature": 0.1})
    print(f"--- {model} ---")
    print(r["message"]["content"][:500])
    print()
