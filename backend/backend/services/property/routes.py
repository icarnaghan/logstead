from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from backend.db import SessionLocal
from backend.models import Property, PropertySchema

router = APIRouter(prefix="/properties", tags=["properties"])


async def get_db():
    async with SessionLocal() as session:
        yield session


@router.get("/", response_model=List[PropertySchema])
async def list_properties(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Property))
    return result.scalars().all()


@router.get("/{property_id}", response_model=PropertySchema)
async def get_property(property_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Property).where(Property.id == property_id))
    property = result.scalar_one_or_none()
    if not property:
        raise HTTPException(status_code=404, detail="Property not found")
    return property


@router.post("/", response_model=PropertySchema, status_code=status.HTTP_201_CREATED)
async def create_property(property: PropertySchema, db: AsyncSession = Depends(get_db)):
    db_property = Property(**property.dict(exclude_unset=True))
    db.add(db_property)
    await db.commit()
    await db.refresh(db_property)
    return db_property
