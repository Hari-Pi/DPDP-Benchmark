import numpy as np
import chromadb
from ollama import Client
from dpdp_rag import config

col = chromadb.PersistentClient(path=str(config.DB_DIR)).get_collection("dpdp")
q = "How does the DPDP Act define personal data?"
emb = Client(host="http://localhost:11434").embed(
    model=config.EMBED_MODEL, input=[q])["embeddings"][0]
got = col.get(include=["documents", "metadatas", "embeddings"])
scores = []
for doc, meta, e in zip(got["documents"], got["metadatas"], got["embeddings"]):
    a, b = np.array(e), np.array(emb)
    cos = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
    scores.append((cos, meta["source"][:25], meta["unit"], meta["part"]))
scores.sort(reverse=True)
print("top 12:")
for s in scores[:12]:
    print("  %.4f %s | %s p%s" % s[0:4])
print()
print("s. 2 chunks:")
for s in scores:
    if s[2] == "s. 2":
        print("  %.4f %s | %s p%s" % s[0:4])
