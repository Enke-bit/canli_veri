"""Hedef API testleri (gercek MSSQL test veritabani).

Sabit JSON dondurulmedigini kanitlamak icin once veritabani doldurulur,
sonra API'nin bu satirlari okudugu dogrulanir.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main_module
from app.db import get_db
from app.models import Appointment, Clinic, Patient, SyncLog, SyncState


@pytest.fixture()
def seeded_db(clean_db):
    now = datetime(2026, 5, 1, 9, 0, 0)
    with Session(clean_db) as session:
        with session.begin():
            session.add_all(
                [
                    Clinic(
                        external_clinic_id="CLN-0001",
                        name="Demo Klinik Merkez",
                        created_at=now,
                        updated_at=now,
                        is_deleted=False,
                    ),
                    Clinic(
                        external_clinic_id="CLN-0002",
                        name="Demo Klinik Kuzey",
                        created_at=now,
                        updated_at=now,
                        is_deleted=True,
                    ),
                ]
            )
            session.flush()
            session.flush()
            session.add_all(
                [
                    Patient(
                        external_patient_id="PAT-000001",
                        external_clinic_id="CLN-0001",
                        first_name="Test",
                        last_name="Hasta",
                        email="patient000001@example.test",
                        phone="TEST_PHONE_000001",
                        created_at=now,
                        updated_at=now,
                        is_deleted=False,
                    ),
                    Patient(
                        external_patient_id="PAT-000002",
                        external_clinic_id="CLN-0001",
                        first_name="Silinmis",
                        last_name="Hasta",
                        email="patient000002@example.test",
                        phone="TEST_PHONE_000002",
                        created_at=now,
                        updated_at=now,
                        is_deleted=True,
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    Appointment(
                        external_appointment_id="APT-000001",
                        external_patient_id="PAT-000001",
                        external_clinic_id="CLN-0001",
                        appointment_datetime=now + timedelta(days=1),
                        end_datetime=now + timedelta(days=1, minutes=30),
                        procedure_type="Kontrol",
                        status="Scheduled",
                        created_at=now,
                        updated_at=now,
                        is_deleted=False,
                    ),
                    Appointment(
                        external_appointment_id="APT-000002",
                        external_patient_id="PAT-000001",
                        external_clinic_id="CLN-0001",
                        appointment_datetime=now - timedelta(days=1),
                        end_datetime=now - timedelta(days=1) + timedelta(minutes=45),
                        procedure_type="Dolgu",
                        status="Completed",
                        created_at=now,
                        updated_at=now,
                        is_deleted=False,
                    ),
                ]
            )
            session.add(
                SyncState(
                    entity_type="appointments",
                    last_synced_at=now,
                    last_successful_run_at=now,
                    updated_at=now,
                )
            )
    yield clean_db


@pytest.fixture()
def api(seeded_db):
    def override_get_db():
        with Session(seeded_db) as session:
            yield session

    main_module.app.dependency_overrides[get_db] = override_get_db
    monkeypatch_target = main_module.get_engine
    main_module.get_engine = lambda: seeded_db
    with TestClient(main_module.app) as client:
        yield client
    main_module.app.dependency_overrides.clear()
    main_module.get_engine = monkeypatch_target


def test_health_reports_real_database(api):
    response = api.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"]["status"] == "ok"
    assert body["database"]["name"].endswith("Test")


def test_clinics_are_read_from_database(api):
    response = api.get("/api/v1/clinics")
    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["total"] == 1
    assert body["data"][0]["external_clinic_id"] == "CLN-0001"
    assert body["data"][0]["updated_at"].endswith("Z")

    with_deleted = api.get("/api/v1/clinics", params={"include_deleted": True})
    assert with_deleted.json()["pagination"]["total"] == 2


def test_patients_are_read_from_database_and_paginated(api):
    response = api.get("/api/v1/patients", params={"limit": 1, "offset": 0})
    body = response.json()
    assert body["pagination"]["total"] == 1
    assert body["pagination"]["has_more"] is False
    assert body["data"][0]["phone"] == "TEST_PHONE_000001"


def test_appointments_filter_by_status(api):
    response = api.get("/api/v1/appointments", params={"status": "Completed"})
    body = response.json()
    assert body["pagination"]["total"] == 1
    assert body["data"][0]["external_appointment_id"] == "APT-000002"


def test_appointments_filter_by_date_range(api):
    response = api.get(
        "/api/v1/appointments",
        params={
            "date_from": "2026-05-02T00:00:00Z",
            "date_to": "2026-05-03T00:00:00Z",
        },
    )
    body = response.json()
    assert body["pagination"]["total"] == 1
    assert body["data"][0]["external_appointment_id"] == "APT-000001"


def test_invalid_status_filter_returns_422(api):
    response = api.get("/api/v1/appointments", params={"status": "Bogus"})
    assert response.status_code == 422


def test_get_single_appointment(api):
    response = api.get("/api/v1/appointments/APT-000001")
    assert response.status_code == 200
    assert response.json()["status"] == "Scheduled"


def test_get_missing_appointment_returns_404(api):
    response = api.get("/api/v1/appointments/APT-NOPE")
    assert response.status_code == 404


def test_status_update_persists_and_logs(api, seeded_db):
    response = api.patch(
        "/api/v1/appointments/APT-000001/status", json={"status": "Confirmed"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "Confirmed"

    with Session(seeded_db) as session:
        row = session.execute(
            select(Appointment).where(
                Appointment.external_appointment_id == "APT-000001"
            )
        ).scalar_one()
        assert row.status == "Confirmed"
        log = session.execute(
            select(SyncLog).where(SyncLog.operation_type == "api_status_update")
        ).scalar_one()
        assert "Scheduled -> Confirmed" in log.error_summary


def test_status_update_rejects_invalid_value(api):
    response = api.patch(
        "/api/v1/appointments/APT-000001/status", json={"status": "Unknown"}
    )
    assert response.status_code == 422


def test_status_update_missing_record_returns_404(api):
    response = api.patch(
        "/api/v1/appointments/APT-NOPE/status", json={"status": "Confirmed"}
    )
    assert response.status_code == 404


def test_sync_status_and_logs_endpoints(api):
    status_response = api.get("/api/v1/sync/status")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["states"][0]["entity_type"] == "appointments"
    assert body["states"][0]["last_successful_run_at"].endswith("Z")

    logs_response = api.get("/api/v1/sync/logs")
    assert logs_response.status_code == 200
    assert logs_response.json()["pagination"]["total"] == 0


# --------------------------------------------------------------- analytics
def test_analytics_summary_uses_database(api, seeded_db):
    response = api.get("/api/v1/analytics/summary", params={"months": 6})
    assert response.status_code == 200
    body = response.json()

    # 2 klinikten 1'i silinmis, 2 hastadan 1'i silinmis.
    assert body["totals"]["clinics"] == 1
    assert body["totals"]["patients"] == 1
    assert body["totals"]["appointments"] == 2
    assert body["totals"]["deleted_appointments"] == 0

    counts = body["appointment_status_counts"]
    assert counts == {
        "Scheduled": 1,
        "Confirmed": 0,
        "Completed": 1,
        "Cancelled": 0,
    }

    # Klinik hacmi gercek sayilardan gelir.
    assert body["clinic_volumes"][0]["clinic_id"] == "CLN-0001"
    assert body["clinic_volumes"][0]["patients"] == 1
    assert body["clinic_volumes"][0]["appointments"] == 2

    # Trend: istenen ay sayisi kadar nokta, toplam hasta sayisi ile tutarli.
    trend = body["patient_registrations"]
    assert len(trend) == 6
    assert sum(row["count"] for row in trend) == 1

    # Henuz SyncLog yok: oran None doner, sifir bolme hatasi olmaz.
    assert body["sync"]["total_runs"] == 0
    assert body["sync"]["success_rate"] is None


def test_analytics_reports_sync_logs(api, seeded_db):
    from datetime import datetime

    with Session(seeded_db) as session:
        with session.begin():
            now = datetime(2026, 5, 1, 10, 0, 0)
            session.add_all(
                [
                    SyncLog(
                        job_id="11111111-1111-1111-1111-111111111111",
                        entity_type="appointments",
                        operation_type="sync",
                        started_at=now,
                        finished_at=now,
                        status="Success",
                        records_read=10,
                        records_inserted=10,
                    ),
                    SyncLog(
                        job_id="22222222-2222-2222-2222-222222222222",
                        entity_type="appointments",
                        operation_type="sync",
                        started_at=now,
                        finished_at=now,
                        status="Failed",
                        error_count=1,
                        error_summary="gecici hata",
                    ),
                ]
            )

    body = api.get("/api/v1/analytics/summary").json()
    sync = body["sync"]
    assert sync["total_runs"] == 2
    assert sync["success_runs"] == 1
    assert sync["failed_runs"] == 1
    assert sync["success_rate"] == 50.0
    assert len(sync["recent_logs"]) == 2


def test_analytics_months_validation(api):
    assert api.get("/api/v1/analytics/summary", params={"months": 0}).status_code == 422
    assert api.get("/api/v1/analytics/summary", params={"months": 99}).status_code == 422


# --------------------------------------------------------------- dashboard
def test_dashboard_is_served(api):
    response = api.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "MedicalPoint" in body
    assert "analytics/summary" in body
    # Harici CDN bagimliligi olmamali.
    assert "cdn." not in body
    assert "cdnjs" not in body


def test_guide_page_is_served(api):
    response = api.get("/kilavuz")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Sıfırdan Çalıştırma Kılavuzu" in body
    assert "init_db.py" in body
    assert "run_source_api.ps1" in body
    assert "register_sync_task.ps1" in body
    # Kurulum sayfasi da harici kaynak kullanmamali.
    assert "cdn." not in body
    assert "cdnjs" not in body


def test_architecture_page_is_served(api):
    response = api.get("/mimari")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Mimari ve Canlı Veri Akışı" in body
    # Gorsel semalar satir ici SVG olmali.
    assert body.count("<svg") >= 5
    assert "updated_since" in body
    assert "SyncState" in body
    assert "cdn." not in body


def test_slides_page_is_served(api):
    response = api.get("/slayt")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Canlı Veri Çekme" in body
    # 14 slayt ve gezinme mantigi bulunmali.
    assert body.count('class="slide') >= 14
    assert "ArrowRight" in body
    assert "upsert" in body.lower()
    assert "checkpoint" in body.lower()
    assert "cdn." not in body
    assert "cdnjs" not in body


def test_sync_slides_page_is_served(api):
    """Basit anlatim sunumu: 4 kural ve 11 slayt."""
    response = api.get("/slayt-senkron")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Canlı veri" in body
    assert body.count('class="slide') >= 11
    # Dort kural ve temel kavramlar anlatilmali.
    for phrase in ("Sadece değişeni", "Defter", "geriden", "Varsa güncelle"):
        assert phrase in body, f"eksik: {phrase}"
    # Sade anlatim: kod orani dusuk, jargon aciklanmis.
    assert "updated_since" in body
    assert "SyncState" in body
    # Harici kaynak yok.
    assert "cdn." not in body
    assert "cdnjs" not in body


def test_all_static_pages_have_no_external_resources(api):
    for path in ("/dashboard", "/kilavuz", "/mimari", "/slayt", "/slayt-senkron"):
        body = api.get(path).text
        for marker in ("http://cdn", "https://cdn", "cdnjs", "unpkg.com"):
            assert marker not in body, f"{path} harici kaynak kullaniyor: {marker}"


def test_pages_link_to_each_other(api):
    """Panelden diger sayfalara gezinme baglantilari kopmamali."""
    dashboard = api.get("/dashboard").text
    for path in ("/kilavuz", "/mimari", "/slayt"):
        assert f'href="{path}"' in dashboard
    for page in (api.get("/kilavuz").text, api.get("/mimari").text):
        assert 'href="/slayt"' in page


def test_root_lists_documentation_pages(api):
    body = api.get("/").json()
    assert body["guide"] == "/kilavuz"
    assert body["architecture"] == "/mimari"
    assert body["dashboard"] == "/dashboard"
    assert body["slides"] == "/slayt"


def test_cors_allows_local_dashboard_origin(api):
    response = api.get(
        "/health", headers={"Origin": "http://127.0.0.1:8001"}
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:8001"


# --------------------------------------------------------------- sync trigger
def test_sync_trigger_disabled_by_default(api, monkeypatch, settings):
    from dataclasses import replace

    import app.routers.sync as sync_router

    monkeypatch.setattr(
        sync_router, "get_settings", lambda: replace(settings, enable_sync_trigger=False)
    )
    response = api.post("/api/v1/sync/run")
    assert response.status_code == 403
    assert "ENABLE_SYNC_TRIGGER" in response.json()["detail"]


def test_sync_trigger_rejects_unknown_entity(api, monkeypatch, settings):
    from dataclasses import replace

    import app.routers.sync as sync_router

    monkeypatch.setattr(
        sync_router, "get_settings", lambda: replace(settings, enable_sync_trigger=True)
    )
    response = api.post("/api/v1/sync/run", params={"entities": "patients,bogus"})
    assert response.status_code == 422
    assert "bogus" in response.json()["detail"]
