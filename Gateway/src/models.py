from pydantic import BaseModel, EmailStr, Field, field_validator 
from typing import Optional
from datetime import date

# --- User Models ---
class UserBase(BaseModel):
    email: EmailStr
    username: str
    name: str = ""
    phone_number: Optional[str] = ""
    address: Optional[str] = ""
    date_of_birth: Optional[date] = ""

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int

class AccountUpdate(BaseModel):
    # Fields for Account table (handled by Gateway)
    email: Optional[EmailStr] = None
    password: Optional[str] = None # Enforce min length if provided

    # Fields potentially for User table (to be forwarded)
    name: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None
    date_of_birth: Optional[date] = None

    @field_validator('password')
    def password_complexity(cls, v):
        if v and len(v) < 8:
            raise ValueError("Password should be more than 8 characters")
        else:
            return v

    # Ensure at least one field is provided for update
    @field_validator('*', pre=True, always=True)
    def check_at_least_one_field(cls, v, values):
        if not any(values.values()):
            raise ValueError("At least one field must be provided for update")
        return v # This validator might need refinement based on Pydantic version

class UserUpdate(BaseModel):
    # Fields potentially for User table (to be forwarded)
    name: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None
    date_of_birth: Optional[date] = None

    @field_validator('*', pre=True, always=True)
    def check_at_least_one_field_payload(cls, v, values):
        if not any(values.values()):
             raise ValueError("At least one user detail field must be provided for update")
        return v

# --- Token Models ---
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    user_id: Optional[int] = None # Use str if using UUIDs
    is_refresh: bool = False

# --- Health Model ---
class HealthStatus(BaseModel):
    status: str