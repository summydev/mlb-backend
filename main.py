# main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status, Depends
from sqlmodel import Session, select
from database import create_db_and_tables, get_session, engine
from models import User
from schemas import UserRegister, UserLogin, TokenResponse
from security import get_password_hash, verify_password, create_access_token, create_refresh_token

# This ensures the database tables are created when the app starts
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="myLB Auth API", version="1.0", lifespan=lifespan)

@app.post("/auth/register", status_code=status.HTTP_200_OK)
async def register_user(user_data: UserRegister, session: Session = Depends(get_session)):
    email = user_data.email.lower()
    
    # 1. Check if email already exists
    statement = select(User).where(User.email == email)
    existing_user = session.exec(statement).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Log in instead?"
        )
    
    # 2. Create new user
    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        name=user_data.name,
        email=email,
        hashed_password=hashed_password,
        is_verified=False  # <-- Make sure this is False again!
    )
    
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    
    # 3. Generate the mock verification link
    # We use a hardcoded token for now to match our /auth/verify-email endpoint
    verification_link = f"https://mlb-backend-9jmu.onrender.com/auth/verify-email?token=mock-magic-link-token"
    
    # 4. Print the "email" to the Render logs
    print("\n" + "="*50)
    print(f"📧 MOCK EMAIL SENT TO: {email}")
    print(f"🔗 CLICK HERE TO VERIFY: {verification_link}")
    print("="*50 + "\n")
    
    return {
        "message": "Verify your email",
        "user_id": new_user.id
    }
@app.post("/auth/login", response_model=TokenResponse)
async def login_user(credentials: UserLogin, session: Session = Depends(get_session)):
    email = credentials.email.lower()
    
    # 1. Fetch user from database
    statement = select(User).where(User.email == email)
    db_user = session.exec(statement).first()
    
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password. Please try again."
        )

    # 2. Verify password
    if not verify_password(credentials.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password. Please try again."
        )

    # 3. Check verification status
    if not db_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email first."
        )

    # 4. Generate Tokens
    access_token = create_access_token(data={"sub": db_user.email})
    refresh_token = create_refresh_token(data={"sub": db_user.email})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": db_user.id,
            "email": db_user.email,
            "name": db_user.name
        }
    }

 