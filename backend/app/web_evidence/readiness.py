"""Pre-deploy and runtime readiness checks for web evidence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text

from .config import WebEvidenceConfig, load_web_evidence_config
from .retention import RETENTION_STATUS_ID, RETENTION_STATUS_KIND, EvidenceRetention

REQUIRED_TABLES = (
    "web_tool_calls",
    "web_evidence_receipts",
    "web_evidence_aliases",
    "web_quota_ledgers",
    "web_provider_circuit",
)

REQUIRED_INDEXES = {
    "web_evidence_aliases": {"ix_web_alias_auth"},
    "web_evidence_receipts": {"ix_web_receipt_auth"},
    "web_tool_calls": {"ix_web_tool_inflight"},
}


def _env_name() -> str:
    return os.getenv("AI_TUTOR_ENV", "development").strip().lower() or "development"


def is_deployed_env(env: str | None = None) -> bool:
    return (env or _env_name()) in {"production", "deployed"}


def postgres_required_for_enablement(env: str | None = None) -> bool:
    """Web evidence may only be enabled against Postgres in deployed environments.

    Local development and the unit suite may use SQLite with the feature flag for
    FakeWebEvidenceProvider tests. Deployed enablement is fail-closed.
    """
    return is_deployed_env(env)


@dataclass(frozen=True)
class WebEvidenceReadiness:
    feature_flag_enabled: bool
    effective_enabled: bool
    dialect: str
    postgres_ok: bool
    schema_ok: bool
    missing_tables: tuple[str, ...]
    missing_indexes: tuple[str, ...]
    egress_hosts: tuple[str, ...]
    egress_ok: bool
    retention: dict[str, Any]
    blocking_errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "featureFlagEnabled": self.feature_flag_enabled,
            "effectiveEnabled": self.effective_enabled,
            "dialect": self.dialect,
            "postgresOk": self.postgres_ok,
            "schemaOk": self.schema_ok,
            "missingTables": list(self.missing_tables),
            "missingIndexes": list(self.missing_indexes),
            "egressHosts": list(self.egress_hosts),
            "egressOk": self.egress_ok,
            "retention": self.retention,
            "blockingErrors": list(self.blocking_errors),
            "status": "ok" if not self.blocking_errors else "degraded",
        }


def check_schema(store) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    inspector = inspect(store.engine)
    tables = set(inspector.get_table_names())
    missing_tables = tuple(name for name in REQUIRED_TABLES if name not in tables)
    missing_indexes: list[str] = []
    if not missing_tables:
        for table, expected in REQUIRED_INDEXES.items():
            present = {idx["name"] for idx in inspector.get_indexes(table)}
            for name in sorted(expected):
                if name not in present:
                    missing_indexes.append(f"{table}.{name}")
    return (not missing_tables and not missing_indexes), missing_tables, tuple(missing_indexes)


def retention_status(store, *, config: WebEvidenceConfig | None = None) -> dict[str, Any]:
    cfg = config or load_web_evidence_config()
    interval = max(60, int(cfg.retention_interval_seconds))
    row = None
    try:
        with store.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload FROM context_records "
                    "WHERE id=:id AND kind=:kind"
                ),
                {"id": RETENTION_STATUS_ID, "kind": RETENTION_STATUS_KIND},
            ).first()
    except Exception as exc:  # noqa: BLE001 — health must never raise
        return {
            "ok": False,
            "stale": True,
            "lastSuccessAt": None,
            "expectedIntervalSeconds": interval,
            "error": type(exc).__name__,
        }
    if row is None:
        return {
            "ok": False,
            "stale": True,
            "lastSuccessAt": None,
            "expectedIntervalSeconds": interval,
            "error": "never_run",
        }
    import json

    try:
        payload = json.loads(row[0])
    except Exception:
        return {
            "ok": False,
            "stale": True,
            "lastSuccessAt": None,
            "expectedIntervalSeconds": interval,
            "error": "malformed_status",
        }
    last_raw = payload.get("lastSuccessAt")
    last_ok = bool(payload.get("ok", False))
    stale = True
    age_seconds = None
    if last_raw:
        try:
            last = datetime.fromisoformat(str(last_raw))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (datetime.now(timezone.utc) - last).total_seconds())
            # Allow one missed interval before marking stale.
            stale = age_seconds > (interval * 2)
        except Exception:
            stale = True
    return {
        "ok": last_ok and not stale,
        "stale": stale,
        "lastSuccessAt": last_raw,
        "lastStats": payload.get("stats") or {},
        "ageSeconds": age_seconds,
        "expectedIntervalSeconds": interval,
        "error": None if last_ok and not stale else (payload.get("error") or ("stale" if stale else "failed")),
    }


def evaluate_readiness(store, *, config: WebEvidenceConfig | None = None) -> WebEvidenceReadiness:
    cfg = config or load_web_evidence_config()
    dialect = store.engine.dialect.name
    postgres_ok = dialect == "postgresql"
    schema_ok, missing_tables, missing_indexes = check_schema(store)
    egress = tuple(cfg.allowed_egress_hosts)
    egress_ok = bool(egress) and set(egress) <= {"api.exa.ai"}
    retention = retention_status(store, config=cfg)

    hard_errors: list[str] = []
    advisory: list[str] = []
    effective = bool(cfg.enabled)
    if cfg.enabled and postgres_required_for_enablement() and not postgres_ok:
        effective = False
        hard_errors.append("web_evidence_requires_postgresql")
    if cfg.enabled and not schema_ok:
        effective = False
        hard_errors.append("web_evidence_schema_incomplete")
    if cfg.enabled and not egress_ok:
        effective = False
        hard_errors.append("web_evidence_egress_not_approved")
    if cfg.enabled and cfg.provider_name == "exa":
        try:
            from ..usage.policy import Policy
            usage_policy=Policy.load()
            if not usage_policy.paid or not usage_policy.provider_rate_version:
                raise RuntimeError("usage rates disabled")
        except Exception:
            effective = False
            hard_errors.append("web_evidence_usage_metering_unavailable")
    if cfg.enabled and retention.get("stale"):
        advisory.append("web_evidence_retention_stale")

    return WebEvidenceReadiness(
        feature_flag_enabled=bool(cfg.enabled),
        effective_enabled=effective and not hard_errors,
        dialect=dialect,
        postgres_ok=postgres_ok,
        schema_ok=schema_ok,
        missing_tables=missing_tables,
        missing_indexes=missing_indexes,
        egress_hosts=egress,
        egress_ok=egress_ok,
        retention=retention,
        blocking_errors=tuple(hard_errors + advisory),
    )


def enforce_enablement_gate(store, config: WebEvidenceConfig) -> WebEvidenceConfig:
    """Return a config that is forced off when deployed enablement prerequisites fail."""
    if not config.enabled:
        return config
    if config.provider_name == "exa":
        try:
            from ..usage.policy import Policy
            policy=Policy.load()
            if not policy.paid or not policy.provider_rate_version:
                raise RuntimeError("usage routes are disabled")
        except Exception:
            return type(config)(**{**config.__dict__, "enabled": False})
    if not postgres_required_for_enablement():
        return config
    report = evaluate_readiness(store, config=config)
    hard = [
        e for e in report.blocking_errors
        if e != "web_evidence_retention_stale"
    ]
    if not hard and report.effective_enabled:
        return config
    return type(config)(**{**config.__dict__, "enabled": False})


def assert_deployed_enablement(store, config: WebEvidenceConfig | None = None) -> None:
    """Raise when production tries to enable web evidence without Postgres/schema."""
    cfg = config or load_web_evidence_config()
    if not cfg.enabled or not postgres_required_for_enablement():
        return
    report = evaluate_readiness(store, config=cfg)
    hard = [e for e in report.blocking_errors if e != "web_evidence_retention_stale"]
    if hard:
        raise RuntimeError("Web evidence cannot be enabled: " + ", ".join(hard))



# Re-export for callers that only need purge after readiness.
__all__ = [
    "REQUIRED_INDEXES",
    "REQUIRED_TABLES",
    "EvidenceRetention",
    "WebEvidenceReadiness",
    "assert_deployed_enablement",
    "check_schema",
    "enforce_enablement_gate",
    "evaluate_readiness",
    "is_deployed_env",
    "postgres_required_for_enablement",
    "retention_status",
]
