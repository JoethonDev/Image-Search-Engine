from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import redis.asyncio as redis
import json

from .. import auth, models, dependencies, config

router = APIRouter(tags=["Authentication"])
token_scheme = HTTPBearer() # Reuse for refresh token
ACCESS_TOKEN_CACHE_PREFIX = "jwt_cache:access:"

# --- Helper Functions ---
def get_token_key(account_id: str):
    return f"{ACCESS_TOKEN_CACHE_PREFIX}{account_id}"

async def get_cached_token(account_id: str, redis_client: redis.Redis) -> dict | None:
    access_token_key = get_token_key(account_id)

    try:
        cached_access_token = await redis_client.get(access_token_key)

        if cached_access_token:
            # Optional: Verify if the cached token is *really* still valid (using decode)
            # This adds overhead but guards against clock skew issues if TTLs drift.
            # token_data = auth.decode_token(cached_access_token)
            # if token_data and not token_data.is_refresh:
            print(f"DEBUG: Cache hit for user {account_id}. Returning cached tokens.")
            return json.loads(cached_access_token)
            # else:
            #     print("DEBUG: Cached access token found but invalid/expired, proceeding to issue new.")

    except Exception as e:
        # Log Redis errors but proceed to issue token if possible
        print(f"WARNING: Redis GET error during login for user {account_id}: {e}")
    
    return None


async def set_cached_token(account_id: str, redis_client: redis.Redis, token: dict):
    access_token_key = get_token_key(account_id)
    access_token = json.dumps(token)
    try:
        # Use pipeline for atomic operations if needed, but SET with EX is usually fine here
        await redis_client.set(access_token_key, access_token, ex=int(config.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60))
        print(f"DEBUG: Stored new tokens in cache for user {account_id}")
        return True
    except Exception as e:
        # Log Redis errors but token was already generated, so login succeeds
        print(f"WARNING: Redis SET error during login for user {account_id}: {e}")
    return False

# --- Routes ---
@router.post("/register", response_model=models.UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(user: models.UserCreate, db: Session = Depends(dependencies.get_db)):
    """Register a new user."""
    # Check for username/email
    db_user = auth.get_user_by_filter(
        filter_condition=(auth.Account.username == user.username or auth.Account.email == user.username),
        db=db
    )
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or Email already registered",
        )
    hashed_password = auth.get_password_hash(user.password)
    user_data = user.model_dump(exclude={"password"})
    user_data["hashed_password"] = hashed_password
    try:
        new_account = auth.create_db_user(user_data, db)
        # `create_db_user` already commits, db.refresh() populates new_account.account_id
    except Exception as e:
        # Log the database error e
        print(f"ERROR: Database error during account creation: {e}")
        db.rollback() # Rollback if commit failed or error occurred before/during commit
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create account record."
        )
    
    # TODO, Update this part before uncommenting
    # --- 3. Prepare data and Trigger User Service (Asynchronously) ---
    # user_detail_payload = models.UserDetailPayload(
    #     account_id=new_account.account_id,
    #     name=user_input.name,
    #     phone_number=user_input.phone_number,
    #     address=user_input.address,
    #     date_of_birth=user_input.date_of_birth,
    # )


    # # Define the task to run in the background
    # async def call_user_service(payload: models.UserDetailPayload):
    #     user_service_url = f"{config.settings.USERS_SERVICE_URL}/users/" # Define specific endpoint
    #     print(f"DEBUG: Calling User Service at {user_service_url} with payload: {payload.model_dump_json()}")
    #     try:
    #         response = await http_client.post(user_service_url, json=payload.model_dump(mode='json')) # Ensure dates are serialized correctly
    #         response.raise_for_status() # Raise exception for 4xx/5xx errors
    #         print(f"SUCCESS: User service call successful for account_id {payload.account_id}. Response: {response.text}")
    #         # Optionally process response if needed
    #     except httpx.RequestError as exc:
    #         # Log specific HTTP request errors (connection, timeout, etc.)
    #         print(f"ERROR: Could not reach User Service for account_id {payload.account_id}: {exc}")
    #         # Implement retry or reconciliation logic if critical
    #     except httpx.HTTPStatusError as exc:
    #         # Log HTTP errors (4xx, 5xx) from the User Service
    #         print(f"ERROR: User Service returned error for account_id {payload.account_id}: {exc.response.status_code} - {exc.response.text}")
    #         # Implement retry or reconciliation logic if critical
    #     except Exception as e:
    #         # Log any other unexpected errors during the call
    #         print(f"ERROR: Unexpected error calling User Service for account_id {payload.account_id}: {e}")

    # # Add the task to run after the response is sent
    # background_tasks.add_task(call_user_service, user_detail_payload)

    # # --- 4. Return Success Response (Gateway Account Creation) ---
    # # The response_model ensures only AccountPublic fields are returned
    # # even though new_account is a full SQLAlchemy object.
    # print(f"SUCCESS: Account created for {new_account.email}. User service call scheduled.")
    return new_account


