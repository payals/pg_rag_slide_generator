"""
Database connection pool manager for MCP Server.

Provides async connection pool with context managers for transactions
and connections. Uses asyncpg for high-performance async Postgres access.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import asyncpg
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL")

# Connection pool singleton
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """
    Get or create the database connection pool.
    
    Returns:
        asyncpg.Pool: The connection pool
        
    Raises:
        ValueError: If DATABASE_URL is not configured
    """
    global _pool
    
    if _pool is None:
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable not set")
        
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
    
    return _pool


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Get a connection from the pool.
    
    Usage:
        async with get_connection() as conn:
            result = await conn.fetch("SELECT * FROM table")
    
    Yields:
        asyncpg.Connection: A database connection
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Get a connection with an active transaction.
    
    Transaction is committed on successful exit, rolled back on exception.
    
    Usage:
        async with transaction() as conn:
            await conn.execute("INSERT INTO ...")
            await conn.execute("UPDATE ...")
    
    Yields:
        asyncpg.Connection: A database connection with active transaction
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn


async def init_pool(database_url: Optional[str] = None) -> asyncpg.Pool:
    """
    Initialize the connection pool with a specific URL.
    
    Idempotent: returns the existing pool if already initialized
    (prevents double-init when FastMCP Client triggers server lifespan).
    
    Args:
        database_url: Optional override for DATABASE_URL
    
    Returns:
        asyncpg.Pool: The connection pool
    """
    global _pool, DATABASE_URL
    
    if _pool is not None:
        return _pool
    
    if database_url:
        DATABASE_URL = database_url
    
    return await get_pool()
