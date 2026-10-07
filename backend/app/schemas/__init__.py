"""Pydantic schemas — the public API request/response shapes. Distinct
from `app.models` (SQLAlchemy ORM entities): schemas are what the API
speaks, models are what the database stores. `from_attributes=True` on
each *Read schema lets FastAPI serialize ORM instances directly.
"""
