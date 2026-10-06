"""Exa adapter behind WebEvidenceProvider. Never exposed to tutor prompts."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from .config import WebEvidenceConfig
from .models import (
    PolicyDecision,
    ProviderError,
    ProviderOpenResult,
    ProviderSearchHit,
    SearchIntent,
    SourceClassification,
)
from ..usage.operations import begin_external, finish_external, rate_liability

_INTENT_INCLUDE_HINTS: dict[SearchIntent, list[str]] = {
    SearchIntent.academic_reference: ["arxiv.org", "scholar.google.com", "edu"],
    SearchIntent.technical_documentation: [],
    SearchIntent.primary_source: [],
}

_DOMAIN_CLASSIFICATION: list[tuple[tuple[str, ...], SourceClassification]] = [
    (("arxiv.org", "acm.org", "ieee.org", "nature.com", "science.org", "nih.gov", "pubmed"), SourceClassification.academic),
    (("gov", "edu"), SourceClassification.primary),  # TLD-ish heuristics applied carefully below
    (("docs.", "developer.", "readthedocs."), SourceClassification.official_documentation),
    (("wikipedia.org", "britannica.com"), SourceClassification.reference),
    (("khanacademy.org", "coursera.org", "edx.org", "mit.edu", "stanford.edu"), SourceClassification.educational),
    (("nytimes.com", "bbc.com", "reuters.com", "apnews.com"), SourceClassification.news),
    (("reddit.com", "quora.com", "stackexchange.com", "stackoverflow.com"), SourceClassification.forum),
]


def classify_domain(domain: str) -> SourceClassification:
    host = domain.lower().strip()
    for needles, label in _DOMAIN_CLASSIFICATION:
        for needle in needles:
            if needle.startswith(".") or "." in needle:
                if host == needle or host.endswith("." + needle) or needle in host:
                    return label
            elif host.endswith("." + needle) or host == needle:
                return label
    if host.endswith(".gov") or host.endswith(".edu"):
        return SourceClassification.primary
    if host.endswith(".io") or "docs." in host:
        return SourceClassification.official_documentation
    return SourceClassification.unknown


def domain_of(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host.lower()


class ExaWebEvidenceProvider:
    provider_name = "exa"

    def __init__(
        self,
        config: WebEvidenceConfig,
        *,
        client: httpx.Client | None = None,
    ):
        self.config = config
        self._client = client
        self._owned_client = client is None

    @property
    def available(self) -> bool:
        return self.config.provider_available

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.config.exa_api_key or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Forma-Learning-WebEvidence/1.0",
        }

    def _http(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.config.timeout_seconds, connect=5.0),
            trust_env=False,
            headers=self._headers(),
        )
        return self._client

    def close(self) -> None:
        if self._owned_client and self._client is not None:
            self._client.close()
            self._client = None

    def _assert_egress(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        allowed = set(self.config.allowed_egress_hosts) | {urlsplit(self.config.exa_base_url).hostname or ""}
        if host not in allowed:
            raise ProviderError("egress_denied", "Outbound retrieval host is not approved.")

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
        *,
        cancel_check=None,
    ) -> dict[str, Any]:
        url = f"{self.config.exa_base_url}{path}"
        self._assert_egress(url)
        # Each HTTP attempt is independently billable, including retries. Exa
        # does not return a monetary receipt, so keep the configured per-call
        # bound held until the attempt ends and settle it as an estimate.
        if path == "/search":
            component = "search"
            rate_name = "OPENLEARN_EXA_USD_PER_SEARCH"
            quantity = {"search_requests": 1}
        elif path == "/contents":
            component = "search"
            rate_name = "OPENLEARN_EXA_USD_PER_CONTENT_PAGE"
            quantity = {"content_page_requests": 1}
        else:
            raise ProviderError("provider_unavailable", "This external retrieval operation is not metered.", retryable=False)
        liability = rate_liability(rate_name, 1, 1)
        attempts = 1 + max(0, self.config.max_retries)
        last_error: Exception | None = None
        for attempt in range(attempts):
            if cancel_check and cancel_check():
                raise ProviderError("cancelled", "Retrieval was cancelled.", retryable=False)
            ticket = begin_external(component, quantity, liability, provider='exa',
                                    model='search' if path == '/search' else 'contents',
                                    provider_rates={'liability_nano_per_request':liability})
            try:
                try:
                    response = self._http().request(
                        method,
                        url,
                        json=body,
                        headers=self._headers(),
                        timeout=httpx.Timeout(self.config.timeout_seconds, connect=self.config.connect_timeout_seconds),
                    )
                finally:
                    # A timeout or dropped connection can still have reached
                    # Exa. Without a provider receipt, retain the full bound.
                    finish_external(ticket, source="estimated")
            except httpx.TimeoutException as exc:
                if cancel_check and cancel_check():
                    raise ProviderError("cancelled", "Retrieval was cancelled.", retryable=False) from exc
                last_error = ProviderError("timeout", "External search timed out.", retryable=True)
                if attempt + 1 >= attempts:
                    raise last_error from exc
                continue
            except httpx.HTTPError as exc:
                if cancel_check and cancel_check():
                    raise ProviderError("cancelled", "Retrieval was cancelled.", retryable=False) from exc
                last_error = ProviderError("network", "External search failed.", retryable=True)
                if attempt + 1 >= attempts:
                    raise last_error from exc
                continue
            if cancel_check and cancel_check():
                raise ProviderError("cancelled", "Retrieval was cancelled.", retryable=False)
            if len(response.content) > self.config.max_response_bytes:
                raise ProviderError("response_too_large", "Provider response exceeded size limits.")
            if response.status_code >= 500:
                last_error = ProviderError(
                    "provider_error",
                    f"External search returned HTTP {response.status_code}.",
                    retryable=True,
                )
                if attempt + 1 >= attempts:
                    raise last_error
                continue
            if response.status_code >= 400:
                raise ProviderError(
                    "provider_error",
                    f"External search returned HTTP {response.status_code}.",
                    retryable=False,
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError("malformed", "External search returned invalid JSON.") from exc
            if not isinstance(payload, dict):
                raise ProviderError("malformed", "External search returned an unexpected payload.")
            return payload
        raise last_error or ProviderError("network", "External search failed.")

    def search(
        self,
        query: str,
        *,
        intent: SearchIntent,
        decision: PolicyDecision,
        cancel_check=None,
    ) -> list[ProviderSearchHit]:
        if not self.available:
            raise ProviderError("provider_unavailable", "Exa is not configured.", retryable=False)
        # Canonical Exa guidance: pick one content view. Prefer highlights for search
        # (token-efficient, query-relevant excerpts). Do not also request text.
        # See https://docs.exa.ai/reference/search-api-guide-for-coding-agents
        body: dict[str, Any] = {
            "query": query,
            "type": "auto",
            "numResults": decision.max_results,
            "contents": {"highlights": True},
        }
        if decision.domain_allowlist:
            hosts = [d for d in decision.domain_allowlist if "." in d]
            if hosts:
                body["includeDomains"] = hosts[:10]
        if decision.domain_denylist:
            hosts = [d for d in decision.domain_denylist if "." in d]
            if hosts:
                body["excludeDomains"] = hosts[:20]
        if not body.get("includeDomains"):
            hints = [h for h in _INTENT_INCLUDE_HINTS.get(intent, []) if "." in h]
            if hints:
                body["includeDomains"] = hints

        payload = self._request("POST", "/search", body, cancel_check=cancel_check)
        results = payload.get("results") or []
        if not isinstance(results, list):
            raise ProviderError("malformed", "External search results were malformed.")

        hits: list[ProviderSearchHit] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            ref = str(item.get("id") or url).strip()
            if not url or not ref:
                continue
            domain = domain_of(url)
            if decision.domain_denylist and domain in set(decision.domain_denylist):
                continue
            if decision.domain_allowlist and domain and domain not in set(decision.domain_allowlist):
                if not any(domain == a or domain.endswith("." + a) for a in decision.domain_allowlist):
                    continue
            highlights = item.get("highlights") or []
            excerpt_parts = [str(h) for h in highlights if h][:5]
            excerpt = " … ".join(excerpt_parts).strip()
            excerpt = excerpt[: decision.max_chars_per_source]
            if not excerpt:
                continue
            score = None
            scores = item.get("highlightScores") or []
            if scores and isinstance(scores[0], (int, float)):
                score = max(0.0, min(1.0, float(scores[0])))
            hits.append(
                ProviderSearchHit(
                    provider_result_ref=ref,
                    title=str(item.get("title") or domain or "Untitled source").strip()[:300],
                    url=url,
                    domain=domain,
                    author=(str(item["author"])[:200] if item.get("author") else None),
                    published_date=(str(item["publishedDate"])[:40] if item.get("publishedDate") else None),
                    excerpt=excerpt,
                    classification=classify_domain(domain),
                    relevance_score=score,
                )
            )
            if len(hits) >= decision.max_results:
                break
        return hits

    def open_result(
        self,
        provider_result_ref: str,
        *,
        focus: str | None,
        decision: PolicyDecision,
        cancel_check=None,
    ) -> ProviderOpenResult:
        if not self.available:
            raise ProviderError("provider_unavailable", "Exa is not configured.", retryable=False)
        # /contents: one content mode. Prefer text for open (broader page body under
        # our char budget). Focus is applied locally after retrieval.
        body: dict[str, Any] = {
            "ids": [provider_result_ref],
            "text": {"maxCharacters": decision.max_chars_per_source},
        }
        payload = self._request("POST", "/contents", body, cancel_check=cancel_check)
        results = payload.get("results") or []
        if not results or not isinstance(results[0], dict):
            raise ProviderError("not_found", "That source could not be retrieved.")
        item = results[0]
        url = str(item.get("url") or "").strip()
        domain = domain_of(url)
        text = str(item.get("text") or "")
        if focus and text:
            lower = text.lower()
            needle = focus.lower()[:80]
            idx = lower.find(needle) if needle else -1
            if idx >= 0:
                start = max(0, idx - 120)
                text = text[start : start + decision.max_chars_per_source]
        excerpt = text.strip()[: decision.max_chars_per_source]
        if not excerpt:
            raise ProviderError("unsupported_content", "That source could not be safely processed.")
        return ProviderOpenResult(
            provider_result_ref=provider_result_ref,
            title=str(item.get("title") or domain or "Untitled source").strip()[:300],
            url=url,
            domain=domain,
            excerpt=excerpt,
            author=(str(item["author"])[:200] if item.get("author") else None),
            published_date=(str(item["publishedDate"])[:40] if item.get("publishedDate") else None),
        )
