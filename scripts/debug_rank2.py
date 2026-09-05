import numpy as np
import chromadb
from ollama import Client
from dpdp_rag import config

col = chromadb.PersistentClient(path=str(config.DB_DIR)).get_collection("dpdp")
qs = {
    "penalty-security-failure":
        "What is the maximum monetary penalty for a Data Fiduciary's failure to take reasonable security safeguards?",
    "penalty-breach-notice":
        "What is the penalty for failing to notify a personal data breach to the Board?",
    "consultation-submissions":
        "How many responses were received on the draft DPDP Rules consultation?",
}
client = Client(host="http://localhost:11434")
for name, q in qs.items():
    emb = client.embed(model=config.EMBED_MODEL,
                       input=[f"search_query: {q}"])["embeddings"][0]
    got = col.get(include=["documents", "metadatas", "embeddings"])
    scores = []
    for doc, meta, e in zip(got["documents"], got["metadatas"], got["embeddings"]):
        a, b = np.array(e), np.array(emb)
        cos = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
        scores.append((cos, meta["unit"], meta["part"]))
    scores.sort(reverse=True)
    print("==", name)
    for rank, s in enumerate(scores[:40]):
        if s[1] in ("THE SCHEDULE", "summary") and (
                name != "consultation-submissions" or s[2] == 0):
            print(f"   rank {rank}: {s[1]} p{s[2]} cos={s[0]:.4f}")
