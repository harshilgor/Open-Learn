"""Shared, versioned conversational capability selection; decisions grant no authority."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict

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
    kind: Literal['direct', 'browser', 'research', 'analysis', 'flashcards', 'reminder', 'control', 'connected_action', 'memory', 'responsibility']
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
