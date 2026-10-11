import os
os.environ["DATABASE_URL"] = "sqlite:///./test_resolveai.db"
os.environ["JWT_SECRET"] = "tests-only-secret-not-for-real-use"
os.environ["DEMO_MODE"] = "true"

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core import Base, engine


@pytest.fixture
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def auth(client):
    response = client.post("/api/auth/register", json={"name": "Test Admin", "email": "admin@example.com", "password": "strong-test-password"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}
