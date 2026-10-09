"""Start the local API with ignored backend/.env settings loaded first."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / 'backend' / '.env', override=False)

import uvicorn

uvicorn.run('backend.app.main:app', host='127.0.0.1', port=8000)
