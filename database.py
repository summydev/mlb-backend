import os
from sqlmodel import SQLModel, create_engine, Session

# This tells FastAPI: "Use the Render secret if it exists. If not, use local SQLite."
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///mylb.db")
# Create the engine
# NEW: Added pool_pre_ping=True to prevent SSL connection drops
engine = create_engine(DATABASE_URL, echo=True, pool_pre_ping=True)

 

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session