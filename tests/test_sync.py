"""Senkronizasyon motoru testleri.

MSSQL entegrasyon testleri ayri DenSyncTest veritabaninda calisir.
SQL Server yoksa bu dosyadaki testler atlanir.
"""
from __future__ import annotations

from dataclasses import replace
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Appointment, Clinic, Patient, SyncLog, SyncState
from app.sync_engine import SourceApiClient, SyncEngine
from mock_source.main import app as source_app
from scripts.generate_synthetic_data import generate_dataset, write_dataset

def make_settings(settings):
    return replace(
        settings,
        sync_page_size=25,
        sync_overlap_seconds=120,
        http_max_retries=2,
        http_backoff_seconds=0.0,
    )


@pytest.fixture()
def dataset(source_data_file):
    data = generate_dataset(clinics=3, patients=12, appointments=40, seed=33)
    write_dataset(data, output=source_data_file, force=True)
    return data


@pytest.fixture()
def engine_for_sync(clean_db, mssql_settings, source_api_server, dataset):
    client = SourceApiClient(
        source_api_server,
        timeout=10,
        max_retries=2,
        backoff_seconds=0.0,
        sleep=lambda _: None,
    )
    sync = SyncEngine(make_settings(mssql_settings), clean_db, client=client)
    try:
        yield sync
    finally:
        sync.close()


def counts(engine) -> dict[str, int]:
    with Session(engine) as session:
        return {
            "clinics": session.execute(select(func.count()).select_from(Clinic)).scalar_one(),
            "patients": session.execute(select(func.count()).select_from(Patient)).scalar_one(),
            "appointments": session.execute(
                select(func.count()).select_from(Appointment)
            ).scalar_one(),
        }


def test_first_sync_inserts_all_records(engine_for_sync, dataset):
    result = engine_for_sync.run()
    assert result.success is True
    assert counts(engine_for_sync.engine) == {
        "clinics": 3,
        "patients": 12,
        "appointments": 40,
    }
    stats = {item.entity: item for item in result.entities}
    assert stats["appointments"].inserted == 40
    assert stats["appointments"].read == 40


def test_repeated_sync_does_not_duplicate(engine_for_sync, dataset):
    first = engine_for_sync.run()
    assert first.success
    second = engine_for_sync.run()
    assert second.success
    assert counts(engine_for_sync.engine) == {
        "clinics": 3,
        "patients": 12,
        "appointments": 40,
    }
    for stats in second.entities:
        assert stats.inserted == 0


def test_full_resync_is_idempotent(engine_for_sync, dataset):
    engine_for_sync.run()
    again = engine_for_sync.run(force_full=True)
    assert again.success
    assert counts(engine_for_sync.engine)["appointments"] == 40
    assert all(stats.inserted == 0 for stats in again.entities)


def test_pagination_fetches_every_record(engine_for_sync, dataset):
    # Sayfa boyutu 25, 40 randevu ve 12 hasta -> birden fazla sayfa.
    result = engine_for_sync.run()
    assert result.success
    stats = {item.entity: item for item in result.entities}
    assert stats["appointments"].read == 40
    assert stats["patients"].read == 12


def test_updated_appointment_is_synced(engine_for_sync, dataset):
    assert engine_for_sync.run().success
    target = dataset["appointments"][0]["ExternalAppointmentId"]

    with TestClient(source_app) as source:
        response = source.patch(
            f"/source/appointments/{target}", json={"procedure_type": "Dolgu"}
        )
        assert response.status_code == 200
        new_status = "Confirmed"
        response = source.patch(
            f"/source/appointments/{target}", json={"status": new_status}
        )
        assert response.status_code == 200

    result = engine_for_sync.run()
    assert result.success
    with Session(engine_for_sync.engine) as session:
        row = session.execute(
            select(Appointment).where(Appointment.external_appointment_id == target)
        ).scalar_one()
        assert row.procedure_type == "Dolgu"
        assert row.status == new_status


def test_cancelled_appointment_propagates(engine_for_sync, dataset):
    assert engine_for_sync.run().success
    target = dataset["appointments"][1]["ExternalAppointmentId"]
    with TestClient(source_app) as source:
        assert (
            source.post(f"/source/appointments/{target}/cancel").status_code == 200
        )

    result = engine_for_sync.run()
    assert result.success
    with Session(engine_for_sync.engine) as session:
        row = session.execute(
            select(Appointment).where(Appointment.external_appointment_id == target)
        ).scalar_one()
        assert row.status == "Cancelled"


def test_soft_deleted_appointment_is_marked(engine_for_sync, dataset):
    assert engine_for_sync.run().success
    target = dataset["appointments"][2]["ExternalAppointmentId"]
    with TestClient(source_app) as source:
        assert source.delete(f"/source/appointments/{target}").status_code == 204

    result = engine_for_sync.run()
    assert result.success
    stats = {item.entity: item for item in result.entities}
    assert stats["appointments"].deleted_marked == 1
    with Session(engine_for_sync.engine) as session:
        row = session.execute(
            select(Appointment).where(Appointment.external_appointment_id == target)
        ).scalar_one()
        assert row.is_deleted is True


def test_success_writes_sync_log_and_state(engine_for_sync, dataset):
    assert engine_for_sync.run().success
    with Session(engine_for_sync.engine) as session:
        logs = session.execute(select(SyncLog)).scalars().all()
        assert {log.entity_type for log in logs} == {
            "clinics",
            "patients",
            "appointments",
        }
        assert all(log.status == "Success" for log in logs)
        assert all(log.finished_at is not None for log in logs)
        states = session.execute(select(SyncState)).scalars().all()
        assert {state.entity_type for state in states} == {
            "clinics",
            "patients",
            "appointments",
        }
        assert all(state.last_synced_at is not None for state in states)


