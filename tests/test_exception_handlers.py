# PROMPT: We are in store-intelligence/tests/. Write tests for FastAPI exception handlers covering 422 validation errors and 500 global exception catches.
# CHANGES MADE: Created test_exception_handlers.py with RequestValidationError (422) and global Exception handler (500) endpoint test assertions.
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch
from app.main import app

@pytest.mark.asyncio
async def test_request_validation_error_handler():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Send a malformed payload (missing events key entirely)
        response = await client.post("/events/ingest", json={})
        assert response.status_code == 422
        data = response.json()
        assert data["error"] == "validation_error"
        assert "details" in data

@pytest.mark.asyncio
async def test_global_exception_handler():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Trigger an unexpected error in get_heatmap to trigger global 500 handler
        with patch("app.routers.stores.get_heatmap", side_effect=Exception("Unexpected database glitch")):
            response = await client.get("/stores/STORE_BLR_002/heatmap")
            assert response.status_code == 500
            data = response.json()
            assert data["error"] == "internal_error"
            assert data["message"] == "An unexpected error occurred."
            assert "trace_id" in data

@pytest.mark.asyncio
async def test_database_unavailable_exception_handler():
    from sqlalchemy.exc import OperationalError
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Trigger SQLAlchemy OperationalError to trigger 503 handler
        with patch("app.routers.stores.get_heatmap", side_effect=OperationalError("select 1", {}, Exception("Connection refused"))):
            response = await client.get("/stores/STORE_BLR_002/heatmap")
            assert response.status_code == 503
            data = response.json()
            assert data["error"] == "database_unavailable"
            assert "database is currently unavailable" in data["message"]
