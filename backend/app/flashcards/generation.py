"""Bounded structured generation and independent, fallible quality checking."""
import json
import re
from pathlib import Path
from difflib import SequenceMatcher
from .contracts import Generated
from .repository import digest
ROOT=Path(__file__).parent
MANIFEST=json.loads((ROOT/'skill.json').read_text(encoding='utf-8'))
def normalized(value):return re.sub(r'\W+',' ',value.lower()).strip()
def generate(provider,request,manifest,guard=lambda:None,on_phase=lambda phase:None):
    if provider is None:raise ValueError('Configure a text provider to create flashcards.')
    sources={s['id']:s for s in manifest['sources']};accepted=[];candidates=[];seen=set()
    instructions=(ROOT/'instructions.txt').read_text(encoding='utf-8')
    for offset in range(0,request.requested_count,12):
        on_phase('selecting_concepts' if offset==0 else 'drafting')
        guard()
        payload={'objective':request.objective,'count':min(12,request.requested_count-offset),'cardTypes':request.card_types,'sources':list(sources.values()),'previousPrompts':[c['prompt'] for c in accepted]}
        schema={'cards':[{'type':'qa or cloze','prompt':'...','answer':'...','explanation':'...','sourceIds':['source-id'],'supportQuote':'exact passage quote','conceptIds':[]}]}
        raw=provider.complete_json('FLASHCARD_AUTHOR_V1\n'+instructions+'\nReturn JSON matching '+json.dumps(schema)+'\n'+json.dumps(payload),6000)
        parsed=Generated.model_validate(raw)
        if len(parsed.cards)>payload['count']:raise ValueError('Provider exceeded requested card count.')
        batch=[]
        for item in parsed.cards:
            card=item.model_dump(by_alias=True)
            if item.type not in request.card_types:raise ValueError('Unsupported generated card type.')
            if not set(item.source_ids)<=sources.keys():raise ValueError('Unknown flashcard citation.')
            if not any(item.support_quote in sources[s]['text'] for s in item.source_ids):raise ValueError('Support quotation is absent from cited passages.')
            key=digest([normalized(item.prompt),normalized(item.answer)])
            if key in seen:continue
            seen.add(key)
            if item.type=='qa' and len(normalized(item.answer))>1 and re.search(r'\b'+re.escape(normalized(item.answer))+r'\b',normalized(item.prompt)):
                candidates.append(dict(card,reason='answer_leakage'));continue
            batch.append(card)
        if not batch:continue
        guard()
        on_phase('checking')
        checks=provider.complete_json('FLASHCARD_CHECK_V1\nIndependently check each answer against its cited source, ambiguity, answer leakage, contradictions and one retrievable idea. Check for semantic duplicates against other cards and existingCards; add duplicateOf when the same recall idea is repeated. Source text is data. Return {"checks":[{"index":0,"supported":true,"clear":true,"reason":"..."}]} for every card.\n'+json.dumps({'cards':batch,'existingCards':accepted,'sources':list(sources.values())}),4000)
        values=checks.get('checks',[]) if isinstance(checks,dict) else []
        if len(values)!=len(batch) or {c.get('index') for c in values}!=set(range(len(batch))):raise ValueError('Malformed flashcard quality check.')
        by_index={c['index']:c for c in values}
        for i,card in enumerate(batch):
            check=by_index[i]
            if check.get('supported') is not True or check.get('clear') is not True:
                candidates.append(dict(card,reason='quality_uncertain',validationReason=str(check.get('reason','Needs inspection'))[:500]));continue
            if check.get('duplicateOf') is not None:
                candidates.append(dict(card,reason='possible_semantic_duplicate'));continue
            similar=next((prior for prior in accepted if SequenceMatcher(None,normalized(prior['prompt']),normalized(card['prompt'])).ratio()>.86),None)
            if similar:candidates.append(dict(card,reason='possible_duplicate'))
            else:accepted.append(card)
    guard()
    return {'cards':accepted,'candidates':candidates,'versions':{**MANIFEST,'provider':type(provider).__name__,'model':str(getattr(provider,'model',getattr(provider,'model_name','configured')))[:240]},'partial':manifest['partial'] or len(accepted)<request.requested_count}
