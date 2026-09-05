from dpdp_rag import query

for q in ["How long before erasure must a Data Fiduciary inform the Data Principal under Rule 8?",
          "How does the DPDP Act define personal data?",
          "How many days to respond to grievances?"]:
    print("=" * 70)
    print("Q:", q)
    for h in query.retrieve(q, k=8):
        m = h["meta"]
        flag = ""
        for n in ["forty-eight", "seventy-two", "identifiable", "ninety days",
                  "two crore"]:
            if n in h["text"].lower():
                flag += f" [{n}]"
        print(f"  d={h['distance']:.3f} kw={h['kw']:.2f} {m['source'][:38]}"
              f" | {m['unit']} p{m['part']}{flag}")
