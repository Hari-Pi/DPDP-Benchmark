"""Command-line chatbot over the DPDP corpus.

Usage:
  python -m dpdp_rag.cli "What is the penalty for a security failure?"
  python -m dpdp_rag.cli --chat
"""
import argparse
import sys

from . import config, query


def print_sources(hits: list[dict]) -> None:
    seen = []
    for h in hits:
        m = h["meta"]
        label = f"{m['source']}, {m['unit']}"
        if label not in seen:
            seen.append(label)
    print("\nSources:")
    for i, label in enumerate(seen, 1):
        print(f"  [{i}] {label}")


def one_shot(args) -> None:
    answer_text, hits = query.answer(args.question, k=args.k, model=args.model)
    print(answer_text)
    if not args.no_sources:
        print_sources(hits)


def chat(args) -> None:
    print(f"DPDP RAG chatbot — model: {args.model}, embeddings: "
          f"{config.EMBED_MODEL}. Type 'exit' to quit.\n")
    history = []
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in {"exit", "quit"}:
            break
        answer_text, hits = query.answer(question, k=args.k, model=args.model,
                                         history=history)
        print(f"\nAssistant: {answer_text}\n")
        if not args.no_sources:
            print_sources(hits)
            print()
        history.extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer_text},
        ])
        history = history[-6:]


def main() -> None:
    p = argparse.ArgumentParser(description="RAG over the DPDP Act and Rules")
    p.add_argument("question", nargs="*", help="one-shot question")
    p.add_argument("--chat", action="store_true", help="interactive mode")
    p.add_argument("--k", type=int, default=config.TOP_K, help="chunks to retrieve")
    p.add_argument("--model", default=config.CHAT_MODEL, help="Ollama chat model")
    p.add_argument("--no-sources", action="store_true", help="hide source list")
    args = p.parse_args()

    if args.chat:
        chat(args)
    elif args.question:
        args.question = " ".join(args.question)
        one_shot(args)
    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
