"""Policy routes (read-only in Phase 4).

  GET /policies            list the user's policies (optional ?status=)
  GET /policies/{id}       one policy, ownership-enforced

No purchase/checkout/quote/payment here (out of scope). Policy download, status
sync and tracking depend on insurer/file integrations and are deferred.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import success
from app.core.security import CurrentUser, require_authenticated
from app.db.session import get_session
from app.modules.policies import service
from app.modules.policies.mappers import policy_to_dict

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("")
async def list_policies(
    status: str | None = None,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    policies = await service.list_policies(session, user.id, status=status)
    return success([policy_to_dict(p) for p in policies])


@router.get("/{policy_id}")
async def get_policy(
    policy_id: str,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    policy = await service.get_policy(session, user.id, policy_id)
    return success(policy_to_dict(policy))
