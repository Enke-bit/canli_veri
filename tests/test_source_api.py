"""Mock kaynak API testleri (TestClient, ag yok)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from mock_source.main import app
from scripts.generate_synthetic_data import generate_dataset, write_dataset

FIXED_NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture()
def client(source_data_file):
    data = generate_dataset(clinics=3, patients=40, appointments=200, seed=21)
    write_dataset(data, output=source_data_file, force=True)
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_data(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["counts"] == {"clinics": 3, "patients": 40, "appointments": 200}


def test_stats_matches_data(client):
    response = client.get("/source/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["clinics"] == 3
    assert sum(body["appointment_status_counts"].values()) == 200


def test_missing_data_file_returns_clear_error(source_data_file):
    with TestClient(app) as test_client:
        response = test_client.get("/health")
        assert response.json()["status"] == "degraded"
        response = test_client.get("/source/appointments")
        assert response.status_code == 503
        assert "generate_synthetic_data.py" in response.json()["detail"]


def test_appointment_json_shape(client):
    response = client.get("/source/appointments", params={"limit": 1})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "pagination"}
    appointment = body["data"][0]
    for field in (
        "external_appointment_id",
        "external_patient_id",
        "external_clinic_id",
        "appointment_datetime",
        "end_datetime",
        "procedure_type",
        "status",
        "created_at",
        "updated_at",
        "is_deleted",
    ):
        assert field in appointment
    assert appointment["appointment_datetime"].endswith("Z")


def test_pagination_has_no_gaps_or_duplicates(client):
    collected: list[str] = []
    offset = 0
    page_size = 37
    while True:
        response = client.get(
            "/source/appointments", params={"limit": page_size, "offset": offset}
        )
        assert response.status_code == 200
        body = response.json()
        collected.extend(item["external_appointment_id"] for item in body["data"])
        pagination = body["pagination"]
        assert pagination["total"] == 200
        if not pagination["has_more"]:
            break
        assert pagination["next_offset"] == offset + page_size
        offset = pagination["next_offset"]
    assert len(collected) == 200
    assert len(set(collected)) == 200


def test_pagination_ordering_is_deterministic(client):
    first = client.get("/source/appointments", params={"limit": 50, "offset": 0}).json()
    second = client.get("/source/appointments", params={"limit": 50, "offset": 0}).json()
    assert first == second


def test_invalid_pagination_rejected(client):
    assert client.get("/source/appointments", params={"limit": 0}).status_code == 422
    assert client.get("/source/appointments", params={"offset": -1}).status_code == 422
    assert client.get("/source/appointments", params={"limit": 9999}).status_code == 422


def test_updated_since_filter(client):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    response = client.get(
        "/source/appointments", params={"updated_since": future, "limit": 10}
    )
    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["pagination"]["total"] == 0


def test_create_appointment(client):
    patient = client.get("/source/patients", params={"limit": 1}).json()["data"][0]
    payload = {
        "external_patient_id": patient["external_patient_id"],
        "external_clinic_id": patient["external_clinic_id"],
        "appointment_datetime": "2027-01-15T10:00:00Z",
        "end_datetime": "2027-01-15T10:30:00Z",
        "procedure_type": "Kontrol",
        "status": "Scheduled",
    }
    response = client.post("/source/appointments", json=payload)
    assert response.status_code == 201
    created = response.json()["data"][0]
    assert created["external_appointment_id"].startswith("APT-LOCAL-")

    fetched = client.get(f"/source/appointments/{created['external_appointment_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["procedure_type"] == "Kontrol"


def test_create_rejects_unknown_patient(client):
    payload = {
        "external_patient_id": "PAT-MISSING",
        "external_clinic_id": "CLN-0001",
        "appointment_datetime": "2027-01-15T10:00:00Z",
        "end_datetime": "2027-01-15T10:30:00Z",
        "procedure_type": "Kontrol",
    }
    assert client.post("/source/appointments", json=payload).status_code == 404


def test_create_rejects_end_before_start(client):
    patient = client.get("/source/patients", params={"limit": 1}).json()["data"][0]
    payload = {
        "external_patient_id": patient["external_patient_id"],
        "external_clinic_id": patient["external_clinic_id"],
        "appointment_datetime": "2027-01-15T10:30:00Z",
        "end_datetime": "2027-01-15T10:00:00Z",
        "procedure_type": "Kontrol",
    }
    assert client.post("/source/appointments", json=payload).status_code == 422


def test_patch_appointment_updates_and_touches_timestamp(client):
    appointment = client.get("/source/appointments", params={"limit": 1}).json()["data"][0]
    external_id = appointment["external_appointment_id"]
    response = client.patch(
        f"/source/appointments/{external_id}", json={"procedure_type": "Dolgu"}
    )
    assert response.status_code == 200
    updated = response.json()["data"][0]
    assert updated["procedure_type"] == "Dolgu"
    assert updated["updated_at"] >= appointment["updated_at"]


def test_patch_unknown_appointment_returns_404(client):
    assert client.patch("/source/appointments/APT-NOPE", json={"status": "Cancelled"}).status_code == 404


def test_patch_without_fields_returns_400(client):
    appointment = client.get("/source/appointments", params={"limit": 1}).json()["data"][0]
    response = client.patch(
        f"/source/appointments/{appointment['external_appointment_id']}", json={}
    )
    assert response.status_code == 400


def test_patch_invalid_status_returns_422(client):
    appointment = client.get("/source/appointments", params={"limit": 1}).json()["data"][0]
    response = client.patch(
        f"/source/appointments/{appointment['external_appointment_id']}",
        json={"status": "Teleported"},
    )
    assert response.status_code == 422


def test_cancel_appointment(client):
    appointment = client.get("/source/appointments", params={"limit": 1}).json()["data"][0]
    external_id = appointment["external_appointment_id"]
    response = client.post(f"/source/appointments/{external_id}/cancel")
    assert response.status_code == 200
    assert response.json()["data"][0]["status"] == "Cancelled"


def test_delete_is_soft_and_visible_with_include_deleted(client):
    appointment = client.get("/source/appointments", params={"limit": 1}).json()["data"][0]
    external_id = appointment["external_appointment_id"]
    assert client.delete(f"/source/appointments/{external_id}").status_code == 204

    hidden = client.get("/source/appointments", params={"limit": 200, "include_deleted": False})
    assert external_id not in {a["external_appointment_id"] for a in hidden.json()["data"]}

    visible = client.get(f"/source/appointments/{external_id}")
    assert visible.status_code == 200
    assert visible.json()["data"]["is_deleted"] is True


def test_deleted_appointment_cannot_be_patched(client):
    appointment = client.get("/source/appointments", params={"limit": 1}).json()["data"][0]
    external_id = appointment["external_appointment_id"]
    client.delete(f"/source/appointments/{external_id}")
    response = client.patch(
        f"/source/appointments/{external_id}", json={"status": "Confirmed"}
    )
    assert response.status_code == 409
