from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from .rate_limiter import limiter, _rate_limit_exceeded_handler, SlowAPIMiddleware
from .routers import health_router, auth_router, proxy_router
from .db_init import create_tables
from .config import settings

# from . import auth, config # For initial admin user creation if needed

# --- Initial Admin User ---
# Uncomment if using ADMIN vars in .env - run ONLY ONCE or add check
# def create_initial_admin():
#     if config.settings.ADMIN_EMAIL and config.settings.ADMIN_PASSWORD:
#         admin_user = auth.get_user_by_email(config.settings.ADMIN_EMAIL)
#         if not admin_user:
#             hashed_password = auth.get_password_hash(config.settings.ADMIN_PASSWORD)
#             auth.create_db_user({
#                 "email": config.settings.ADMIN_EMAIL,
#                 "hashed_password": hashed_password
#             })
#             print(f"Admin user '{config.settings.ADMIN_EMAIL}' created.")
# create_initial_admin() # Call it here - BE CAREFUL IN PRODUCTION

print(settings.ACCESS_TOKEN_EXPIRE_MINUTES)
# --- FastAPI App Setup ---
app = FastAPI(
    title="Image Search API Gateway",
    description="Handles authentication and proxies requests to downstream services.",
    version="0.1.0",
)

# --- Middleware ---

# Must be before routers
# Add the SlowAPIMiddleware to handle exceptions globally
# app.add_middleware(SlowAPIMiddleware) # No longer needed if using exception handler directly? Let's keep handler.

# CORS (Cross-Origin Resource Sharing) - Allow frontend requests
origins = [
    "http://localhost",
    "http://localhost:3000", # Example frontend dev server
    "*"
    # Add your deployed frontend URL here
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Allow all methods
    allow_headers=["*"], # Allow all headers
)

# Add rate limiter state and exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# --- Routers ---
app.include_router(health_router.router, prefix="") # /health
app.include_router(auth_router.router, prefix="")   # /register, /login, /refresh-token
app.include_router(proxy_router.router, prefix="")  # /search, /users, /merchants proxy routes

# --- Root Endpoint ---
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the API Gateway"}

# --- App startup initialization ---
@app.on_event("startup")
def startup_event():
    create_tables()