"""Store verified account email for operator-configured test allowances."""
from alembic import op
import sqlalchemy as sa

revision = '0078_usage_test_identity'
down_revision = '0077_usage_estimate_references'
branch_labels = depends_on = None


def upgrade():
    op.add_column('identity_accounts', sa.Column('verified_email', sa.String(320), nullable=True))


def downgrade():
    op.drop_column('identity_accounts', 'verified_email')
