"""Explicit process budgets. These limits must also hold during deploy overlap."""
from __future__ import annotations

import os
from dataclasses import dataclass

ROLE_POOLS = {'api': 5, 'api-free': 5, 'generation': 5, 'learning': 2, 'agent': 2,
              'class': 2, 'browser': 2, 'notifications': 2, 'migrate': 1, 'cron': 1}
# Redis client pools per process. Keep the sum (x replicas x deploy overlap)
# inside the Key Value plan's connection limit; see deploy/connection-budget.json.
REDIS_ROLE_POOLS = {'api': 6, 'api-free': 6, 'generation': 4, 'learning': 2, 'agent': 2,
                    'class': 2, 'browser': 2, 'notifications': 1, 'migrate': 1, 'cron': 1}


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
                         positive_int('OPENLEARN_DB_POOL_TIMEOUT_SECONDS', 10 if role == 'api-free' else 3, 30),
                         positive_int('OPENLEARN_DB_CONNECT_TIMEOUT_SECONDS', 3, 30),
                         positive_int('OPENLEARN_HTTP_CONCURRENCY', 128, 1000))


def redis_pool_size() -> int:
    role = os.getenv('OPENLEARN_PROCESS_ROLE', 'api')
    if role not in REDIS_ROLE_POOLS:
        raise ValueError('Unknown OPENLEARN_PROCESS_ROLE')
    return positive_int('OPENLEARN_REDIS_POOL_SIZE', REDIS_ROLE_POOLS[role], 50)
