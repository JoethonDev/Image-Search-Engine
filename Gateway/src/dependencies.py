from typing import Optional
from fastapi import Depends, HTTPException, Response, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import redis.asyncio as redis
import httpx

from . import auth
from .models import TokenData
from .db_init import Account
from .config import settings

# Scheme for extracting token from header
token_scheme = HTTPBearer()
DATABASE_URL = "postgresql://avnadmin:AVNS_pJ81YzNkQZ50I53daVx@image-search-image-search-engine.h.aivencloud.com:28638/image-search"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

async def get_token_data(token: HTTPAuthorizationCredentials = Depends(token_scheme)) -> TokenData:
    """Dependency to decode token, raises 401 if invalid/missing."""
    token_data = auth.decode_token(token.credentials)
    if not token_data:
        raise auth.credentials_exception
    return token_data

async def get_current_user(token_data: TokenData = Depends(get_token_data)) -> Account:
    """Dependency to get the current authenticated user from valid token data."""
    if token_data.is_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type: Refresh token used where Access token expected",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = auth.get_user_by_id(token_data.user_id)
    if user is None:
        # print(f"DEBUG: User not found for ID: {token_data.user_id}") # Debugging
        raise auth.credentials_exception
    # print(f"DEBUG: Found user: {user.email}") # Debugging
    return user

async def get_optional_current_user(
    request: Request, # Inject request object
    token: Optional[HTTPAuthorizationCredentials] = Depends(token_scheme)
) -> Optional[Account]:
    """
    Dependency that attempts to get the current user.
    Returns Account if authentication is successful, None otherwise.
    Crucially, stores the result in request.state for the rate limiter key_func.
    """
    user = None
    if token:
        token_data = auth.decode_token(token.credentials)
        if token_data and not token_data.is_refresh:
            user = auth.get_user_by_id(token_data.user_id)

    request.state.user = user # Store user (or None) in request state
    # print(f"DEBUG get_optional_current_user: request.state.user = {user.email if user else None}") # Debugging
    return user

async def _call_internal_service(
    http_client: httpx.AsyncClient,
    method: str,
    service_base_url: str,
    path: str,
    account_id: Optional[int] = None, # For X-User-ID
    json_payload: Optional[dict] = None,
    params: Optional[dict] = None,
    body: Optional[bytes] = None,
    headers: Optional[dict] = {}
    # Add service-to-service auth token if needed
) -> httpx.Response: # Return the raw httpx response
    """Helper to make calls to internal microservices."""
    target_url = f"{service_base_url}/{path}" # Ensure path starts with / or logic handles it

    if account_id:
        headers["X-User-ID"] = str(account_id)
    # Add internal auth headers if necessary: headers["X-Internal-Auth"] = "..."

    try:
        response = await http_client.request(
            method=method,
            url=target_url,
            headers=headers,
            json=json_payload, # Handles json serialization and content-type header
            params=params,
            content=body,
            timeout=15.0 # Maybe shorter timeout for internal calls
        )
        response.raise_for_status() # Raise HTTPStatusError for 4xx/5xx
        excluded_response_headers = ["content-encoding", "transfer-encoding", "connection"]
        response_headers = {
            key: value for key, value in response.headers.items() if key.lower() not in excluded_response_headers
        }

        response = Response(
            content=response.content,
            status_code=response.status_code,
            headers=response_headers,
            # media_type=rp.headers.get("content-type") # Let FastAPI handle this based on content
        )
        return response
        
    except httpx.TimeoutException as exc:
        print(f"ERROR: Timeout calling internal service {method} {target_url}: {exc}")
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Upstream service timed out.")

    except httpx.HTTPStatusError as exc:
        print(f"ERROR: Internal service {method} {target_url} returned error: {exc.response.status_code} - {exc.response.text}")
        raise # Or handle differently
    except httpx.RequestError as exc:
        print(f"ERROR: Could not reach internal service {method} {target_url}: {exc}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Upstream service error: {e}")
    
    except Exception as e:
        print(f"ERROR: Unexpected error calling internal service {method} {target_url}: {e}")
        raise

# Dependency to get a database session
async def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Get Redis
async def get_redis() -> redis.Redis:
    """Dependency to get an async Redis connection."""
    # Consider using a connection pool for production
    try:
        # Create client (pool is better for prod)
        client = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        # Check connection
        await client.ping()
        yield client
    except Exception as e:
         print(f"ERROR: Could not connect to Redis: {e}")
         # Decide how to handle Redis connection failure - maybe raise HTTPException?
         # For now, yield None and let endpoints handle it, or raise 500
         yield None # Or raise HTTPException(503, "Cache service unavailable")
    finally:
        if 'client' in locals() and client:
            await client.aclose() # Close connection/pool