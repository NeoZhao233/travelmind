from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MemoryDeletionError(RuntimeError):
    """The store could not confirm a requested memory deletion."""


class MemoryScope(BaseModel, frozen=True):
    tenant_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    user_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    thread_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")

    @property
    def thread_key(self) -> tuple[str, str, str]:
        return self.tenant_id, self.user_id, self.thread_id

    @property
    def user_key(self) -> tuple[str, str]:
        return self.tenant_id, self.user_id


class MemoryTurn(BaseModel):
    turn_id: str = Field(min_length=1, max_length=128)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


class UserPreference(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=500)
    updated_at: datetime
    consent_recorded: bool

    @field_validator("updated_at")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("updated_at must include a timezone")
        return value


class MemorySnapshot(BaseModel):
    turns: list[MemoryTurn] = Field(default_factory=list)
    preferences: list[UserPreference] = Field(default_factory=list)
    degraded_components: list[str] = Field(default_factory=list)


class MemoryWriteResult(BaseModel):
    persisted: bool
    reason_code: str
    degraded_components: list[str] = Field(default_factory=list)
