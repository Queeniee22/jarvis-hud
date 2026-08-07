import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PORT = 8770

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
VOICE_ID = os.getenv("VOICE_ID", "")
_obsidian_key_raw = os.getenv("OBSIDIAN_API_KEY", "").strip()
# .env may accidentally include a literal "Bearer " prefix; strip it so
# callers always get the bare key and can build "Bearer <key>" themselves.
if _obsidian_key_raw.lower().startswith("bearer "):
    _obsidian_key_raw = _obsidian_key_raw.split(" ", 1)[1]
OBSIDIAN_API_KEY = _obsidian_key_raw
OBSIDIAN_PORT = int(os.getenv("OBSIDIAN_PORT", "27126"))
# Local REST API plugin: HTTP on 27125, HTTPS (self-signed) on 27126.
OBSIDIAN_SCHEME = "https" if OBSIDIAN_PORT == 27126 else "http"
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")

# The Obsidian vault. The brain subprocess runs with this as its cwd so the
# Claude CLI picks up the vault's CLAUDE.md memory protocol and can read and
# write notes with its own tools.
VAULT_PATH = os.getenv("VAULT_PATH", r"C:\Users\Mackenzie\Jarvis")
