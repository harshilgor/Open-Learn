"""The visual model proxy settles with the provider receipt, never twice."""
import asyncio
import json

import httpx

from backend.app import openintelligentui


def chunks(finish_at, total=6):
    lines = []
    for index in range(total):
        choice = {'index': 0, 'delta': {'content': f'part{index}'}}
        if index == finish_at:
            choice['finish_reason'] = 'tool_calls'
        lines.append('data: ' + json.dumps({'choices': [choice]}) + '\n\n')
    lines.append('data: ' + json.dumps({'choices': [], 'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'cost': 0.0012}}) + '\n\n')
    lines.append('data: [DONE]\n\n')
    return lines


def run(monkeypatch, lines, stop_when):
    """Consume until ``stop_when(line)`` (None: everything), then let drains finish."""
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    served = []

    async def body():
        for line in lines:
            served.append(line)
            await asyncio.sleep(0.01)
            yield line.encode()
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=body(), headers={'content-type': 'text/event-stream'}))))
    settled = []

    async def scenario():
        stream = openintelligentui.metered_stream({'model': 'm'}, 'ticket', lambda ticket, receipt: settled.append(receipt))
        async for line in stream:
            if stop_when is not None and stop_when(line):
                break
        await stream.aclose()
        for _ in range(100):
            if not openintelligentui._DRAINS:
                break
            await asyncio.sleep(0.02)
    asyncio.run(scenario())
    return settled, served


def test_full_stream_settles_with_the_receipt(monkeypatch):
    settled, _ = run(monkeypatch, chunks(finish_at=5), None)
    assert settled == [{'prompt_tokens': 100, 'completion_tokens': 50, 'cost': 0.0012}]


def test_finished_generation_is_drained_for_its_receipt_after_the_client_leaves(monkeypatch):
    # CopilotKit stops reading at the tool call (finish_reason), before usage.
    settled, served = run(monkeypatch, chunks(finish_at=5), lambda line: 'finish_reason' in line)
    assert settled == [{'prompt_tokens': 100, 'completion_tokens': 50, 'cost': 0.0012}]
    assert len(served) == 7  # stops right after the usage chunk


def test_unfinished_generation_is_aborted_and_kept_conservative(monkeypatch):
    # A cancelled visual: nothing more is read or billed beyond the reservation.
    settled, served = run(monkeypatch, chunks(finish_at=5), lambda line: 'part1' in line)
    assert settled == [None]
    assert len(served) < 8


def test_rejected_request_settles_at_zero_and_reports_failure(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    error = {'error': {'code': 400, 'message': 'Provider returned error', 'metadata': {'raw': json.dumps({'error': {'message': 'messages.5: invalid'}})}}}
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(
        lambda request: httpx.Response(400, json=error))))
    settled, relayed = [], []

    async def scenario():
        async for line in openintelligentui.metered_stream({'model': 'm'}, 'ticket', lambda ticket, receipt: settled.append(receipt)):
            relayed.append(line)
    asyncio.run(scenario())
    assert settled == [{'prompt_tokens': 0, 'completion_tokens': 0, 'cost': 0}]
    assert 'Visual model request failed' in relayed[0]
