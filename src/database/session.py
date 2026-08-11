from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.settings import settings


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
)
