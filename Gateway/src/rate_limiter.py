from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request

from .db_init import Account # Assuming UserInDB has an 'id' attribute

def rate_limit_key_func(request: Request) -> str:
    """
    Determines the key for rate limiting.
    Uses user ID if authenticated (read from request.state set by dependency).
    Uses IP address if anonymous.
    Includes scope in the key.
    """
    user: Account | None = getattr(request.state, "user", None)
    scope = request.scope.get("path", "") # Get route path for potential scope use

    if user:
        # print(f"DEBUG rate_limit_key_func: Authenticated User ID={user.id}") # Debugging
        return f"user:{user.id}" # Key includes 'user:' prefix
    else:
        ip = get_remote_address(request)
        # print(f"DEBUG rate_limit_key_func: Anonymous IP={ip}") # Debugging
        return f"ip:{ip}" # Key includes 'ip:' prefix

# Initialize the limiter
limiter = Limiter(key_func=rate_limit_key_func, strategy="fixed-window") # Or "moving-window"

# Note: We apply limits directly via decorators on the routes later.
# The middleware is primarily needed to catch the RateLimitExceeded exception.