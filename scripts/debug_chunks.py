import chromadb
from dpdp_rag import config

col = chromadb.PersistentClient(path=str(config.DB_DIR)).get_collection("dpdp")
got = col.get(include=["documents", "metadatas"])
needles = ["two crore", "forty-eight hours", "6,951", "6,915",
           "identifiable by or in relation"]
for n in needles:
    found = 0
    for doc, meta in zip(got["documents"], got["metadatas"]):
        if n.lower() in doc.lower():
            found += 1
            if found <= 3:
                i = doc.lower().index(n.lower())
                print(f"[{n}] {meta['source'][:40]} | {meta['unit']} p{meta['part']}")
                print("   ...", doc[max(0, i-80):i+100].replace(chr(10), " "), "...")
    if not found:
        print(f"[{n}] NOT FOUND in any chunk")
