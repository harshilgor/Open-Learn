"""Normalize learner-facing Markdown into canonical semantic lesson blocks.

The provider writes ordinary Markdown. This parser is deliberately behind the
generation boundary: it maps content semantics to the existing LessonArtifact
contract and never asks a frontend to parse provider events.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .model_provider import GeneratedBlock

_HEAD = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)
_KINDS = {
    "example": "example", "worked example": "example", "equation": "visual", "math": "visual",
    "code": "visual", "try it": "check", "check": "check", "question": "check",
    "summary": "reflection", "recap": "reflection", "key idea": "explanation",
}


def _display_heading(heading: str, default_heading: str) -> str:
    """Drop generic section labels while preserving useful content headings."""
    if heading.strip().casefold().rstrip(':') == 'explanation':
        return ''
    if heading.strip().casefold() == default_heading.strip().casefold():
        return ''
    return heading


def semantic_blocks(markdown: str, default_heading: str) -> list[GeneratedBlock]:
    """Create meaningful blocks when headings are present; keep prose intact otherwise."""
    matches = list(_HEAD.finditer(markdown))
    if not matches:
        return [GeneratedBlock(kind="explanation", heading="", body=markdown.strip())]
    blocks: list[GeneratedBlock] = []
    preface = markdown[:matches[0].start()].strip()
    if preface:
        blocks.append(GeneratedBlock(kind="explanation", heading="", body=preface))
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        body = markdown[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(markdown)].strip()
        if not body:
            continue
        normalized = heading.lower().rstrip(":")
        kind = _KINDS.get(normalized, "explanation")
        blocks.append(GeneratedBlock(kind=kind, heading=_display_heading(heading, default_heading), body=body))
    return blocks or [GeneratedBlock(kind="explanation", heading="", body=markdown.strip())]


@dataclass(frozen=True)
class LessonStreamOperation:
    action: str
    block_id: str
    kind: str = "explanation"
    heading: str = ""
    text: str = ""


class ProgressiveLessonParser:
    """Translate neutral Markdown headings into normalized block operations.

    Provider chunks may split headings at arbitrary byte boundaries, so a line
    is held only while it may still be a heading. Body text is then forwarded
    incrementally to the active semantic block.
    """
    def __init__(self, generation_id: str, default_heading: str):
        self.generation_id = generation_id
        self.default_heading = default_heading
        self.pending = ""
        self.block_index = 0
        self.block_id = ""
        self.kind = "explanation"
        self.heading = default_heading

    def _start(self, heading: str, kind: str) -> LessonStreamOperation:
        self.block_index += 1
        self.block_id = f"stream_{self.generation_id}_{self.block_index}"
        self.heading, self.kind = _display_heading(heading, self.default_heading), kind
        return LessonStreamOperation("start", self.block_id, kind, self.heading)

    def feed(self, delta: str) -> list[LessonStreamOperation]:
        self.pending += delta
        operations: list[LessonStreamOperation] = []
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            match = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
            if match:
                if self.block_id:
                    operations.append(LessonStreamOperation("complete", self.block_id))
                heading = match.group(1).strip()
                operations.append(self._start(heading, _KINDS.get(heading.lower().rstrip(":"), "explanation")))
                continue
            if not self.block_id:
                operations.append(self._start("", "explanation"))
            operations.append(LessonStreamOperation("delta", self.block_id, text=line + "\n"))
        # Once a line cannot be a heading, stream it without waiting for a newline.
        if self.pending and self.block_id and not self.pending.startswith("#"):
            operations.append(LessonStreamOperation("delta", self.block_id, text=self.pending))
            self.pending = ""
        return operations

    def finish(self) -> list[LessonStreamOperation]:
        operations: list[LessonStreamOperation] = []
        if self.pending:
            if not self.block_id:
                operations.append(self._start("", "explanation"))
            operations.append(LessonStreamOperation("delta", self.block_id, text=self.pending))
            self.pending = ""
        if self.block_id:
            operations.append(LessonStreamOperation("complete", self.block_id))
        return operations
