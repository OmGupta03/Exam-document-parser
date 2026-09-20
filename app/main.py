import logging
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.api import api_router
from app.api.v1.endpoints.health import health_check
from app.core.config import settings

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Production-oriented backend service for document intelligence and question extraction. "
        "Processes PDFs and images asynchronously, extracts structured questions with options and answers, "
        "and tracks source traceability and extraction confidence."
    ),
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global generic exception handler - prevents leaking internal exceptions per PRD §9
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled internal exception during request %s: %s", request.url.path, str(exc), exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Please contact support or try again later."}
    )


# Root health endpoint per PRD §9 table: GET /health
app.add_api_route(
    "/health",
    health_check,
    methods=["GET"],
    tags=["Health"],
    summary="Liveness & Readiness Health Check",
    description="Root liveness check verifying PostgreSQL and Redis connections."
)

# Include v1 API routes
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "health": "/health"
    }



