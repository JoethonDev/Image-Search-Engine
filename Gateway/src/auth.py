from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from fastapi import Depends

from .config import settings
from .dependencies import get_db
from .models import TokenData
from .db_init import Account

# --- Helper ---
def get_attributes_from_dict(cls):
    attributes = [attr for attr in cls.__dict__ if not attr.startswith("__") and not callable(getattr(cls, attr))]
    return attributes

def class_builder(data: dict, model):
    cls_attr = get_attributes_from_dict(model)
    model_instance = model()
    for key, value in data.items():
        if key in cls_attr:
            setattr(model_instance, key, value)
    return model_instance

# --- Password Hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

# Replace with ORM, Real Data
fake_users_db: Dict[int, Account] = {}
user_id_counter = 1

def get_user_by_username(username: str, db: Session = Depends(get_db)) -> Optional[Account]:
    # Get user from Database
    return db.query(Account).filter(Account.username == username).first()

def get_user_by_email(email: str, db: Session = Depends(get_db)) -> Optional[Account]:
    return db.query(Account).filter(Account.email == email).first()

def get_user_by_id(user_id: int, db: Session = Depends(get_db)) -> Optional[Account]:
    return db.query(Account).filter(Account.account_id == user_id).first()

def get_user_by_filter(filter_condition: bool, db: Session = Depends(get_db)) -> Optional[Account]:
    return db.query(Account).filter(filter_condition).first()

def create_db_user(user_data: Dict[str, Any], db: Session = Depends(get_db)) -> Account:
    account = class_builder(user_data, Account)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account

# --- JWT Token Handling ---
def create_token(data: dict, expires_delta: timedelta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), is_refresh = False) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire, "is_refresh": is_refresh})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> Optional[TokenData]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id: Optional[int] = payload.get("account_id")
        is_refresh: bool = payload.get("is_refresh", False)
        if user_id is None:
            # print("DEBUG: User ID (sub) not in token payload") # Debugging
            return None
        # print(f"DEBUG: Decoded token: user_id={user_id}, is_refresh={is_refresh}") # Debugging
        return TokenData(user_id=user_id, is_refresh=is_refresh)
    except JWTError as e:
        # print(f"DEBUG: JWTError decoding token: {e}") # Debugging
        return None
    except Exception as e:
        # print(f"DEBUG: Unexpected error decoding token: {e}") # Debugging
        return None

# --- Credentials Exception ---
credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

class CredentialsException(HTTPException):
    def __init__(self, status_code = status.HTTP_401_UNAUTHORIZED, detail = "Could not validate credentials", headers = {"WWW-Authenticate": "Bearer"}):
        super().__init__(status_code, detail, headers)