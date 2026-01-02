from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

import os

# SQLite database file
# In production, swap with Postgres URL via env var
SQLALCHEMY_DATABASE_URL = "sqlite:///./kaori.db"
# Override with env var if present (e.g. "bigquery://project-id/dataset")
if os.getenv("DB_CONNECTION_STRING"):
    SQLALCHEMY_DATABASE_URL = os.getenv("DB_CONNECTION_STRING")

if "sqlite" in SQLALCHEMY_DATABASE_URL:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
elif "bigquery" in SQLALCHEMY_DATABASE_URL:
    # pip install sqlalchemy-bigquery google-cloud-bigquery
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
else:
    # Postgres / Cloud SQL
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    """Dependency for API routes/engine to get DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
