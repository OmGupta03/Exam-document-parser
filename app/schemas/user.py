from datetime import datetime
import uuid
from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    email: EmailStr = Field(..., description="Unique email address of the user")


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, description="User password (minimum 8 characters)")


class UserResponse(UserBase):
    id: uuid.UUID = Field(..., description="Unique user identifier (UUID)")
    created_at: datetime = Field(..., description="Timestamp when user was registered")

    model_config = {"from_attributes": True}


class UserInDB(UserResponse):
    hashed_password: str
