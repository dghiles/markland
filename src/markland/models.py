"""Document + grant data models."""

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Document:
    id: str
    title: str
    content: str
    share_token: str
    created_at: str
    updated_at: str
    is_public: bool = False
    is_featured: bool = False
    owner_id: str | None = None
    version: int = 1

    @staticmethod
    def generate_id() -> str:
        return secrets.token_hex(8)

    @staticmethod
    def generate_share_token() -> str:
        return secrets.token_urlsafe(16)

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()


@dataclass
class Grant:
    doc_id: str
    principal_id: str
    principal_type: str  # 'user' | 'agent'
    level: str  # 'view' | 'edit'
    granted_by: str
    granted_at: str


@dataclass
class Agent:
    id: str
    display_name: str
    owner_type: str  # "user" | "service"
    owner_id: str
    created_at: str
    revoked_at: str | None = None

    @staticmethod
    def generate_id() -> str:
        return "agt_" + secrets.token_hex(8)

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()


@dataclass
class Invite:
    id: str
    token_hash: str
    doc_id: str
    level: str  # 'view' | 'edit'
    single_use: bool
    uses_remaining: int
    created_by: str  # principal_id (usr_… at launch)
    created_at: str
    expires_at: str | None = None
    revoked_at: str | None = None

    @staticmethod
    def generate_id() -> str:
        return "inv_" + secrets.token_hex(8)

    @staticmethod
    def generate_token() -> str:
        # 32 bytes of entropy; urlsafe for direct use in URLs.
        # Prefixed with `mk_inv_` so tokens are self-describing (mirrors
        # `mk_usr_` / `mk_agt_` in service/auth.py) and secret-scanners can
        # detect leaked invite tokens.
        return "mk_inv_" + secrets.token_urlsafe(32)

    def is_active(self, *, now: str) -> bool:
        if self.revoked_at is not None:
            return False
        if self.uses_remaining <= 0:
            return False
        if self.expires_at is not None and now >= self.expires_at:
            return False
        return True
