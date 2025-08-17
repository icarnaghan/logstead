from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DOCKER = os.getenv("DOCKER", "0") == "1"
if DOCKER:
    DATABASE_URL = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/logstead"
    )
else:
    DATABASE_URL = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/logstead"
    )

engine = create_async_engine(DATABASE_URL, echo=True, future=True)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()
