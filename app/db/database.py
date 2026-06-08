from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
_is_postgres = bool(DATABASE_URL and DATABASE_URL.startswith("postgresql"))
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=_is_postgres,   # test connections before use; handles pod restarts
    pool_recycle=300 if _is_postgres else -1,  # recycle every 5 min to avoid server-side timeouts
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

Base = declarative_base()
