# app/database.py
from sqlmodel import SQLModel, create_engine, Session
from app.models import Period, EmployeeRib # Import models to register them
import os

# Load from .env or default
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ribs.db")

# SQLite specific args
connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)

def create_db_and_tables():
    """Creates the database tables based on the models."""
    SQLModel.metadata.create_all(engine)

def get_session():
    """Dependency for FastAPI routes to get a DB session."""
    with Session(engine) as session:
        yield session