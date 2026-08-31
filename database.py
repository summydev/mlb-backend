import os
from sqlmodel import create_engine, SQLModel, Session

# 1. Fetch the database URL from environment variables
# If it doesn't exist, it falls back to a local SQLite database for easy local testing.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mylb_local.db")

# 2. Fix the Render URL quirk
# SQLAlchemy requires 'postgresql://', but Render provides 'postgres://'
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 3. Create the Database Engine
# For Postgres, we don't need the 'check_same_thread' argument that SQLite requires.
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Adding pool_pre_ping=True ensures the server reconnects if the database goes to sleep
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

def create_db_and_tables():
    """Creates the tables in the database if they don't already exist."""
    SQLModel.metadata.create_all(engine)

def get_session():
    """Provides a database session for the FastAPI endpoints."""
    with Session(engine) as session:
        yield session