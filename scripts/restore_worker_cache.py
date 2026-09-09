#!/usr/bin/env python3
"""Restore the optional Droidian cache before starting Ollama/ingestion."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dpdp_rag.cache import restore


try:
    result = restore()
    print(f"[cache] {result['status']}; downloaded={result['files']} files; index={result['index']}", flush=True)
    model_dir = Path("data/worker-artifacts/cache/ollama/models").resolve()
    if model_dir.is_dir() and any(model_dir.iterdir()):
        print(f"[cache] ollama_models={model_dir}", flush=True)
except Exception as error:  # cache is an optimization, never a hard dependency
    print(f"[cache] unavailable ({error}); continuing with normal setup", flush=True)
