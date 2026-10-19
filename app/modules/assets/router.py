"""Asset routes.

  GET    /assets           list (optional ?asset_type=)
  POST   /assets           create
  PUT    /assets/{id}      update (ownership-enforced)
  DELETE /assets/{id}      delete (ownership-enforced)

All reads and writes are scoped to the authenticated user; writes require CSRF.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import success
from app.core.security import CurrentUser, enforce_csrf, require_authenticated
from app.db.session import get_session
from app.modules.assets import service
from app.modules.assets.mappers import asset_to_dict
from app.modules.assets.schemas import AssetCreateRequest, AssetUpdateRequest

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("")
async def list_assets(
    asset_type: str | None = None,
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    assets = await service.list_assets(session, user.id, asset_type=asset_type)
    return success([asset_to_dict(a) for a in assets])


@router.post("")
async def create_asset(
    body: AssetCreateRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    asset = await service.create_asset(session, user.id, body)
    return success(asset_to_dict(asset), "Asset created")


@router.put("/{asset_id}")
async def update_asset(
    asset_id: str,
    body: AssetUpdateRequest,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    asset = await service.update_asset(session, user.id, asset_id, body)
    return success(asset_to_dict(asset), "Asset updated")


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: str,
    _csrf: None = Depends(enforce_csrf),
    user: CurrentUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await service.delete_asset(session, user.id, asset_id)
    return success(None, "Asset deleted")
