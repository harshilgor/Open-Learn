"""Readiness diagnostics without printing credentials or activating paid work."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
load_dotenv(Path(__file__).resolve().parents[1] / '.env')
from backend.app.dictation_routes import configuration


def main():
    required = ['DEEPGRAM_API_KEY', 'OPENLEARN_DICTATION_SECRET',
                'OPENLEARN_DICTATION_USD_PER_MINUTE', 'OPENLEARN_PROVIDER_RATE_VERSION']
    checks = {name: bool(os.getenv(name)) for name in required}
    checks['dictation_enabled'] = os.getenv('OPENLEARN_DICTATION_ENABLED') == 'true'
    checks['secret_length_valid'] = len(os.getenv('OPENLEARN_DICTATION_SECRET', '')) >= 32
    url = urlparse(os.getenv('OPENLEARN_DICTATION_WS_URL', ''))
    loopback = url.scheme == 'ws' and url.hostname in {'127.0.0.1', 'localhost'} and os.getenv('AI_TUTOR_ENV', 'development') not in {'production', 'deployed'}
    checks['public_websocket_configured'] = (url.scheme == 'wss' and bool(url.hostname) or loopback) and url.path == '/v1/dictation/stream'
    try:
        configuration()
        checks['provider_and_usage_configuration_valid'] = True
    except Exception:
        checks['provider_and_usage_configuration_valid'] = False
    print(json.dumps(checks, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
