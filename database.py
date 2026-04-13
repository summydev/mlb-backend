from sqlmodel import SQLModel, create_engine, Session

# This creates a local file named 'mylb.db' in your project folder.
# When you go to production, replace this URL with your Neon/Supabase PostgreSQL URL!
sqlite_file_name = "mylb.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# The engine is the core connection to the database
# echo=True prints the SQL queries to your terminal, which is great for debugging
engine = create_engine(sqlite_url, echo=True) 

def create_db_and_tables():
    # This automatically scans your models.py and creates the tables if they don't exist
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session