@router.post("/login", response_model=models.Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(dependencies.get_db), redis_client: redis.Redis = Depends(dependencies.get_redis)):
    """Authenticate user and return access and refresh tokens."""
    # print(f"DEBUG login attempt: username={form_data.username}") # Debugging

    # --- 1. Check Redis Connection ---
    if not redis_client:
        # Handle case where Redis connection failed in dependency
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication support services unavailable.")
    
    # --- 2. Verify Credentials ---
    user = auth.get_user_by_email(form_data.username, db) or auth.get_user_by_username(form_data.username, db) # Using email or username here
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise auth.CredentialsException(detail="Incorrect email or password")
    
    # --- 3. Get Token from cache if not expired ---
    account_id_str = str(user.account_id)
    cached_token = await get_cached_token(account_id_str)

    if not cached_token:
        # --- 4. Re-issue Access/Refresh Token ---
        access_token = auth.create_token(
            data={"account_id": str(user.account_id)} # Use str(user.account_id) if using UUIDs
        )
        refresh_token = auth.create_token(data={"account_id": str(user.account_id)}, is_refresh=True) 
        pass

        # --- 5. Store New Tokens in Cache ---
        cached_token = {"access_token": access_token, "refresh_token": refresh_token}
        await set_cached_token(account_id_str, redis_client, cached_token)
        # On failure add background task to add it later

    cached_token.update({"token_type": "bearer"})
    return cached_token



@router.post("/refresh-token", response_model=models.Token)
async def refresh_access_token(token: HTTPAuthorizationCredentials = Depends(token_scheme), db: Session = Depends(dependencies.get_db), redis_client: redis.Redis = Depends(dependencies.get_redis)):
    """Get a new access token using a valid refresh token."""
    token_data = auth.decode_token(token.credentials)

    if not token_data or not token_data.is_refresh:
        raise auth.CredentialsException(detail="Invalid or expired refresh token")
    
    # Check refresh token to be latest
    account_id = token_data.user_id
    account_id_str = str(account_id)
    access_token = await get_cached_token(account_id_str, redis_client)
    if not access_token or access_token['refresh_token'] != token:
        raise auth.CredentialsException(detail="Invalid or expired refresh token")

    user = auth.get_user_by_id(account_id, db)
    if not user:
        raise auth.CredentialsException(detail="User not found for refresh token")

    # Issue new tokens
    new_access_token = auth.create_token(
        data={"account_id": account_id_str}
    )
    new_refresh_token = auth.create_token(data={"account_id": account_id_str}, is_refresh=True) # Use str(user.account_id) if using UUIDs

    # Set Cached Token
    await set_cached_token(account_id_str, redis_client, {"access_token": new_access_token, "refresh_token": new_refresh_token})

    # Optionally issue a new refresh token as well (for refresh token rotation)
    # new_refresh_token = auth.create_refresh_token(data={"sub": str(user.account_id)})
    # For simplicity, we reuse the old refresh token until it expires
    return {"access_token": new_access_token, "refresh_token": new_refresh_token, "token_type": "bearer"}

