"""Repair lecture tables created before capture_interrupted was added to 0026.

Some local databases were stamped at 0026 while that migration did not yet
include the column. The current 0026 creates it for fresh installs, so this
migration checks the live schema before adding it.
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_lecture_capture_interrupted_repair"
down_revision = "0026_lecture_pipeline"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("lecture_recordings")}
    if "capture_interrupted" not in columns:
        op.add_column("lecture_recordings", sa.Column("capture_interrupted", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    # 0026's current schema requires this column, including on fresh installs.
    pass
