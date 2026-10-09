"""Shared, versioned conversational capability selection; decisions grant no authority."""
import logging
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict
from ..classification.config import min_score, rollout_mode, should_sample_shadow
from ..classification.service import ClassificationService

logger = logging.getLogger(__name__)

PUBLIC_SITES = {
    'youtube': 'https://www.youtube.com', 'github': 'https://github.com',
    'google': 'https://www.google.com', 'wikipedia': 'https://www.wikipedia.org',
    'reddit': 'https://www.reddit.com',
}
ACTION = re.compile(r'\b(open|visit|browse|navigate|go to|go through|look at|look through|check|read through|search|find)\b', re.I)
NEGATED = re.compile(r"\b(?:do not|don't|never)\s+(?:open|visit|browse|navigate|check|search|go)\b", re.I)
URL = re.compile(r'https://[^\s<>"\)]+|\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>"\)]*)?', re.I)


class AdmissionPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal['conversation-admission-v1'] = 'conversation-admission-v1'
    kind: Literal['direct', 'browser', 'research', 'analysis', 'flashcards', 'reminder', 'control', 'connected_action', 'calendar_read', 'memory', 'responsibility']
    source_url: str | None = None
    source_alias: str | None = None
    action: Literal['pause', 'resume', 'cancel'] | None = None


def plan_message(message: str) -> AdmissionPlan:
    """Deterministic high-confidence requests bypass speculative model classification.

    Ordinary questions remain with the existing learning owner. Unsupported website
    names go to connection resolution, never to a fabricated institution URL.
    """
    value = message.strip()
    lower = value.lower()
    calendar_subject = re.search(r'\b(?:my|the)?\s*(?:google\s+)?(?:calendar|schedule|meetings?|events?)\b', lower)
    calendar_read = re.search(
        r"\b(?:what(?:'s| is) on|show|list|check|read|find|summari[sz]e|look at|look through|go through|review)\b.{0,60}\b(?:(?:my|the)\s+)?(?:google\s+)?(?:calendar|schedule|meetings?|events?)\b|"
        r"\bwhat(?:'s| is)\s+(?:my|the)\s+(?:google\s+)?(?:calendar|schedule|meetings?|events?)\b|"
        r"\bwhat\s+(?:meetings?|events?)\s+do\s+i\s+have\b|"
        r"\b(?:do i have|am i)\b.{0,40}\b(?:meetings?|events?)\b",
        lower,
    )
    calendar_write = re.search(r'\b(?:create|add|update|delete|remove|cancel|move|reschedule)\b|\bschedule\s+(?:(?:a|an|the|my)\s+)?(?:meetings?|events?|appointments?|classes?)\b', lower)
    if calendar_subject and calendar_read and not calendar_write:
        return AdmissionPlan(kind='calendar_read')
    if re.match(r'^(?:explain|teach me|tell me how|show me how|what is|what are|how (?:do|does))\b', lower):
        return AdmissionPlan(kind='direct')
    if re.match(r'^(?:please\s+)?remember that\s+', lower):
        return AdmissionPlan(kind='memory')
    if re.search(r'\b(?:keep an eye on|watch|monitor|keep checking|check every|every week|every day)\b', lower) and not re.match(r'^(?:remind me|quiz me)', lower):
        return AdmissionPlan(kind='responsibility')
    if re.fullmatch(r'(?:please\s+)?(?:stop|cancel|pause|resume|continue)(?:\s+(?:that|it|the task|this task|the browser))?[.!]?', lower):
        verb = re.search(r'stop|cancel|pause|resume|continue', lower).group()
        return AdmissionPlan(kind='control', action={'stop': 'cancel', 'continue': 'resume'}.get(verb, verb))
    if re.match(r'^(?:please\s+)?(?:remind me|quiz me (?:every|weekdays)|show my reminders|list (?:my )?reminders|cancel .*reminder|snooze)', value, re.I):
        return AdmissionPlan(kind='reminder')
    if re.match(r'^(?:please\s+)?(?:make|create|generate|prepare|build)\s+(?:me\s+)?(?:some\s+)?(?:flash\s*cards|cards\s+for\s+(?:review|study))', value, re.I):
        return AdmissionPlan(kind='flashcards')
    if not NEGATED.search(value) and ACTION.search(value):
        url = URL.search(value)
        named = next((name for name in PUBLIC_SITES if re.search(r'\b' + name + r'\b', lower)), None)
        web_context = re.search(r'\b(canvas|website|web ?site|portal|browser|lms|online|my (?:classes|courses|account))\b', lower)
        explicit_destination = re.search(r'\b(?:open|visit|browse|navigate|go to)\s+(?:my\s+|the\s+)?(.+)', value, re.I)
        # "Open the lesson/quiz" remains a learning command, not a website.
        learning_destination = explicit_destination and re.match(r'(?:lesson|quiz|notes?|flashcards?|study canvas|course|dashboard|review|file|attachment|book)\b', explicit_destination[1], re.I)
        if url or named or web_context or (explicit_destination and not learning_destination):
            alias = None
            if not url and not named:
                alias = 'Canvas' if re.search(r'\bcanvas\b', lower) else explicit_destination[1].strip(' .!?')[:120] if explicit_destination else None
            return AdmissionPlan(kind='browser', source_url=((url.group().rstrip('.,;!?') if url.group().lower().startswith('https://') else 'https://' + url.group().rstrip('.,;!?')) if url else PUBLIC_SITES.get(named)) if url or named else None, source_alias=alias)
    if re.search(r'\b(?:research|investigate|compare sources|find evidence|look up evidence)\b', lower) and not re.match(r'^(?:what is|explain|define)\b', lower):
        return AdmissionPlan(kind='research')
    if re.search(r'\b(?:analy[sz]e|plot|chart)\b.*\b(?:csv|dataset|spreadsheet|lab results|data file)\b', lower):
        return AdmissionPlan(kind='analysis')
    if re.search(r'\b(?:send|draft|compose)\b.*\b(?:email|gmail)\b|\b(?:create|add|update)\b.*\b(?:calendar event|meeting)\b', lower):
        return AdmissionPlan(kind='connected_action')
    return AdmissionPlan(kind='direct')


