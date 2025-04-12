import httpx
from fastapi import APIRouter, Request, Response, Depends, HTTPException, status
from typing import Optional
from slowapi.util import get_remote_address

from ..config import settings
from ..dependencies import get_current_user, get_optional_current_user, _call_internal_service # Import both
from ..db_init import Account # Import User model
from ..rate_limiter import limiter # Import the limiter instance

router = APIRouter()

async def _proxy_request(
    request: Request,
    target_base_url: str,
    user: Optional[Account] = None # Accept optional user
    ):
    """Helper function to perform the proxy request."""
    # Construct target URL
    # request.url.path already contains the prefix like '/search', so remove it if needed
    # or adjust target_base_url not to include it if already present.
    # Let's assume target_base_url is just the scheme+host+port
    # path = request.url.path # Full path like /search/images
    # Using path parameters to capture the rest of the path
    # The path parameter 'sub_path' will be available in the calling route function
    with httpx.AsyncClient as client:
        sub_path = request.path_params.get("sub_path", "")
        # target_url = f"{target_base_url}/{sub_path}"
        method = request.method
        # if request.url.query:
        #     target_url += f"?{request.url.query}"

        body = await request.body()

        try:
            response = await _call_internal_service(http_client=client, method=method,service_base_url=target_base_url, path=sub_path, params=request.url.query, body=body)
            return response
        except httpx.TimeoutException:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Upstream service timed out.")
        except httpx.RequestError as e:
            # Log the error e
            print(f"ERROR: Upstream request error: {e}")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Upstream service error: {e}")
        except Exception as e:
            print(f"ERROR: Internal server error: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {e}")



# --- Search Proxy ---
# Apply rate limiting DECORATORS here
# The key_func will differentiate user/ip
# Apply multiple limits: per minute (applies to all), per day (differentiated by scope)
@router.api_route(
    "/search/{sub_path:path}", # Capture everything after /search/
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    dependencies=[Depends(get_optional_current_user)], # IMPORTANT: Run this BEFORE limiter
    tags=["Proxy - Search"]
)
@limiter.limit("10/minute", key_func=lambda r: r.state.user.id if getattr(r.state, 'user', None) else get_remote_address(r)) # Per-minute limit for all
@limiter.limit("100/day", key_func=lambda r: r.state.user.id if getattr(r.state, 'user', None) else None) # Daily limit only for authenticated users
@limiter.limit("50/day", key_func=lambda r: get_remote_address(r) if not getattr(r.state, 'user', None) else None) # Daily limit only for anonymous users
async def proxy_search(request: Request):
    """Proxy requests to the Search service with rate limiting."""
    # get_optional_current_user already ran and set request.state.user
    user: Optional[Account] = getattr(request.state, "user", None)
    return await _proxy_request(request, settings.SEARCH_SERVICE_URL, user)


# --- Users Proxy ---
@router.api_route(
    "/users/{sub_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    dependencies=[Depends(get_current_user)], # Requires authentication
    tags=["Proxy - Users"]
)
async def proxy_users(request: Request, current_user: Account = Depends(get_current_user)):
    """Proxy requests to the Users service. Requires authentication."""
    # --- Add this check ---
    sub_path = request.path_params.get("sub_path", "")
    if sub_path.lower() == "update" or sub_path.lower().startswith("update/"):
         # Block requests to /users/update explicitly
         # You could return 404 Not Found or 405 Method Not Allowed
         print(f"INFO: Blocking direct proxy request to /users/update path.")
         raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This update operation should be performed via /accounts/update."
            # Or status_code=status.HTTP_405_METHOD_NOT_ALLOWED
         )
    # --- End of check ---
    return await _proxy_request(request, settings.USERS_SERVICE_URL, current_user)

# --- Merchants Proxy ---
@router.api_route(
    "/merchants/{sub_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    dependencies=[Depends(get_current_user)], # Requires authentication
    tags=["Proxy - Merchants"]
)
async def proxy_merchants(request: Request, current_user: Account = Depends(get_current_user)):
    """Proxy requests to the Merchants service. Requires authentication."""
    return await _proxy_request(request, settings.MERCHANTS_SERVICE_URL, current_user)

# Add specific root routes if needed, e.g. /users/ or /merchants/
@router.api_route(
    "/users/",
    methods=["GET", "POST"], # Example methods
    include_in_schema=False, # Hide from docs if covered by path param version
    dependencies=[Depends(get_current_user)],
)
async def proxy_users_root(request: Request, current_user: Account = Depends(get_current_user)):
     request.path_params["sub_path"] = "" # Set sub_path for root
     return await _proxy_request(request, settings.USERS_SERVICE_URL, current_user)

@router.api_route(
    "/merchants/",
    methods=["GET", "POST"], # Example methods
    include_in_schema=False,
    dependencies=[Depends(get_current_user)],
)
async def proxy_merchants_root(request: Request, current_user: Account = Depends(get_current_user)):
     request.path_params["sub_path"] = "" # Set sub_path for root
     return await _proxy_request(request, settings.MERCHANTS_SERVICE_URL, current_user)