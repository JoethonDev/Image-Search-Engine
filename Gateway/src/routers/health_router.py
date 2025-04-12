from fastapi import APIRouter
from ..models import HealthStatus

router = APIRouter()

@router.get("/health", response_model=HealthStatus, tags=["Health"])
async def health_check():
    """Check the health of the API Gateway."""
    return {"status": "ok"}