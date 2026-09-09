"""Configuration for the DPDP RAG pipeline."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_DIR = ROOT / "data" / "text"
OFFICIAL_TEXT_DIR = TEXT_DIR / "official"
DB_DIR = ROOT / "chroma_db"
COLLECTION = "dpdp"

EMBED_MODEL = "nomic-embed-text"
CHAT_MODEL = "qwen2.5:7b-instruct"
NUM_CTX = int(os.environ.get("DPDP_NUM_CTX", "5120"))
MAX_OUTPUT_TOKENS = 400   # bounds generation compute per answer

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150
TOP_K = 8
EMBED_BATCH = 8           # small batches: low, steady GPU load
