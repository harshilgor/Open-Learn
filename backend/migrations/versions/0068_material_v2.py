"""Versioned page, cue and lexical posting ledgers."""
import sqlalchemy as sa
import json
import re
import hashlib
from collections import Counter
from alembic import op
revision = '0068_material_v2'
down_revision = '0067_class_chunk_coverage'
branch_labels = depends_on = None

def upgrade():
    op.create_table('material_extract_pages',
        sa.Column('version_id', sa.String(160), sa.ForeignKey('material_versions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('page_index', sa.Integer(), primary_key=True),
        sa.Column('source_revision', sa.String(64), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False))
    op.create_table('material_index_pages',
        sa.Column('version_id', sa.String(160), sa.ForeignKey('material_versions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('page_index', sa.Integer(), primary_key=True),
        sa.Column('source_revision', sa.String(64), nullable=False),
        sa.Column('index_version', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('page_label', sa.String(64), nullable=False),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False))
    op.create_index('ix_material_index_page_label', 'material_index_pages', ['version_id', 'page_label'])
    op.create_table('material_index_cues',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('version_id', sa.String(160), sa.ForeignKey('material_versions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('page_index', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('label', sa.String(160), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False))
    op.create_index('ix_material_index_cue', 'material_index_cues', ['kind', 'label', 'version_id'])
    op.create_table('material_index_terms',
        sa.Column('term', sa.String(80), primary_key=True),
        sa.Column('block_id', sa.String(160), sa.ForeignKey('material_blocks.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('frequency', sa.Integer(), nullable=False))
    op.create_index('ix_material_index_term_block', 'material_index_terms', ['block_id'])
    # Legacy passages remain searchable without re-upload. Keyset batches keep
    # migration memory bounded independently of the size of the library.
    conn = op.get_bind()
    cursor = ''
    while True:
        rows = conn.execute(sa.text('SELECT b.*,v.sha256 FROM material_blocks b JOIN material_versions v ON v.id=b.version_id WHERE b.id>:cursor ORDER BY b.id LIMIT 200'), {'cursor':cursor}).mappings().all()
        if not rows: break
        for row in rows:
            payload=json.loads(row['payload'] or '{}')
            conn.execute(sa.text("INSERT INTO material_index_pages(version_id,page_index,source_revision,index_version,page_label,status,payload) VALUES(:v,:p,:r,2,:l,'legacy','{}') ON CONFLICT(version_id,page_index) DO NOTHING"),
                {'v':row['version_id'],'p':row['page_index'],'r':row['sha256'] or '', 'l':str(payload.get('pageLabel') or row['page_index']+1)[:64]})
            postings=[{'term':term[:80], 'block':row['id'], 'n':n} for term,n in Counter(re.findall(r'\w{2,}',row['text'].casefold())).items()]
            if postings:
                conn.execute(sa.text('INSERT INTO material_index_terms(term,block_id,frequency) VALUES(:term,:block,:n) ON CONFLICT(term,block_id) DO UPDATE SET frequency=excluded.frequency'),postings)
            for match in re.finditer(r'\b(chapter|ch\.?|section|sec\.?|figure|fig\.?|equation|eq\.?)\s*([\d]+(?:[.-]\d+)*[a-z]?)',row['text'],re.I):
                prefix=match[1].casefold()
                kind='chapter' if prefix.startswith('ch') else 'section' if prefix.startswith('sec') else 'figure' if prefix.startswith('fig') else 'equation'
                label=match[2].casefold()
                key='idx_'+hashlib.sha256('|'.join(map(str,(row['version_id'],row['page_index'],kind,label))).encode()).hexdigest()[:48]
                conn.execute(sa.text('INSERT INTO material_index_cues(id,version_id,page_index,kind,label,payload) VALUES(:id,:v,:p,:k,:l,:payload) ON CONFLICT(id) DO NOTHING'),
                    {'id':key,'v':row['version_id'],'p':row['page_index'],'k':kind,'l':label,'payload':json.dumps({'spanId':row['id'],'provenance':'legacy_extracted_text_label'})})
        cursor=rows[-1]['id']

def downgrade():
    op.drop_table('material_index_terms')
    op.drop_table('material_index_cues')
    op.drop_table('material_index_pages')
    op.drop_table('material_extract_pages')
