# PROMPT: We are in store-intelligence/tests/. Write the full pipeline and schema test suite. Ensure tests/conftest.py defines required fixtures including async_client, db_session, sample_event, sample_events_batch, staff_event, and reentry_sequence.
# CHANGES MADE: Added sample_event, sample_events_batch, staff_event, and reentry_sequence fixtures as requested, added required prompt comment headers, and defined async_client.

import pytest
import asyncio
from typing import AsyncGenerator
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.database import Base, get_db_session

# Use in-memory SQLite for fast testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def event_loop():
    """
    Creates an instance of the default event loop for the test session.
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        # Create all tables in-memory
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a clean database session per test.
    Clears Event and VisitorSession tables before yielding.
    """
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    async with session_factory() as session:
        from sqlalchemy import delete
        from app.models import Event, VisitorSession
        await session.execute(delete(Event))
        await session.execute(delete(VisitorSession))
        await session.commit()
        yield session
        await session.rollback()

@pytest.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTP client configured to inject the test database session.
    """
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    
    async with AsyncClient(
        transport=ASGITransport(app=app), 
        base_url="http://test"
    ) as ac:
        yield ac
        
    app.dependency_overrides.clear()

@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Standard test client for backward compatibility across other tests.
    """
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    
    async with AsyncClient(
        transport=ASGITransport(app=app), 
        base_url="http://testserver"
    ) as ac:
        yield ac
        
    app.dependency_overrides.clear()

@pytest.fixture
def sample_event() -> dict:
    import uuid
    from datetime import datetime, timezone
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_01",
        "visitor_id": "VIS_abc123",
        "event_type": "ENTRY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {}
    }

@pytest.fixture
def sample_events_batch() -> list:
    import uuid
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    visitor_1 = "VIS_111111"
    visitor_2 = "VIS_222222"
    
    return [
        # 2 ENTRY
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_01",
            "visitor_id": visitor_1,
            "event_type": "ENTRY",
            "timestamp": (now - timedelta(minutes=10)).isoformat(),
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.95,
            "metadata": {}
        },
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_01",
            "visitor_id": visitor_2,
            "event_type": "ENTRY",
            "timestamp": (now - timedelta(minutes=9)).isoformat(),
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.90,
            "metadata": {}
        },
        # 2 ZONE_ENTER
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_02",
            "visitor_id": visitor_1,
            "event_type": "ZONE_ENTER",
            "zone_id": "AISLE_01",
            "timestamp": (now - timedelta(minutes=8)).isoformat(),
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.92,
            "metadata": {}
        },
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_02",
            "visitor_id": visitor_2,
            "event_type": "ZONE_ENTER",
            "zone_id": "AISLE_02",
            "timestamp": (now - timedelta(minutes=7)).isoformat(),
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.88,
            "metadata": {}
        },
        # 2 ZONE_DWELL
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_02",
            "visitor_id": visitor_1,
            "event_type": "ZONE_DWELL",
            "zone_id": "AISLE_01",
            "timestamp": (now - timedelta(minutes=6)).isoformat(),
            "dwell_ms": 5000,
            "is_staff": False,
            "confidence": 0.94,
            "metadata": {}
        },
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_02",
            "visitor_id": visitor_2,
            "event_type": "ZONE_DWELL",
            "zone_id": "AISLE_02",
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
            "dwell_ms": 4000,
            "is_staff": False,
            "confidence": 0.91,
            "metadata": {}
        },
        # 1 BILLING_QUEUE_JOIN
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_03",
            "visitor_id": visitor_1,
            "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": (now - timedelta(minutes=4)).isoformat(),
            "dwell_ms": 1000,
            "is_staff": False,
            "confidence": 0.96,
            "metadata": {"queue_depth": 3}
        },
        # 1 BILLING_QUEUE_ABANDON
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_03",
            "visitor_id": visitor_2,
            "event_type": "BILLING_QUEUE_ABANDON",
            "timestamp": (now - timedelta(minutes=3)).isoformat(),
            "dwell_ms": 8000,
            "is_staff": False,
            "confidence": 0.89,
            "metadata": {}
        },
        # 2 EXIT
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_04",
            "visitor_id": visitor_1,
            "event_type": "EXIT",
            "timestamp": (now - timedelta(minutes=2)).isoformat(),
            "dwell_ms": 600000,
            "is_staff": False,
            "confidence": 0.97,
            "metadata": {}
        },
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_04",
            "visitor_id": visitor_2,
            "event_type": "EXIT",
            "timestamp": (now - timedelta(minutes=1)).isoformat(),
            "dwell_ms": 480000,
            "is_staff": False,
            "confidence": 0.93,
            "metadata": {}
        }
    ]

@pytest.fixture
def staff_event() -> dict:
    import uuid
    from datetime import datetime, timezone
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_01",
        "visitor_id": "VIS_abc123",
        "event_type": "ENTRY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dwell_ms": 0,
        "is_staff": True,
        "confidence": 0.95,
        "metadata": {}
    }

@pytest.fixture
def reentry_sequence() -> list:
    import uuid
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    visitor_id = "VIS_def456"
    return [
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_01",
            "visitor_id": visitor_id,
            "event_type": "ENTRY",
            "timestamp": (now - timedelta(minutes=10)).isoformat(),
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.90,
            "metadata": {}
        },
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_04",
            "visitor_id": visitor_id,
            "event_type": "EXIT",
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
            "dwell_ms": 300000,
            "is_staff": False,
            "confidence": 0.92,
            "metadata": {}
        },
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_01",
            "visitor_id": visitor_id,
            "event_type": "REENTRY",
            "timestamp": (now - timedelta(minutes=1)).isoformat(),
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.91,
            "metadata": {}
        }
    ]