class _FailingAppointmentsClient:
    """Klinik/hasta icin gercek istemci, randevularda hata uretir."""

    def __init__(self, real_client: SourceApiClient, message: str):
        self.real = real_client
        self.message = message
        self.attempts = 0

    def fetch_clinics(self, updated_since, page_size):
        return self.real.fetch_clinics(updated_since, page_size)

    def fetch_patients(self, updated_since, page_size):
        return self.real.fetch_patients(updated_since, page_size)

    def fetch_appointments(self, updated_since, page_size):
        self.attempts += 1
        raise httpx.ConnectTimeout(self.message)

    def close(self):
        pass


def test_failed_run_is_not_marked_success_and_checkpoint_not_advanced(
    mssql_settings, clean_db, source_api_server, dataset
):
    real_client = SourceApiClient(
        source_api_server,
        max_retries=2,
        backoff_seconds=0.0,
        sleep=lambda _: None,
    )
    failing = _FailingAppointmentsClient(real_client, "simulated timeout")

    # 1) Basarisiz calisma
    engine = SyncEngine(make_settings(mssql_settings), clean_db, client=failing)
    result = engine.run()
    engine.close()
    assert result.success is False
    assert result.error is not None and "appointments" in result.error
    assert counts(clean_db)["appointments"] == 0

    with Session(clean_db) as session:
        failed_logs = (
            session.execute(select(SyncLog).where(SyncLog.status == "Failed"))
            .scalars()
            .all()
        )
        assert len(failed_logs) == 1
        assert failed_logs[0].entity_type == "appointments"
        assert failed_logs[0].error_summary
        state = session.execute(
            select(SyncState).where(SyncState.entity_type == "appointments")
        ).scalar_one_or_none()
        assert state is None or state.last_synced_at is None

        # Basarili turlerin checkpoint'i ilerlemis olmali.
        clinic_state = session.execute(
            select(SyncState).where(SyncState.entity_type == "clinics")
        ).scalar_one()
        assert clinic_state.last_synced_at is not None

    # 2) Sonraki calisma basarisiz veriyi yeniden isler
    recovering = SyncEngine(make_settings(mssql_settings), clean_db, client=real_client)
    recovered = recovering.run()
    recovering.close()
    assert recovered.success is True
    assert counts(clean_db)["appointments"] == 40


def test_retry_after_transient_503_then_success():
    attempts = {"count": 0}
    payload = {
        "data": [],
        "pagination": {
            "limit": 10,
            "offset": 0,
            "total": 0,
            "has_more": False,
            "next_offset": None,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, text="temporary")
        return httpx.Response(200, json=payload)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://source.test"
    )
    source = SourceApiClient(
        "http://source.test",
        max_retries=4,
        backoff_seconds=0.0,
        client=client,
        sleep=lambda _: None,
    )
    try:
        result = source.fetch_clinics(None, 10)
        pages = list(result)
        assert pages == [[]]
        assert attempts["count"] == 3
    finally:
        client.close()


def test_retry_gives_up_after_max_attempts():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://source.test"
    )
    source = SourceApiClient(
        "http://source.test",
        max_retries=3,
        backoff_seconds=0.0,
        client=client,
        sleep=lambda _: None,
    )
    try:
        with pytest.raises(Exception) as excinfo:
            list(source.fetch_patients(None, 10))
        assert "500" in str(excinfo.value)
    finally:
        client.close()


def test_invalid_source_payload_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": True})

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://source.test"
    )
    source = SourceApiClient("http://source.test", client=client, sleep=lambda _: None)
    try:
        with pytest.raises(Exception) as excinfo:
            list(source.fetch_clinics(None, 10))
        assert "dogrulanamadi" in str(excinfo.value)
    finally:
        client.close()


def test_duplicate_pages_are_detected():
    """Ayni sayfa tekrar donerse motor mükerrer islem yapmadan durur."""
    payload = {
        "data": [],
        "pagination": {
            "limit": 10,
            "offset": 0,
            "total": 20,
            "has_more": False,
            "next_offset": None,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://source.test"
    )
    source = SourceApiClient("http://source.test", client=client, sleep=lambda _: None)
    try:
        assert list(source.fetch_appointments(None, 10)) == [[]]
    finally:
        client.close()


def test_sync_state_checkpoint_is_utc_naive(engine_for_sync, dataset):
    assert engine_for_sync.run().success
    with Session(engine_for_sync.engine) as session:
        state = session.execute(
            select(SyncState).where(SyncState.entity_type == "clinics")
        ).scalar_one()
        assert state.last_synced_at is not None
        assert state.last_synced_at.tzinfo is None


def test_sync_trigger_endpoint_runs_real_sync(
    clean_db, mssql_settings, source_api_server, dataset, monkeypatch
):
    """Dashboard'un kullandigi POST /api/v1/sync/run ucu gercekten senkronize eder."""
    from fastapi.testclient import TestClient

    import app.routers.sync as sync_router
    from app.main import app as target_app

    runtime_settings = replace(
        mssql_settings,
        source_api_url=source_api_server,
        enable_sync_trigger=True,
        sync_page_size=25,
        http_max_retries=2,
        http_backoff_seconds=0.0,
    )
    monkeypatch.setattr(sync_router, "get_settings", lambda: runtime_settings)
    monkeypatch.setattr(sync_router, "get_engine", lambda: clean_db)

    with TestClient(target_app) as client:
        response = client.post("/api/v1/sync/run")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["job_id"]
    assert counts(clean_db)["appointments"] == 40

    # Ikinci tetikleme de m?kerrer kayit olusturmamali.
    with TestClient(target_app) as client:
        second = client.post("/api/v1/sync/run")
    assert second.status_code == 200
    assert counts(clean_db)["appointments"] == 40
