import chromadb
from ollama import Client
from dpdp_rag import config
from dpdp_rag import query

col = chromadb.PersistentClient(path=str(config.DB_DIR)).get_collection("dpdp")
row = col.get(ids=["rules:FIRST SCHEDULE PART A:0"], include=["documents"])
chunk = row["documents"][0]
print("CHUNK (first 300):", chunk[:300].replace("\n", " "))

client = Client(host="http://localhost:11434")
q = "What is the minimum net worth required for Consent Manager registration?"
for label, ctx in [("single-chunk", chunk),
                   ("single-chunk+label", f"[1] DPDP Rules 2025, FIRST SCHEDULE PART A\n{chunk}")]:
    r = client.chat(model=config.CHAT_MODEL, messages=[
        {"role": "system", "content": query.SYSTEM_PROMPT},
        {"role": "user", "content": f"Context:\n\n{ctx}\n\nQuestion: {q}"},
    ], options={"temperature": 0.1})
    print(f"--- {label} ---")
    print(r["message"]["content"][:300])

