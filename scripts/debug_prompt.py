from dpdp_rag import query

hits = query.retrieve("According to Rule 8, how long before erasure must a Data Fiduciary inform the Data Principal?", k=8)
ctx = query.build_context(hits)
print(ctx[:6000])
print("....")
print("HAS forty-eight:", "forty-eight" in ctx)