# Do here sending request to user service using _call_internal_service!
@router.patch("/accounts/update", response_model=models.AccountPublic)
async def update_account(
    update_data: models.AccountUpdate,
    db: Session = Depends(dependencies.get_db),
    current_user: auth.Account = Depends(dependencies.get_current_user), # Get current user (Account object)
    http_client: httpx.AsyncClient = Depends(get_http_client),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Update the authenticated user's account details (username, email, password).
    Optionally forwards other details (name, phone, etc.) to the User Service.
    """
    account_id_to_update = current_user.account_id
    update_payload_dict = update_data.model_dump(exclude_unset=True) # Get only provided fields

    if not update_payload_dict:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No update data provided."
        )

    account_fields_to_update = {}
    user_service_fields_to_update = {}

    # --- 1. Prepare Account Update Data & Check Conflicts ---
    if "username" in update_payload_dict:
        new_username = update_payload_dict["username"]
        # Check if new username is taken by *another* user
        existing_user = auth.get_user_by_filter(
            (auth.Account.username == new_username) & (auth.Account.account_id != account_id_to_update),
            db=db
        )
        if existing_user:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken.")
        account_fields_to_update["username"] = new_username

    if "email" in update_payload_dict:
        new_email = update_payload_dict["email"]
        # Check if new email is taken by *another* user
        existing_user = auth.get_user_by_filter(
            (auth.Account.email == new_email) & (auth.Account.account_id != account_id_to_update),
            db=db
        )
        if existing_user:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered by another account.")
        account_fields_to_update["email"] = new_email

    if "password" in update_payload_dict and update_payload_dict["password"] is not None:
        account_fields_to_update["hashed_password"] = auth.get_password_hash(update_payload_dict["password"])

    # --- 2. Update Account in Gateway DB ---
    if account_fields_to_update:
        try:
            db.query(auth.Account).filter(auth.Account.account_id == account_id_to_update).update(
                account_fields_to_update, synchronize_session="fetch"
            )
            # Add updated_at logic if not automatically handled by DB trigger/onupdate
            # db.query(auth.Account).filter(auth.Account.account_id == account_id_to_update).update({"updated_at": func.now()})
            db.commit()
            db.refresh(current_user) # Refresh the current_user object with updated data
            print(f"SUCCESS: Updated account fields for account_id {account_id_to_update}")
        except Exception as e:
            # Log database error e
            print(f"ERROR: Database error during account update: {e}")
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update account record."
            )

    # --- 3. Prepare and Trigger User Service Update (if needed) ---
    user_detail_fields = ["name", "phone_number", "address", "date_of_birth"]
    for field in user_detail_fields:
        if field in update_payload_dict:
            user_service_fields_to_update[field] = update_payload_dict[field]

    if user_service_fields_to_update:
        user_update_payload = models.UserUpdate(**user_service_fields_to_update)

        # Define background task for User Service call
        async def call_user_service_update(payload: models.UserUpdate, acc_id: int):
            # Assuming User Service uses account_id in the URL for PATCH/PUT
            user_service_url = f"{config.settings.USERS_SERVICE_URL}/users/account/{acc_id}" # Adjust endpoint as needed
            print(f"DEBUG: Calling User Service PATCH at {user_service_url} for account_id {acc_id}")
            try:
                # Use PATCH for partial updates
                response = await http_client.patch(user_service_url, json=payload.model_dump(mode='json', exclude_unset=True))
                response.raise_for_status()
                print(f"SUCCESS: User service PATCH successful for account_id {acc_id}. Response: {response.text}")
            except httpx.RequestError as exc:
                print(f"ERROR: Could not reach User Service for PATCH account_id {acc_id}: {exc}")
            except httpx.HTTPStatusError as exc:
                print(f"ERROR: User Service PATCH returned error for account_id {acc_id}: {exc.response.status_code} - {exc.response.text}")
            except Exception as e:
                print(f"ERROR: Unexpected error calling User Service PATCH for account_id {acc_id}: {e}")

        background_tasks.add_task(call_user_service_update, user_update_payload, account_id_to_update)
        print(f"INFO: User service update task scheduled for account_id {account_id_to_update}")

    # --- 4. Return Updated Account Data ---
    # response_model ensures only AccountPublic fields are sent
    return current_user

# Temp Route
from ..db_init import Account

@router.get("/view")
async def view_accounts(db: Session = Depends(dependencies.get_db)):
    accounts = db.query(Account).all()
    return {"accounts" : accounts}
