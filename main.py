# main.py
from fastapi import FastAPI, HTTPException, status
from schemas import UserRegister, UserLogin, TokenResponse
from security import get_password_hash, verify_password, create_access_token, create_refresh_token

app = FastAPI(title="myLB Auth API", version="1.0")

# --- Mock Database ---
fake_users_db = {}

@app.post("/auth/register", status_code=status.HTTP_200_OK)
async def register_user(user: UserRegister):
    # Enforce lowercase email as per specs
    email = user.email.lower()
    
    if email in fake_users_db:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Log in instead?"
        )
    
    hashed_password = get_password_hash(user.password)
    
    # Save user (marked as unverified initially)
    fake_users_db[email] = {
        "id": f"user_{len(fake_users_db) + 1}",
        "name": user.name,
        "email": email,
        "password": hashed_password,
        "is_verified": False 
    }
    
    return {
        "message": "Verify your email",
        "user_id": fake_users_db[email]["id"]
    }

@app.get("/auth/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(token: str):
    """
    This simulates the endpoint hit by the deep link: myLB://verify?token={token}
    In reality, you would decode the token to find the user. Here we mock it.
    """
    if token != "mock-magic-link-token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification token."
        )
    
    # Mocking a successful verification for our test user
    test_email = "test@example.com"
    if test_email in fake_users_db:
        fake_users_db[test_email]["is_verified"] = True
        
        # Generate initial tokens so the user is immediately logged in
        access_token = create_access_token(data={"sub": test_email})
        refresh_token = create_refresh_token(data={"sub": test_email})
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "message": "Account verified and active."
        }
        
    return {"message": "Verification successful."}

@app.post("/auth/login", response_model=TokenResponse)
async def login_user(credentials: UserLogin):
    email = credentials.email.lower()
    
    # 1. Check if user exists
    user_data = fake_users_db.get(email)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password. Please try again."
        )

    # 2. Verify password
    if not verify_password(credentials.password, user_data["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password. Please try again."
        )

    # 3. Check verification status
    if not user_data["is_verified"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email first."
        )

    # 4. Generate Tokens
    access_token = create_access_token(data={"sub": email})
    refresh_token = create_refresh_token(data={"sub": email})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user_data["id"],
            "email": email,
            "name": user_data["name"]
        }
    }