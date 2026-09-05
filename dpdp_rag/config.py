"""Configuration for the DPDP RAG pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_DIR = ROOT / "data" / "text"
OFFICIAL_TEXT_DIR = TEXT_DIR / "official"
DB_DIR = ROOT / "chroma_db"
COLLECTION = "dpdp"

EMBED_MODEL = "nomic-embed-text"
CHAT_MODEL = "qwen2.5:7b-instruct"
NUM_CTX = 5120            # reduced from 8192 to cut GPU memory/compute load
MAX_OUTPUT_TOKENS = 400   # bounds generation compute per answer

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150
TOP_K = 8
EMBED_BATCH = 8           # small batches: low, steady GPU load
