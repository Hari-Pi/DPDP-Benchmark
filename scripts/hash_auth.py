"""Generate PBKDF2 credential entries for the DPDP RAG server's .env.

Run:  python scripts/hash_auth.py [username]
Prompts for the password (hidden). Writes/updates in .env:
  DPDP_USER, DPDP_AUTH_SALT (hex), DPDP_AUTH_HASH (hex)

The plaintext password is never written anywhere.
"""
import getpass
import hashlib
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
ITERATIONS = 600_000


def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else input("Username: ").strip()
    if not username:
        sys.exit("username required")
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        sys.exit("passwords do not match")
    if len(password) < 8:
        sys.exit("password too short (min 8 chars)")

    salt = secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, ITERATIONS)

    entries = {
        "DPDP_USER": username,
        "DPDP_AUTH_SALT": salt.hex(),
        "DPDP_AUTH_HASH": digest.hex(),
    }

    lines = []
    if ENV.exists():
        lines = [l for l in ENV.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.split("=")[0].strip() in entries]
    lines.extend(f"{k}={v}" for k, v in entries.items())
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f".env updated: DPDP_USER={username}, salt+hash written "
          f"(PBKDF2-SHA256, {ITERATIONS} iterations). Plaintext not stored.")


if __name__ == "__main__":
    main()
