import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
env = ROOT / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

LLM = os.environ.get("LLM", "on")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "40"))
COVER_HIGH = float(os.environ.get("COVER_HIGH", "0.6"))
COVER_LOW = float(os.environ.get("COVER_LOW", "0.3"))
MAX_QUESTION = int(os.environ.get("MAX_QUESTION", "500"))
DB_PATH = ROOT / os.environ.get("DB_PATH", "data/log.db")
