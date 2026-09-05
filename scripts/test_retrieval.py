from dpdp_rag import query

qs = [
    "What did the corrigendum G.S.R. 892(E) to the DPDP Rules change?",
    "Corrigendum page 24 line 22 DPDP Rules of this Gazette Official Gazette correction",
    "What corrections were made to the Digital Personal Data Protection Rules 2025 on 10 December 2025?",
    "When were the Chairperson and Members of the Data Protection Board appointed?",
    "How many submissions were received on the draft DPDP Rules and what did stakeholders say?",
]
for q in qs:
    print("Q:", q)
    for h in query.retrieve(q, k=5):
        m = h["meta"]
        print("  %.3f %s | %s" % (h["distance"], m["source"][:62], m["unit"]))
    print()
