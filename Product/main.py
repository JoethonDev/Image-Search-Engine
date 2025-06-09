from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
import product_router
from database import create_postgres_tables, create_qdrant_collection

# --- FastAPI App Setup ---
app = FastAPI(
    title="Product Service",
    description="Handles crud operations on products.",
    version="0.1.0",
)

# from .routers import product_router
app.include_router(product_router.router)

# --- Middleware ---
# CORS (Cross-Origin Resource Sharing) - Allow frontend requests
# Configure to only my host!
origins = [
    settings.ORIGIN_HOST,
    "*"
    # Add your deployed frontend URL here
]
# Configure to only my host!
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"], # Allow all methods
    allow_headers=["*"], # Allow all headers
)

# --- Root Endpoint ---
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the Product Service"}


# --- App startup initialization ---
@app.on_event("startup")
def startup_event():
    create_postgres_tables()
    create_qdrant_collection()
