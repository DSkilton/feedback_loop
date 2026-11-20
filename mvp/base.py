"""Shared SQLAlchemy metadata for write models and CQRS-style read projections."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
