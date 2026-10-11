"""Explicit process budgets. These limits must also hold during deploy overlap."""
from __future__ import annotations

import os
from dataclasses import dataclass

ROLE_POOLS = {'api': 5, 'api-free': 5, 'learning': 2, 'agent': 2,
              'class': 2, 'browser': 2, 'notifications': 2, 'migrate': 1}


def positive_int(name: str, default: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not 1 <= value <= maximum:
        raise ValueError(f'{name} must be between 1 and {maximum}')
    return value


@dataclass(frozen=True)
class ProcessBudget:
    role: str
    pool_size: int
    pool_timeout: int
    connect_timeout: int
    http_concurrency: int


def process_budget() -> ProcessBudget:
    role = os.getenv('OPENLEARN_PROCESS_ROLE', 'api')
    if role not in ROLE_POOLS:
        raise ValueError('Unknown OPENLEARN_PROCESS_ROLE')
    return ProcessBudget(role, positive_int('OPENLEARN_DB_POOL_SIZE', ROLE_POOLS[role], 20),
                         positive_int('OPENLEARN_DB_POOL_TIMEOUT_SECONDS', 3, 30),
                         positive_int('OPENLEARN_DB_CONNECT_TIMEOUT_SECONDS', 3, 30),
                         positive_int('OPENLEARN_HTTP_CONCURRENCY', 128, 1000))
