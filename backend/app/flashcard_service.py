"""Shared private draft storage; generation never schedules mastery/review."""
from .workflow_store import WorkflowStore
import hashlib
from sqlalchemy import text

class FlashcardService:
    def __init__(self,store):self.records=WorkflowStore(store)
    def save_draft(self,conn,owner,class_id,window_id,items,course_id):
        identifier='deck_'+hashlib.sha256(class_id.encode()).hexdigest()[:32]
        exists=conn.execute(text("SELECT 1 FROM practice_records WHERE id=:id AND owner_id=:owner AND kind='flashcard_deck'"),{'id':identifier,'owner':owner}).first()
        deck=self.records.read(owner,identifier,'flashcard_deck',conn) if exists else {'id':identifier,'classId':class_id,'courseId':course_id,'status':'draft','windows':{},'scheduled':False}
        # Keep immutable candidates by source window. Current windows control visibility.
        deck['windows'][window_id]=items
        active=conn.execute(text('SELECT payload FROM class_sessions WHERE id=:id AND owner_id=:owner'),{'id':class_id,'owner':owner}).scalar_one()
        import json
        session=json.loads(active);active_set=session.get('activeWindowSetId')
        active=conn.execute(text("SELECT window_id FROM class_session_window_membership WHERE owner_id=:owner AND class_id=:class AND set_id=:set AND purpose='transcript'"),{'owner':owner,'class':class_id,'set':active_set}).scalars().all() if active_set else session.get('activeWindows',[])
        active=set(active)
        deck['cards']=[card for wid,cards in deck['windows'].items() if wid in active for card in cards]
        self.records.put(conn,owner,'flashcard_deck',deck,parent=class_id,expected=deck['revision'] if exists else None)
        return identifier
