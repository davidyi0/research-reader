"""google auth: drop password_hash, add name

Revision ID: 9c2a4e1f7b3d
Revises: 1728043a9298
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c2a4e1f7b3d"
down_revision: Union[str, None] = "1728043a9298"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.Text(), nullable=True))
    op.drop_column("users", "password_hash")


def downgrade() -> None:
    op.add_column(
        "users", sa.Column("password_hash", sa.Text(), nullable=False, server_default="")
    )
    op.drop_column("users", "name")
