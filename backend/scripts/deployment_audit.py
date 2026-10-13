"""Read-only public deployment probes. Never retrieves environment secrets."""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx


def probe(client, url):
    started = time.perf_counter()
    try:
        response = client.get(url, follow_redirects=False)
        return {"status": response.status_code, "elapsedMs": round((time.perf_counter() - started) * 1000, 3),
            "contentType": response.headers.get("content-type"),
            "serverTiming": response.headers.get("server-timing"),
            "traceId": response.headers.get("x-openlearn-trace-id")}
    except httpx.HTTPError as error:
        return {"status": 0, "elapsedMs": round((time.perf_counter() - started) * 1000, 3), "error": type(error).__name__}


def public_bundle_origins(client, frontend):
    html = client.get(frontend).text
    paths = re.findall(r'<script[^>]+src="([^"]+)"', html)
    origins = set()
    evidence = []
    for path in paths[:40]:
        if not path.startswith("/_next/"):
            continue
        response = client.get(urljoin(frontend, path))
        if response.status_code != 200:
            continue
        for match in re.finditer(r'https://[a-z0-9-]+\.onrender\.com', response.text):
            origins.add(match.group())
            nearby = response.text[max(0, match.start() - 120):match.end() + 300]
            if "apiBaseUrl" in nearby or "formaDesktop" in nearby or "NEXT_PUBLIC_LEARNING_API_URL" in nearby:
                evidence.append({"asset": path, "origin": match.group(), "nearApiConfiguration": True})
    return {"renderOrigins": sorted(origins), "apiConfigurationEvidence": evidence,
        "note": "An origin in public assets alone is not proof of a browser request; verify runtime routing separately."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--api", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    for value in (args.frontend, args.api):
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
            parser.error("Use public HTTPS origins without credentials/query strings")
    with httpx.Client(timeout=20) as client:
        report = {"observedAt": datetime.now(timezone.utc).isoformat(),
            "frontend": args.frontend, "api": args.api,
            "probes": {path: probe(client, args.api.rstrip('/') + path) for path in ("/health", "/ready", "/release")},
            "frontendAccountProxy": probe(client, args.frontend.rstrip('/') + "/v1/account"),
            "publicAssets": {}}
        try:
            report['publicAssets'] = public_bundle_origins(client, args.frontend)
        except httpx.HTTPError as error:
            report['publicAssets'] = {'available': False, 'error': type(error).__name__}
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
