"""Bounded synthetic model comparison. Never changes the production model route."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from backend.app.model_provider import OpenRouterLessonProvider, close_provider_http_clients
from backend.app.context_engine import GenerationContext, estimate_tokens
from backend.scripts.performance_benchmark import summary


async def evaluate(args, cases):
    rows = []
    key = os.getenv('OPENROUTER_API_KEY')
    if not key:
        raise SystemExit('OPENROUTER_API_KEY is required; it will not be exported.')
    try:
        for model in args.models.split(','):
            provider = OpenRouterLessonProvider(key, model.strip(), None, 'Open Learn synthetic evaluation')
            for case in cases:
              for repetition in range(args.repeat):
                start = time.perf_counter()
                row = {'model': model.strip(), 'scenario': case['id'], 'status': 'failed', 'firstTextMs': None,
                    'quality': 'unreviewed', 'answer': '', 'repetition': repetition,
                    'prefixCacheRequested': args.prefix_cache}
                instructions = case.get('instructions', 'Explain clearly and preserve the supplied learning context.')
                prompt = GenerationContext(instructions=instructions, blocks=(), recent_messages=(),
                    current_user_message=case['prompt'], estimated_input_tokens=estimate_tokens(instructions + case['prompt']),
                    budget_tokens=12000, omitted=())
                async def collect():
                    async for delta in provider.stream_text(prompt, max_tokens=args.max_output_tokens):
                        if delta.strip() and row['firstTextMs'] is None:
                            row['firstTextMs'] = (time.perf_counter() - start) * 1000
                        row['answer'] += delta
                try:
                    await asyncio.wait_for(collect(), args.timeout_seconds)
                    row['status'] = 'completed' if row['firstTextMs'] is not None else 'empty'
                except Exception as cause:
                    row['errorType'] = type(cause).__name__
                row['completionMs'] = (time.perf_counter() - start) * 1000
                usage = provider.last_usage
                if usage:
                    row.update(cachedPromptTokens=usage.cached_prompt_tokens, cacheWriteTokens=usage.cache_write_tokens,
                        promptTokens=usage.prompt_tokens, completionTokens=usage.completion_tokens, providerCostUsd=usage.cost)
                rows.append(row)
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(json.dumps({'scope': 'synthetic provider-only; excludes database/browser',
                    'productionQualification': False, 'routeChanged': False, 'qualityQualified': False,
                    'firstText': summary([item['firstTextMs'] for item in rows if item['status']=='completed']),
                    'perModelFirstText': {route: summary([item['firstTextMs'] for item in rows
                        if item['status']=='completed' and item['model']==route]) for route in args.models.split(',')},
                    'results': rows}, indent=2), encoding='utf-8')
    finally:
        await close_provider_http_clients()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', required=True, type=Path)
    parser.add_argument('--models', required=True)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--max-output-tokens', type=int, default=256)
    parser.add_argument('--timeout-seconds', type=int, default=30)
    parser.add_argument('--repeat', type=int, default=1, help='Repeat the exact synthetic prefix to observe warm/cache behavior')
    parser.add_argument('--prefix-cache', action='store_true', help='Opt in to Anthropic input-prefix caching for evaluation only')
    parser.add_argument('--max-estimated-usd', type=float, required=True)
    parser.add_argument('--input-usd-per-million-ceiling', type=float, required=True)
    parser.add_argument('--output-usd-per-million-ceiling', type=float, required=True)
    args = parser.parse_args()
    os.environ['OPENLEARN_PROVIDER_PREFIX_CACHE_ENABLED'] = 'true' if args.prefix_cache else 'false'
    cases = json.loads(args.cases.read_text(encoding='utf-8'))
    models = [model.strip() for model in args.models.split(',')]
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100 or not 1 <= len(models) <= 4 or any(not model for model in models):
        parser.error('Require 1–100 synthetic cases and 1–4 explicit model routes.')
    if not 1 <= args.max_output_tokens <= 512 or not 1 <= args.timeout_seconds <= 60 or not 1 <= args.repeat <= 3:
        parser.error('Output must be 1–512 tokens; timeout 1–60 seconds.')
    if any(not isinstance(case, dict) or not isinstance(case.get('id'), str)
           or not isinstance(case.get('prompt'), str) or len(case['prompt']) > 12000 for case in cases):
        parser.error('Cases require string id/prompt; maximum prompt length 12000 characters.')
    if any(not isinstance(case.get('instructions', ''), str) or len(case.get('instructions', '')) > 12000 for case in cases):
        parser.error('Synthetic instruction prefixes must be strings with at most 12000 characters.')
    import math
    rates = [args.input_usd_per_million_ceiling, args.output_usd_per_million_ceiling, args.max_estimated_usd]
    if any(not math.isfinite(value) or value <= 0 for value in rates):
        parser.error('Budget and tariff ceilings must be finite positive numbers.')
    # UTF-8 bytes are a deliberately conservative input-token ceiling.
    estimated = len(models) * args.repeat * sum((len(case['prompt'].encode()) + len(case.get('instructions', 'Explain clearly and preserve the supplied learning context.').encode()) + 1024) * args.input_usd_per_million_ceiling
        + args.max_output_tokens * args.output_usd_per_million_ceiling for case in cases) / 1_000_000
    if estimated > args.max_estimated_usd:
        parser.error('Conservative estimated spend exceeds the requested budget. No provider calls made.')
    asyncio.run(evaluate(args, cases))


if __name__ == '__main__':
    main()
