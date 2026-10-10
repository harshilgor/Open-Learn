"""Provider-neutral planning for the Ask/Learn generation context.

The budget is deliberately conservative: token counts are estimates until a
provider returns actual usage. Canonical turns remain in Journey storage.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


def estimate_tokens(value: Any) -> int:
    """Conservative, tokenizer-independent estimate for mixed prose and JSON."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return max(1, (len(text.encode("utf-8")) + 2) // 3)


@dataclass(frozen=True)
class ContextBlock:
    kind: str
    content: Any
    source: str
    priority: int
    required: bool = False
    relevance_score: float = 0.0

    @property
    def estimated_tokens(self) -> int:
        return estimate_tokens({self.kind: self.content}) + 16


@dataclass(frozen=True)
class GenerationContext:
    instructions: str
    blocks: tuple[ContextBlock, ...]
    recent_messages: tuple[dict[str, str], ...]
    current_user_message: str
    estimated_input_tokens: int
    budget_tokens: int
    omitted: tuple[str, ...]
    omission_reasons: tuple[dict[str, Any], ...] = ()
    estimated_image_tokens: int = 0
    included_turn_count: int = 0

    def supporting_context(self) -> str:
        return json.dumps(
            {block.kind: block.content for block in self.blocks},
            ensure_ascii=False,
        )

    def legacy_prompt(self) -> str:
        """Compatibility for providers without structured-message support."""
        return self.instructions + "\n" + self.supporting_context() + "\nRecent conversation: " + json.dumps(self.recent_messages, ensure_ascii=False) + "\nCurrent user message: " + self.current_user_message


class ContextEngine:
    """Choose bounded context while retaining complete recent turn pairs."""

    def __init__(self, input_budget_tokens: int = 12000, recent_budget_tokens: int = 4000):
        self.input_budget_tokens = input_budget_tokens
        self.recent_budget_tokens = recent_budget_tokens

    def build_generation_context(
        self,
        *,
        instructions: str,
        current_user_message: str,
        candidates: list[ContextBlock],
        turns: list[dict],
        image_count: int = 0,
        image_token_reserve: int = 1200,
    ) -> GenerationContext:
        # Image tokenization depends on provider detail, dimensions, and model.
        # Reserve a configurable amount per image before admitting text blocks.
        image_cost = max(0, image_count) * max(0, image_token_reserve)
        required_cost = estimate_tokens(instructions) + estimate_tokens(current_user_message) + 128 + image_cost
        if required_cost > self.input_budget_tokens:
            raise ValueError("Current request exceeds the model context budget")
        remaining = self.input_budget_tokens - required_cost
        chosen: list[ContextBlock] = []
        omitted: list[str] = []
        omission_reasons: list[dict[str, Any]] = []
        for block in sorted((item for item in candidates if item.required), key=lambda item: (item.priority, -item.relevance_score, item.kind)):
            if block.estimated_tokens > remaining:
                raise ValueError(f"Required context exceeds the model context budget: {block.kind}")
            chosen.append(block)
            remaining -= block.estimated_tokens

        recent: list[dict[str, str]] = []
        recent_remaining = min(remaining, self.recent_budget_tokens)
        recent_omitted_indexes: list[int] = []
        for turn_index in range(len(turns) - 1, -1, -1):
            turn = turns[turn_index]
            lesson = turn.get("lesson") or {}
            answer = "\n".join(str(block.get("body", "")) for block in lesson.get("blocks", []))
            draft = turn.get("assistantDraft")
            if isinstance(draft, str) and draft:
                answer = "[Earlier response draft; it may be incomplete and can be corrected or replaced]\n" + draft
            pair = [
                {"role": "user", "content": str(turn.get("question", ""))},
                {"role": "assistant", "content": answer},
            ]
            cost = sum(estimate_tokens(message["content"]) + 8 for message in pair)
            if cost > recent_remaining:
                omitted.append("conversation_older_turns")
                recent_omitted_indexes = list(range(turn_index + 1))
                break
            recent[0:0] = pair
            recent_remaining -= cost

        recent_cost = min(remaining, self.recent_budget_tokens) - recent_remaining
        remaining -= recent_cost
        if recent_omitted_indexes:
            omission_reasons.append({
                "kind": "conversation_older_turns",
                "source": "journey",
                "reason": "recent_window_budget_exhausted",
                "turnIndexes": recent_omitted_indexes,
                "omittedCount": len(recent_omitted_indexes),
            })
        for block in sorted((item for item in candidates if not item.required), key=lambda item: (item.priority, -item.relevance_score, item.kind)):
            if block.estimated_tokens <= remaining:
                chosen.append(block)
                remaining -= block.estimated_tokens
            elif isinstance(block.content, list) and block.content:
                # Retrieved evidence is ranked. Preserve complete items in order
                # so a large passage cannot suppress every smaller passage.
                kept = []
                for item in block.content:
                    item_cost = ContextBlock(block.kind, [*kept, item], block.source, block.priority,
                                             relevance_score=block.relevance_score).estimated_tokens
                    if item_cost <= remaining:
                        kept.append(item)
                if kept:
                    partial = ContextBlock(block.kind, kept, block.source, block.priority,
                                           relevance_score=block.relevance_score)
                    chosen.append(partial)
                    remaining -= partial.estimated_tokens
                omitted.append(f"{block.kind}_partial" if kept else block.kind)
                kept_keys = {json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) for item in kept}
                skipped_items = [item for item in block.content if json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) not in kept_keys]
                omission_reasons.append({
                    "kind": block.kind,
                    "source": block.source,
                    "reason": "some_items_exceed_remaining_budget" if kept else "block_exceeds_remaining_budget",
                    "priority": block.priority,
                    "relevanceScore": block.relevance_score,
                    "omittedSourceIds": _source_ids(skipped_items),
                    "omittedItemCount": len(skipped_items),
                    "estimatedTokens": block.estimated_tokens,
                    "remainingTokens": remaining + (chosen[-1].estimated_tokens if kept else 0),
                })
            else:
                omitted.append(block.kind)
                omission_reasons.append({
                    "kind": block.kind,
                    "source": block.source,
                    "reason": "block_exceeds_remaining_budget",
                    "priority": block.priority,
                    "relevanceScore": block.relevance_score,
                    "sourceIds": _source_ids(block.content),
                    "estimatedTokens": block.estimated_tokens,
                    "remainingTokens": remaining,
                })

        used = self.input_budget_tokens - remaining
        return GenerationContext(
            instructions=instructions,
            blocks=tuple(chosen),
            recent_messages=tuple(recent),
            current_user_message=current_user_message,
            estimated_input_tokens=used,
            budget_tokens=self.input_budget_tokens,
            omitted=tuple(omitted),
            omission_reasons=tuple(omission_reasons),
            estimated_image_tokens=image_cost,
            included_turn_count=len(recent) // 2,
        )


def _source_ids(value: Any) -> list[str]:
    found: set[str] = set()
    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, entry in item.items():
                if key.lower().endswith("id") and isinstance(entry, (str, int)):
                    found.add(f"{key}:{entry}")
                else:
                    walk(entry)
        elif isinstance(item, (list, tuple)):
            for entry in item:
                walk(entry)
    walk(value)
    return sorted(found)
