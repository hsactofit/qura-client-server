"""Asset CRUD, scoped to the authenticated user."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.models.assets import Asset
from app.modules.assets.schemas import AssetCreateRequest, AssetUpdateRequest


async def list_assets(
    session: AsyncSession, user_id: str, *, asset_type: str | None = None
) -> list[Asset]:
    stmt = select(Asset).where(Asset.user_id == user_id)
    if asset_type:
        stmt = stmt.where(Asset.asset_type == asset_type)
    stmt = stmt.order_by(Asset.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_asset(session: AsyncSession, user_id: str, asset_id: str) -> Asset:
    result = await session.execute(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == user_id)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise ApiError("Asset not found", status_code=404)
    return asset


def _apply(asset: Asset, body: AssetCreateRequest | AssetUpdateRequest) -> None:
    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        if field == "property_area_sqft" and value is not None:
            value = Decimal(str(value))
        setattr(asset, field, value)


async def create_asset(
    session: AsyncSession, user_id: str, body: AssetCreateRequest
) -> Asset:
    asset = Asset(user_id=user_id, asset_type=body.asset_type)
    _apply(asset, body)
    session.add(asset)
    await session.flush()
    return asset


async def update_asset(
    session: AsyncSession, user_id: str, asset_id: str, body: AssetUpdateRequest
) -> Asset:
    asset = await get_asset(session, user_id, asset_id)
    _apply(asset, body)
    await session.flush()
    return asset


async def delete_asset(session: AsyncSession, user_id: str, asset_id: str) -> None:
    asset = await get_asset(session, user_id, asset_id)
    await session.delete(asset)
    await session.flush()
