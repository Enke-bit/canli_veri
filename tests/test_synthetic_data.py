"""Sentetik veri ureticisi testleri (harici bagimlilik yok)."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from scripts.generate_synthetic_data import (
    generate_dataset,
    validate_dataset,
    write_dataset,
)

FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_dataset_counts_and_structure():
    data = generate_dataset(clinics=3, patients=500, appointments=2000, seed=7, as_of=FIXED_NOW)
    assert len(data["clinics"]) == 3
    assert len(data["patients"]) == 500
    assert len(data["appointments"]) == 2000
    assert data["meta"]["seed"] == 7
    assert validate_dataset(data) == []


def test_referential_integrity():
    data = generate_dataset(clinics=3, patients=30, appointments=120, seed=11, as_of=FIXED_NOW)
    clinic_ids = {c["ExternalClinicId"] for c in data["clinics"]}
    patient_clinic = {p["ExternalPatientId"]: p["ExternalClinicId"] for p in data["patients"]}
    for appointment in data["appointments"]:
        assert appointment["ExternalPatientId"] in patient_clinic
        assert appointment["ExternalClinicId"] in clinic_ids
        assert patient_clinic[appointment["ExternalPatientId"]] == appointment[
            "ExternalClinicId"
        ]


def test_valid_appointment_times_and_statuses():
    data = generate_dataset(clinics=3, patients=20, appointments=100, seed=5, as_of=FIXED_NOW)
    statuses = {a["Status"] for a in data["appointments"]}
    assert statuses <= {"Scheduled", "Confirmed", "Completed", "Cancelled"}
    assert len(statuses) > 1
    for appointment in data["appointments"]:
        start = datetime.fromisoformat(
            appointment["AppointmentDateTime"].replace("Z", "+00:00")
        )
        end = datetime.fromisoformat(appointment["EndDateTime"].replace("Z", "+00:00"))
        assert end > start
        assert appointment["ProcedureType"]


def test_past_today_and_future_appointments_exist():
    data = generate_dataset(clinics=3, patients=40, appointments=400, seed=13, as_of=FIXED_NOW)
    days = {
        datetime.fromisoformat(a["AppointmentDateTime"].replace("Z", "+00:00")).date()
        for a in data["appointments"]
    }
    assert any(day < FIXED_NOW.date() for day in days)
    assert any(day == FIXED_NOW.date() for day in days)
    assert any(day > FIXED_NOW.date() for day in days)


def test_same_seed_reproduces_same_dataset():
    first = generate_dataset(clinics=2, patients=10, appointments=30, seed=99, as_of=FIXED_NOW)
    second = generate_dataset(clinics=2, patients=10, appointments=30, seed=99, as_of=FIXED_NOW)
    assert first == second


def test_different_seed_changes_data():
    first = generate_dataset(clinics=2, patients=10, appointments=30, seed=1, as_of=FIXED_NOW)
    second = generate_dataset(clinics=2, patients=10, appointments=30, seed=2, as_of=FIXED_NOW)
    assert first["appointments"] != second["appointments"]


def test_only_synthetic_contact_data():
    data = generate_dataset(clinics=3, patients=50, appointments=50, seed=3, as_of=FIXED_NOW)
    for patient in data["patients"]:
        assert patient["Email"].endswith("@example.test")
        assert patient["Phone"].startswith("TEST_PHONE_")


def test_validate_detects_orphan_appointment():
    data = generate_dataset(clinics=3, patients=5, appointments=10, seed=4, as_of=FIXED_NOW)
    broken = copy.deepcopy(data)
    broken["appointments"][0]["ExternalPatientId"] = "PAT-DOES-NOT-EXIST"
    errors = validate_dataset(broken)
    assert errors


def test_validate_detects_invalid_status():
    data = generate_dataset(clinics=1, patients=3, appointments=5, seed=4, as_of=FIXED_NOW)
    broken = copy.deepcopy(data)
    broken["appointments"][0]["Status"] = "Unknown"
    assert validate_dataset(broken)


def test_write_dataset_refuses_overwrite_without_force(tmp_path):
    data = generate_dataset(clinics=1, patients=3, appointments=200, seed=4, as_of=FIXED_NOW)
    target = tmp_path / "data.json"
    write_dataset(data, output=target)
    original = target.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_dataset(data, output=target)
    assert target.read_text(encoding="utf-8") == original


def test_write_dataset_with_force_keeps_backup(tmp_path, monkeypatch):
    from scripts import generate_synthetic_data as module

    monkeypatch.setattr(module, "BACKUP_DIR", tmp_path / "backups")
    data = generate_dataset(clinics=1, patients=3, appointments=200, seed=4, as_of=FIXED_NOW)
    target = tmp_path / "data.json"
    write_dataset(data, output=target)
    written = write_dataset(data, output=target, force=True)
    assert written == target
    backups = list((tmp_path / "backups").glob("*.json"))
    assert len(backups) == 1
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert len(parsed["appointments"]) == 200
