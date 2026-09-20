from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    document_groups,
    documents,
    health,
    questions,
    warnings,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])
api_router.include_router(questions.router, tags=["Questions"])
api_router.include_router(warnings.router, tags=["Warnings"])
api_router.include_router(document_groups.router, prefix="/document-groups", tags=["Document Groups"])
