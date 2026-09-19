import asyncio
import redis.asyncio as aioredis
from app.core.config import settings

# Global redis connection pool
redis_pool = aioredis.ConnectionPool.from_url(
    settings.redis_url,
    max_connections=20,
    decode_responses=True
)


def get_redis_client() -> aioredis.Redis:
    """Return an async Redis client instance."""
    return aioredis.Redis(connection_pool=redis_pool)


async def check_redis_connection(timeout_seconds: float = 2.0) -> bool:
    """Check if Redis is reachable and responds to PING within timeout_seconds."""
    client = get_redis_client()
    try:
        response = await asyncio.wait_for(client.ping(), timeout=timeout_seconds)
        return bool(response)
    except Exception:
        return False
    finally:
        await client.aclose()
