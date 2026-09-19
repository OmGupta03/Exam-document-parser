import asyncio
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import check_db_connection
from app.core.redis import check_redis_connection
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={
        200: {"description": "All backend dependencies are healthy and reachable."},
        503: {"description": "One or more backend dependencies (PostgreSQL or Redis) are unavailable."},
    },
    summary="Service Health and Dependency Check",
    description="Checks the liveness and readiness of the API and its dependent services (PostgreSQL and Redis). Returns 503 if any dependency is degraded."
)
async def health_check():
    """Verify API, PostgreSQL database, and Redis connectivity."""
    db_ok, redis_ok = await asyncio.gather(
        check_db_connection(timeout_seconds=2.0),
        check_redis_connection(timeout_seconds=2.0),
        return_exceptions=True
    )

    db_connected = db_ok is True
    redis_connected = redis_ok is True

    db_status = "connected" if db_connected else "disconnected"
    redis_status = "connected" if redis_connected else "disconnected"

    is_healthy = db_connected and redis_connected
    overall_status = "healthy" if is_healthy else "unhealthy"

    payload = {
        "status": overall_status,
        "database": db_status,
        "redis": redis_status,
        "version": settings.VERSION
    }

    if not is_healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=payload
    )
