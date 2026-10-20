"""SQLAlchemy ORM models for the Qura client portal.

Importing this package registers every model with the shared ``Base.metadata``
(see ``app.db.base``). Alembic imports ``app.db.models`` so autogenerate always
sees the full schema. Keep every model reachable from here.

Entity groups:
- identity:      User, UserProfile, UserSetting, PasswordResetToken, Invite
- policies:      Policy
- claims:        Claim, ClaimDocument
- assets:        Asset
- family:        FamilyMember
- transactions:  Transaction
- engagement:    Notification, Announcement
- support:       SupportTicket, TicketMessage
- files:         StoredFile
- kyc:           KycDocument
- reference:     MasterData
- admin:         AuditLog
"""

from __future__ import annotations

from app.db.base import Base
from app.db.models.admin import AuditLog
from app.db.models.assets import Asset
from app.db.models.claims import Claim, ClaimDocument
from app.db.models.engagement import Announcement, Notification
from app.db.models.family import FamilyMember
from app.db.models.files import StoredFile
from app.db.models.identity import (
    Invite,
    PasswordResetToken,
    User,
    UserProfile,
    UserSetting,
)
from app.db.models.kyc import KycDocument
from app.db.models.policies import Policy
from app.db.models.reference import MasterData
from app.db.models.support import SupportTicket, TicketMessage
from app.db.models.transactions import Transaction

__all__ = [
    "Base",
    "User",
    "UserProfile",
    "UserSetting",
    "PasswordResetToken",
    "Invite",
    "Policy",
    "Claim",
    "ClaimDocument",
    "Asset",
    "FamilyMember",
    "Transaction",
    "Notification",
    "Announcement",
    "SupportTicket",
    "TicketMessage",
    "StoredFile",
    "KycDocument",
    "MasterData",
    "AuditLog",
]
