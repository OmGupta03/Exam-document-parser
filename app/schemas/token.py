from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type, typically 'bearer'")
    expires_in: int = Field(..., description="Token lifespan in seconds")


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    exp: Optional[int] = None


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="User account email")
    password: str = Field(..., description="User account password")
