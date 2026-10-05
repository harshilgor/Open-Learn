"""Add indexed keyset metadata for bounded quiz history pages."""
import json
from datetime import datetime, timezone
import sqlalchemy as sa
from alembic import op


revision = '0061_quiz_history_keyset'
down_revision = '0060_class_output_transition_epoch'
branch_labels = depends_on = None


def upgrade():
    op.add_column('practice_records', sa.Column('history_updated_at', sa.String(80), nullable=True))
    op.add_column('practice_records', sa.Column('history_created_at', sa.String(80), nullable=True))
    op.add_column('practice_records', sa.Column('history_session_id', sa.String(160), nullable=True))
    op.add_column('practice_records', sa.Column('history_lesson_note_id', sa.String(160), nullable=True))
    op.add_column('practice_records', sa.Column('history_status', sa.String(40), nullable=True))
    op.add_column('practice_records', sa.Column('history_concept_id', sa.String(160), nullable=True))
    op.add_column('practice_records', sa.Column('history_presentation_id', sa.String(160), nullable=True))
    op.add_column('practice_records', sa.Column('history_is_retry', sa.Boolean(), nullable=True))
    op.add_column('practice_records', sa.Column('history_assisted', sa.Boolean(), nullable=True))
    op.add_column('practice_records', sa.Column('history_outcome', sa.String(40), nullable=True))

    def canonical_timestamp(value):
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')
        except ValueError:
            return value

    connection = op.get_bind()
    cursor = ''
    while True:
        rows = connection.execute(sa.text("""
            SELECT id,kind,payload FROM practice_records
            WHERE kind IN ('quiz','review_session','attempt','challenge') AND id>:cursor ORDER BY id LIMIT 500
        """), {'cursor': cursor}).mappings().all()
        if not rows:
            break
        values = []
        for row in rows:
            payload = json.loads(row['payload'])
            values.append({
                'id': row['id'],
                'history_updated_at': canonical_timestamp(payload.get('updatedAt') or payload.get('createdAt')) if row['kind'] == 'quiz' else None,
                'history_created_at': canonical_timestamp(payload.get('createdAt')),
                'history_session_id': payload.get('sessionId') if row['kind'] == 'quiz' else payload.get('learnSessionId') if row['kind'] == 'review_session' else None,
                'history_lesson_note_id': payload.get('lessonNoteId') if row['kind'] == 'quiz' else None,
                'history_status': payload.get('status'),
                'history_concept_id': payload.get('conceptId') if row['kind'] == 'attempt' else None,
                'history_presentation_id': payload.get('presentationId') if row['kind'] in {'attempt', 'challenge'} else None,
                'history_is_retry': bool(payload.get('retryOf')) if row['kind'] == 'attempt' else None,
                'history_assisted': bool(payload.get('assisted')) if row['kind'] == 'attempt' else None,
                'history_outcome': payload.get('outcome') if row['kind'] == 'attempt' else None,
            })
        connection.execute(sa.text("""
            UPDATE practice_records SET history_updated_at=:history_updated_at,history_created_at=:history_created_at,
                history_session_id=:history_session_id,
                history_lesson_note_id=:history_lesson_note_id,history_status=:history_status,
                history_concept_id=:history_concept_id,history_presentation_id=:history_presentation_id,
                history_is_retry=:history_is_retry,history_assisted=:history_assisted,
                history_outcome=:history_outcome
            WHERE id=:id AND kind IN ('quiz','review_session','attempt','challenge')
        """), values)
        cursor = rows[-1]['id']

    op.create_index(
        'ix_practice_quiz_history_page',
        'practice_records',
        ['owner_id', 'kind', 'history_created_at', 'id'],
    )
    op.create_index(
        'ix_practice_quiz_session_history',
        'practice_records',
        ['owner_id', 'kind', 'history_session_id', 'history_created_at', 'id'],
    )
    op.create_index(
        'ix_practice_session_active_activity',
        'practice_records',
        ['owner_id', 'kind', 'history_session_id', 'history_status', 'history_created_at', 'id'],
    )
    op.create_index(
        'ix_practice_quiz_history_lesson',
        'practice_records',
        ['owner_id', 'kind', 'history_lesson_note_id', 'history_created_at', 'id'],
    )
    op.create_index(
        'ix_practice_session_activity',
        'practice_records',
        ['owner_id', 'history_session_id', 'kind', 'id'],
    )
    op.create_index(
        'ix_practice_attempt_session_concept_recent',
        'practice_records',
        ['owner_id', 'kind', 'history_concept_id', 'history_created_at', 'id', 'parent_id'],
    )
    op.create_index(
        'ix_practice_challenge_presentation_status',
        'practice_records',
        ['owner_id', 'kind', 'parent_id', 'history_presentation_id', 'history_status'],
    )
    op.create_index(
        'ix_class_sessions_owner_history',
        'class_sessions',
        ['owner_id', 'created_at', 'id'],
    )
    op.create_index(
        'ix_class_input_synthesis_legacy',
        'class_input_windows',
        ['owner_id', 'class_id', 'kind', 'id'],
    )


def downgrade():
    op.drop_index('ix_class_input_synthesis_legacy', table_name='class_input_windows')
    op.drop_index('ix_class_sessions_owner_history', table_name='class_sessions')
    op.drop_index('ix_practice_session_activity', table_name='practice_records')
    op.drop_index('ix_practice_session_active_activity', table_name='practice_records')
    op.drop_index('ix_practice_challenge_presentation_status', table_name='practice_records')
    op.drop_index('ix_practice_attempt_session_concept_recent', table_name='practice_records')
    op.drop_index('ix_practice_quiz_history_lesson', table_name='practice_records')
    op.drop_index('ix_practice_quiz_session_history', table_name='practice_records')
    op.drop_index('ix_practice_quiz_history_page', table_name='practice_records')
    op.drop_column('practice_records', 'history_lesson_note_id')
    op.drop_column('practice_records', 'history_session_id')
    op.drop_column('practice_records', 'history_updated_at')
    op.drop_column('practice_records', 'history_created_at')
    op.drop_column('practice_records', 'history_status')
    op.drop_column('practice_records', 'history_concept_id')
    op.drop_column('practice_records', 'history_presentation_id')
    op.drop_column('practice_records', 'history_is_retry')
    op.drop_column('practice_records', 'history_assisted')
    op.drop_column('practice_records', 'history_outcome')
