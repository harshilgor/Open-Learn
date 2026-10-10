"""Bounded, owner-scoped visual grounding; executable code is never model context."""
import re
import json
from html import unescape
from sqlalchemy import text


def readable_html(value):
    value = re.sub(r'<(script|style)\b[^>]*>[\s\S]*?</\1>', '', value, flags=re.I)
    return unescape(re.sub(r'<[^>]+>', ' ', value))[:3000]


def lesson_text(lesson):
    return '\n'.join(str(block.get('body', '')) for block in lesson.get('blocks', []))[:6000]


def visual_grounding(conn, records, owner, session_id, lesson_id):
    messages, visuals = [], []
    lessons=[]
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
                    visuals.append(item)
    return {'conversation':messages[-4:],'explanation':explanation,'priorVisuals':visuals[-2:]}
