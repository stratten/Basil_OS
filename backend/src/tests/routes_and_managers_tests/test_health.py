"""Tests for health check endpoint."""

import pytest
from fastapi.testclient import TestClient

from api.settings import Settings, get_settings
from api.main import app

@pytest.fixture
def test_client():
    """Create a test client."""
    return TestClient(app)

@pytest.mark.asyncio
async def test_health_check(test_client):
    """Test health check endpoint."""
    response = test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data

def test_health_check_content_type(test_client: TestClient):
    """Test the health check endpoint returns JSON content type."""
    response = test_client.get("/health")
    assert response.headers["content-type"] == "application/json" 