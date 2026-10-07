from __future__ import annotations

from datetime import datetime
from uuid import UUID

import re

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

_DOMAIN = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$|^localhost$")


def _clean_domains(v: list[str]) -> list[str]:
    out = []
    for d in v:
        d = d.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
        if not d:
            continue
        if not _DOMAIN.match(d.split(":")[0]):
            raise ValueError(f"invalid domain: {d}")
        out.append(d.split(":")[0])
    return sorted(set(out))



class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    base_url: HttpUrl
    allowed_domains: list[str] = Field(default_factory=list, max_length=20)
    default_goals: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("allowed_domains")
    @classmethod
    def _domains(cls, v: list[str]) -> list[str]:
        return _clean_domains(v)

    @field_validator("default_goals")
    @classmethod
    def _goals(cls, v: list[str]) -> list[str]:
        return [g.strip()[:500] for g in v if g.strip()]


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    allowed_domains: list[str] | None = Field(default=None, max_length=20)
    default_goals: list[str] | None = Field(default=None, max_length=10)

    @field_validator("allowed_domains")
    @classmethod
    def _domains(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_domains(v)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    base_url: str
    allowed_domains: list[str] = []
    default_goals: list[str] = []
    run_count: int = 0
    bug_count: int = 0
    created_at: datetime
    updated_at: datetime
