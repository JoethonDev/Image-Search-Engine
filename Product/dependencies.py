from fastapi import Depends, Header, HTTPException, status
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import httpx
from qdrant_client import QdrantClient

import service, config
from models import Merchant


DATABASE_URL = "postgresql://avnadmin:AVNS_pJ81YzNkQZ50I53daVx@image-search-image-search-engine.h.aivencloud.com:28638/image-search"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
USER_HEADER = "X-USER-ID"

# Dependency to get a database session
async def get_http_client() -> httpx.AsyncClient:
    async with httpx.AsyncClient(timeout=30.0) as client: # Adjust timeout
        yield client

async def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_qdrant():
    client = QdrantClient(
        url=config.settings.QDRANT_ENDPOINT,
        api_key=config.settings.QDRANT_KEY,
    )
    return client


async def get_product_service(db: Session = Depends(get_db), client: httpx.AsyncClient = Depends(get_http_client), qdrant: QdrantClient = Depends(get_qdrant)):
    return service.ProductService(db, client, qdrant)


async def resolve_merchant_id(
    # Attempt to get merchant_id from the URL path.
    # It's Optional because the '/' route doesn't have it in the path.
    merchant_id: Optional[int],
    # Attempt to get merchant_id from the X-User-ID header.
    # It's Optional because the '/{merchant_id}/products' route might not explicitly rely on it.
    merchant_id_from_header: Optional[int] = Header(
        None, # Default to None if header is not provided
        alias=USER_HEADER,
        description="The ID of the authenticated merchant from the X-User-ID header"
    )
) -> Merchant:
    """
    Resolves the merchant_id for the request.
    Prioritizes the merchant_id from the URL path.
    If not found in the path, falls back to the X-User-ID header.
    If neither is provided, raises an HTTPException.
    """
    if merchant_id is not None:
        return Merchant(merchant_id=merchant_id, is_owner=False)
    elif merchant_id_from_header is not None:
        return Merchant(merchant_id=merchant_id_from_header, is_owner=True)
    else:
        # This case should only be hit if neither the path nor the header provides the ID
        # and it's mandatory for this operation.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Merchant ID is required. Provide it in the URL path (e.g., /{{merchant_id}}/products) or via the '{USER_HEADER}' header."
        )