def classify_message(message: str, *, context: dict | None = None) -> AdmissionPlan:
    """Route free text semantically through JEV, with deterministic fallback.

    Exact local control commands remain deterministic. A JEV label can select an
    existing capability, but never grants authority to execute it.
    """
    fallback = plan_message(message)
    if fallback.kind in {'control', 'calendar_read'}:
        return fallback
    mode = rollout_mode('turn_route')
    if mode == 'off' or mode == 'shadow' and not should_sample_shadow('turn_route', message):
        return fallback
    try:
        decision = ClassificationService().turn_route(message, context=context)
    except Exception as exc:
        # Route safely using the existing deterministic classifier if JEV is
        # unavailable, invalid, or not metered.
        logger.info('classification_fallback', extra={
            'classification_contract':'turn_route', 'classification_error':type(exc).__name__,
        })
        return fallback
    if mode == 'shadow':
        return fallback
    threshold = min_score('turn_route', decision.value, default=0.82)
    if decision.score < threshold:
        return fallback
    if decision.value == 'none':
        return AdmissionPlan(kind='direct')
    kind = {
        'direct_answer': 'direct', 'learn': 'direct', 'quiz': 'direct',
        'browser_academic': 'browser', 'research': 'research', 'data_analysis': 'analysis',
        'flashcards': 'flashcards', 'reminder': 'reminder', 'memory': 'memory',
        'responsibility': 'responsibility',
    }.get(decision.value)
    if not kind:
        return fallback
    if kind == 'browser':
        parsed = fallback if fallback.kind == 'browser' else None
        if parsed is None:
            url = URL.search(message)
            source_url = None
            if url:
                raw_url = url.group().rstrip('.,;!?')
                source_url = raw_url if raw_url.lower().startswith('https://') else 'https://' + raw_url
            named = next((name for name in PUBLIC_SITES if re.search(r'\b' + name + r'\b', message, re.I)), None)
            parsed = AdmissionPlan(kind='browser', source_url=source_url or PUBLIC_SITES.get(named),
                                   source_alias=None if source_url or named else None)
        return parsed
    return AdmissionPlan(kind=kind)
