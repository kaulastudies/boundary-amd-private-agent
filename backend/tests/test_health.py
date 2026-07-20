from fastapi.testclient import TestClient

from boundary_backend.main import app


def test_health_endpoint_reports_local_only_status() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "backend",
        "model": "not-configured",
        "remote_apis_enabled": False,
    }
