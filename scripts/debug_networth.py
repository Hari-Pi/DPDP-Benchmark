from dpdp_rag import query

for h in query.retrieve(
        "What is the minimum net worth required for Consent Manager registration?",
        k=6):
    m = h["meta"]
    flag = "[two crore]" if "two crore" in h["text"].lower() else ""
    print("d=%.3f kw=%.2f %s | %s p%s %s" % (h["distance"], h["kw"],
          m["source"][:35], m["unit"], m["part"], flag))
