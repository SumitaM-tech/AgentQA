"""Shared SQLAlchemy declarative base. Every model in `app/models/`
inherits from this. Kept in its own module (rather than inside
`session.py`) so `alembic/env.py` can import just the metadata without
pulling in the async engine/session machinery.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Uuid
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk():
    """Standard UUID primary key column used by every entity."""
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
