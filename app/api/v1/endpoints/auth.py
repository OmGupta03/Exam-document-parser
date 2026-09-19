from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User
from app.schemas.token import LoginRequest, Token
from app.schemas.user import UserCreate, UserResponse

router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Creates a new user account with email and password."
)
async def register(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Create a new user."""
    # Check if user already exists
    stmt = select(User).where(User.email == user_in.email.lower())
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists."
        )

    # Hash password and persist
    new_user = User(
        email=user_in.email.lower(),
        hashed_password=get_password_hash(user_in.password)
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


@router.post(
    "/login",
    response_model=Token,
    summary="User Login (OAuth2 Form)",
    description="OAuth2 compatible token login, accepts application/x-www-form-urlencoded username (email) and password."
)
async def login_oauth2(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """OAuth2 password flow token login."""
    stmt = select(User).where(User.email == form_data.username.lower())
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expires_in_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    access_token = create_access_token(
        subject=user.id,
        expires_delta=timedelta(seconds=expires_in_seconds)
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in_seconds
    }


@router.post(
    "/login/json",
    response_model=Token,
    summary="User Login (JSON Body)",
    description="JSON login endpoint accepting email and password in request body."
)
async def login_json(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Direct JSON token login."""
    stmt = select(User).where(User.email == login_data.email.lower())
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expires_in_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    access_token = create_access_token(
        subject=user.id,
        expires_delta=timedelta(seconds=expires_in_seconds)
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in_seconds
    }


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get Current Authenticated User",
    description="Returns profile information for the currently authenticated bearer token user."
)
async def get_me(
    current_user: User = Depends(get_current_user)
) -> Any:
    """Retrieve own user details."""
    return current_user
