"""Bounded, owner-scoped visual grounding.

Prior visuals are described as readable text by default. Executable source is
shared only for an explicit edit target: the newest generated visual from an
earlier turn when the learner's request reads as a change to it. The source is
the model's own previously verified output, and any revision is re-verified.
"""
import re
import json
from html import unescape
from sqlalchemy import text

# Bounded source handed to the producer for in-place edits.
MAX_EDIT_SOURCE_CHARS = 64000
EDIT_CUE = re.compile(
    r"\b(add|change|make|turn|modify|update|adjust|show|hide|remove|replace|switch|convert|slow|speed|faster|slower|"
    r"bigger|smaller|larger|instead|also|now|another|extend|include|label|color|colour|zoom|rotate|animate|fix|"
    r"this|it|the (?:simulation|visual|chart|graph|diagram|animation|plot|scene|model|circuit|dashboard))\b",
    re.IGNORECASE)


def readable_html(value):
    value = re.sub(r'<(script|style)\b[^>]*>[\s\S]*?</\1>', '', value, flags=re.I)
    return unescape(re.sub(r'<[^>]+>', ' ', value))[:3000]


def lesson_text(lesson):
    return '\n'.join(str(block.get('body', '')) for block in lesson.get('blocks', []))[:6000]


def edit_target(record):
    """Exact source and state of a generated visual, or None when too large."""
    spec = record['spec']
    content = spec.get('content') or {}
    source = {key: content.get(key) for key in ('css', 'html', 'jsFunctions', 'jsExpressions', 'initialHeight') if content.get(key) is not None}
    if len(json.dumps(source)) > MAX_EDIT_SOURCE_CHARS:
        return None
    return {'id': spec['id'], 'title': spec['title'], 'revision': spec['revision'], 'lineage': spec.get('lineage'),
            'controls': spec.get('controls', []), 'controlValues': spec.get('controlValues', {}), 'source': source}


def visual_grounding(conn, records, owner, session_id, lesson_id, question=''):
    messages, visuals = [], []
    lessons, earlier = [], set()
    journey_id = 'journey_' + session_id
    if conn.execute(text('SELECT 1 FROM practice_records WHERE id=:id AND owner_id=:owner'), {'id':journey_id,'owner':owner}).first():
        journey = records.read(owner, journey_id, 'journey', conn)
        turns = journey.get('turns', [])
        # Freeze at the target turn; later user submissions cannot alter a queued brief.
        target = next((i for i, turn in enumerate(turns) if (turn.get('lesson') or {}).get('id') == lesson_id), len(turns)-1)
        for turn in turns[max(0,target-2):target+1]:
            if turn.get('question'):
                messages.append({'role':'user','content':str(turn['question'])[:6000]})
            lesson = turn.get('lesson') or {}
            lessons.append(lesson)
            if lesson.get('id') and lesson.get('id') != lesson_id:
                earlier.add(lesson['id'])
            body = lesson_text(lesson)
            if body:
                messages.append({'role':'assistant','content':body})
    row = conn.execute(text('SELECT payload FROM lesson_artifacts WHERE id=:id'),{'id':lesson_id}).scalar_one_or_none()
    explanation = ''
    if row:
        lesson = json.loads(row)
        if lesson.get('sessionId',lesson.get('session_id')) == session_id:
            explanation = lesson_text(lesson)
            lessons.append(lesson)
    seen=set()
    editable = None
    for lesson in lessons:
            for block in lesson.get('blocks', []):
                for ref in block.get('visualizations', []):
                    if ref.get('type') != 'generated_ui_ref':
                        continue
                    if ref['id'] in seen:continue
                    row = conn.execute(text('SELECT 1 FROM practice_records WHERE id=:id AND owner_id=:owner AND kind=:kind'), {'id':ref['id'],'owner':owner,'kind':'generated_visual'}).first()
                    if not row:
                        continue
                    record = records.read(owner,ref['id'],'generated_visual',conn)
                    if record['sessionId'] != session_id:
                        continue
                    seen.add(ref['id'])
                    spec = record['spec']
                    item = {'id':spec['id'],'title':spec['title'],'revision':spec['revision'],'renderer':spec['renderer'],
                            'controls':spec.get('controls',[]),'controlValues':spec.get('controlValues',{})}
                    if spec['renderer'] == 'a2ui':
                        # Preserve exact values while bounding the serialized job input.
                        if len(json.dumps(spec['content'])) <= 10000:
                            item['table'] = spec['content']
                        else:
                            item['dataUnavailable'] = 'Table exceeds context limit; request the relevant rows.'
                    else:
                        item['description'] = readable_html(''.join(spec['content'].get('html',[])))
                        # The newest custom visual from an earlier turn is the edit candidate.
                        if lesson.get('id') in earlier:
                            editable = record
                    visuals.append(item)
    grounding = {'conversation':messages[-4:],'explanation':explanation,'priorVisuals':visuals[-2:]}
    if editable is not None and EDIT_CUE.search(question or ''):
        target = edit_target(editable)
        if target is not None:
            grounding['editTarget'] = target
    return grounding
