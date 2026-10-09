"""Connector interface for authorized publishing integrations.

A connector must be honest about what it can do: ``discover_capabilities`` reports, per operation,
whether it is supported *for this specific site and account*, why not if not, and whether
rollback is possible. Operations not declared supported are never attempted.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

OPERATIONS = (
    "set_title",
    "set_meta_description",
    "set_image_alt",
    "content_insert_after_heading",
    "content_append",
    "content_replace_href",
    "content_link_phrase",
    "add_json_ld",
    "set_canonical",
    "create_redirect",
    "set_robots",
)


class ConnectorError(Exception):
    """A provider call failed. ``user_message`` is safe to show to users."""

    def __init__(self, user_message: str, *, detail: Any = None, conflict: bool = False):
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail
        self.conflict = conflict


@dataclass
class Capability:
    supported: bool
    reason: str = ""
    rollback: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return {"supported": self.supported, "reason": self.reason, "rollback": self.rollback, "notes": self.notes}


@dataclass
class SiteIdentity:
    site_url: str
    name: str
    account: str
    raw: dict = field(default_factory=dict)


@dataclass
class ResourceRef:
    kind: str  # e.g. "pages", "posts"
    id: str
    link: str
    api_url: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "id": self.id, "link": self.link, "api_url": self.api_url}


@dataclass
class ApplyResult:
    original_state: dict
    new_state: dict
    provider_response: dict
    rollback_ref: dict


class Connector(ABC):
    provider: str
    display_name: str

    @abstractmethod
    async def verify_identity(self, creds: dict) -> SiteIdentity: ...

    @abstractmethod
    async def discover_capabilities(self, creds: dict) -> dict[str, Capability]: ...

    @abstractmethod
    async def locate(self, creds: dict, page_url: str, extracted: dict | None) -> ResourceRef | None: ...

    @abstractmethod
    async def read(self, creds: dict, ref: ResourceRef) -> dict: ...

    @abstractmethod
    async def apply(self, creds: dict, ref: ResourceRef, operation: str, params: dict) -> ApplyResult: ...

    @abstractmethod
    async def rollback(self, creds: dict, rollback_ref: dict) -> dict: ...

    async def disconnect(self, creds: dict) -> None:  # pragma: no cover - optional
        return None
