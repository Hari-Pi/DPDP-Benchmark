import numpy as np
import chromadb
from ollama import Client
from dpdp_rag import config

col = chromadb.PersistentClient(path=str(config.DB_DIR)).get_collection("dpdp")
client = Client(host="http://localhost:11434")

cases = [
    ("How many responses were received on the draft DPDP Rules consultation?",
     ["6,951", "6,915"]),
    ("What is the maximum monetary penalty for a Data Fiduciary's failure to take reasonable security safeguards?",
     ["two hundred and fifty crore", "security safeguards"]),
]
for q, needles in cases:
    emb = client.embed(model=config.EMBED_MODEL,
                       input=[f"search_query: {q}"])["embeddings"][0]
    got = col.get(include=["documents", "metadatas", "embeddings"])
    scores = []
    for doc, meta, e in zip(got["documents"], got["metadatas"], got["embeddings"]):
        a, b = np.array(e), np.array(emb)
        cos = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
        scores.append((cos, meta["unit"], meta["part"], doc))
    scores.sort(key=lambda s: -s[0])
    print("==", q[:60])
    for needle in needles:
        found = False
        for rank, (cos, unit, part, doc) in enumerate(scores):
            if needle.lower() in doc.lower():
                print(f"   '{needle}' -> rank {rank} | {unit} p{part} cos={cos:.4f}")
                found = True
                break
        if not found:
            print(f"   '{needle}' -> NOT IN CORPUS")
