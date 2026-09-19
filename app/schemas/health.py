from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(..., description="Overall health status: 'healthy' or 'unhealthy'")
    database: str = Field(..., description="PostgreSQL connection status: 'connected' or 'disconnected'")
    redis: str = Field(..., description="Redis connection status: 'connected' or 'disconnected'")
    version: str = Field(..., description="Service version")
