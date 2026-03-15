"""add email_accounts table

Revision ID: 88c2468f075b
Revises: 7d432dfd9151
Create Date: 2026-03-15 01:14:26.645157

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '88c2468f075b'
down_revision: Union[str, None] = '7d432dfd9151'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_accounts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('password_encrypted', sa.Text(), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False, server_default='outlook'),
        sa.Column('status', sa.String(50), nullable=False, server_default='creating'),
        sa.Column('steam_account_id', sa.Integer(), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('proxy_id', sa.Integer(), sa.ForeignKey('proxies.id', ondelete='SET NULL'), nullable=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('note', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('email_accounts')
