"""Sentetik klinik/hasta/randevu verisi uretir.

Kullanim:
    python scripts/generate_synthetic_data.py
    python scripts/generate_synthetic_data.py --patients 50 --appointments 200 --force
    python scripts/generate_synthetic_data.py --validate-only

Guvenlik:
- Yalnizca sentetik veri uretir (example.test e-posta, TEST_PHONE_* telefon).
- Var olan dosyanin uzerine yazmak icin --force gerekir; once yedek alinir.
- Hicbir zaman mevcut dosyayi sessizce silmez.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from faker import Faker  # noqa: E402

DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "synthetic_source.json"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"

PROCEDURE_TYPES = [
    "Genel muayene",
    "Kontrol",
    "Dis temizligi",
    "Dolgu",
    "Dis cekimi",
    "Kanal tedavisi",
    "Rutin kontrol",
]
APPOINTMENT_STATUSES = ["Scheduled", "Confirmed", "Completed", "Cancelled"]
CLINIC_NAMES = [
    "Demo Klinik Merkez",
    "Demo Klinik Kuzey",
    "Demo Klinik Sahil",
    "Demo Klinik Guney",
    "Demo Klinik Batı",
]


def _iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _choose_status(rng: random.Random, appointment_dt: datetime, now: datetime) -> str:
    is_past = appointment_dt < now - timedelta(hours=1)
    if is_past:
        return rng.choices(
            ["Completed", "Cancelled", "Confirmed", "Scheduled"],
            weights=[65, 15, 10, 10],
            k=1,
        )[0]
    return rng.choices(
        ["Scheduled", "Confirmed", "Cancelled"], weights=[55, 30, 15], k=1
    )[0]


def generate_dataset(
    clinics: int = 3,
    patients: int = 500,
    appointments: int = 2000,
    seed: int = 42,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Belirtilen sayida tutarli sentetik veri uretir (dosyaya yazmaz)."""
    if clinics < 1:
        raise ValueError("En az 1 klinik gerekir.")
    if patients < 1:
        raise ValueError("En az 1 hasta gerekir.")
    if appointments < 1:
        raise ValueError("En az 1 randevu gerekir.")

    now = (as_of or _utc_now()).astimezone(timezone.utc).replace(microsecond=0)
    rng = random.Random(seed)
    fake = Faker("tr_TR")
    Faker.seed(seed)

    clinic_records: list[dict[str, Any]] = []
    for index in range(1, clinics + 1):
        created = now - timedelta(days=rng.randint(200, 900), hours=rng.randint(0, 23))
        updated = created + timedelta(days=rng.randint(0, max(1, (now - created).days)))
        name = (
            CLINIC_NAMES[index - 1]
            if index <= len(CLINIC_NAMES)
            else f"Demo Klinik {index:02d}"
        )
        clinic_records.append(
            {
                "ExternalClinicId": f"CLN-{index:04d}",
                "Name": name,
                "CreatedAt": _iso_z(created),
                "UpdatedAt": _iso_z(min(updated, now)),
                "IsDeleted": False,
            }
        )

    patient_records: list[dict[str, Any]] = []
    for index in range(1, patients + 1):
        clinic = clinic_records[(index - 1) % clinics]
        created = now - timedelta(
            days=rng.randint(1, 700), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        updated = created + timedelta(
            days=rng.randint(0, max(0, (now - created).days)),
            hours=rng.randint(0, 23),
        )
        first_name = fake.first_name()
        last_name = fake.last_name()
        patient_records.append(
            {
                "ExternalPatientId": f"PAT-{index:06d}",
                "ExternalClinicId": clinic["ExternalClinicId"],
                "FirstName": first_name,
                "LastName": last_name,
                "Email": f"patient{index:06d}@example.test",
                "Phone": f"TEST_PHONE_{index:06d}",
                "CreatedAt": _iso_z(created),
                "UpdatedAt": _iso_z(min(updated, now)),
                "IsDeleted": False,
            }
        )

    appointment_records: list[dict[str, Any]] = []
    for index in range(1, appointments + 1):
        patient = rng.choice(patient_records)

        bucket = rng.choices(["past", "today", "future"], weights=[30, 5, 65], k=1)[0]
        if bucket == "past":
            day_offset = rng.randint(-180, -1)
        elif bucket == "today":
            day_offset = 0
        else:
            day_offset = rng.randint(1, 120)

        appointment_dt = (now + timedelta(days=day_offset)).replace(
            hour=rng.choice([9, 10, 11, 12, 13, 14, 15, 16]),
            minute=rng.choice([0, 30]),
            second=0,
            microsecond=0,
        )
        duration = rng.choice([30, 30, 45, 60, 60, 90])
        end_dt = appointment_dt + timedelta(minutes=duration)

        created = now - timedelta(
            days=rng.randint(0, 45), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        updated = created + timedelta(
            days=rng.randint(0, 5), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        status = _choose_status(rng, appointment_dt, now)

        appointment_records.append(
            {
                "ExternalAppointmentId": f"APT-{index:06d}",
                "ExternalPatientId": patient["ExternalPatientId"],
                "ExternalClinicId": patient["ExternalClinicId"],
                "AppointmentDateTime": _iso_z(appointment_dt),
                "EndDateTime": _iso_z(end_dt),
                "ProcedureType": rng.choice(PROCEDURE_TYPES),
                "Status": status,
                "CreatedAt": _iso_z(created),
                "UpdatedAt": _iso_z(min(updated, now)),
                "IsDeleted": False,
            }
        )

    return {
        "meta": {
            "schema_version": 1,
            "generated_at": _iso_z(now),
            "seed": seed,
            "counts": {
                "clinics": len(clinic_records),
                "patients": len(patient_records),
                "appointments": len(appointment_records),
            },
            "note": (
                "Tamamen sentetik demo verisi. Gercek hasta/klinik bilgisi icermez. "
                "E-postalar example.test, telefonlar TEST_PHONE_* formatindadir."
            ),
            "time_format": "ISO-8601 UTC, ornek: 2026-01-31T09:30:00Z",
        },
        "clinics": clinic_records,
        "patients": patient_records,
        "appointments": appointment_records,
    }


def validate_dataset(data: dict[str, Any]) -> list[str]:
    """Veri butunlugu kontrolleri; hata listesi dondurur (bos = gecerli)."""
    errors: list[str] = []
    for key in ("clinics", "patients", "appointments"):
        if not isinstance(data.get(key), list):
            return [f"'{key}' listesi eksik veya gecersiz."]

    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    clinic_ids: set[str] = set()
    for clinic in data["clinics"]:
        cid = clinic.get("ExternalClinicId")
        if not cid:
            errors.append("Klinikte ExternalClinicId eksik.")
            continue
        if cid in clinic_ids:
            errors.append(f"Tekrarlanan klinik kimligi: {cid}")
        clinic_ids.add(cid)
        try:
            created = parse(clinic["CreatedAt"])
            updated = parse(clinic["UpdatedAt"])
            if updated < created:
                errors.append(f"{cid}: UpdatedAt < CreatedAt")
        except (KeyError, ValueError) as exc:
            errors.append(f"{cid}: gecersiz tarih ({exc})")

    patient_ids: set[str] = set()
    patient_clinic: dict[str, str] = {}
    for patient in data["patients"]:
        pid = patient.get("ExternalPatientId")
        if not pid:
            errors.append("Hastada ExternalPatientId eksik.")
            continue
        if pid in patient_ids:
            errors.append(f"Tekrarlanan hasta kimligi: {pid}")
        patient_ids.add(pid)
        pcid = patient.get("ExternalClinicId")
        patient_clinic[pid] = pcid
        if pcid not in clinic_ids:
            errors.append(f"{pid}: bilinmeyen klinik {pcid}")
        email = patient.get("Email") or ""
        phone = patient.get("Phone") or ""
        if email and not email.endswith("@example.test"):
            errors.append(f"{pid}: e-posta sentetik alan adi kullanmiyor: {email}")
        if phone and not phone.startswith("TEST_PHONE_"):
            errors.append(f"{pid}: telefon sentetik degil: {phone}")
        try:
            created = parse(patient["CreatedAt"])
            updated = parse(patient["UpdatedAt"])
            if updated < created:
                errors.append(f"{pid}: UpdatedAt < CreatedAt")
        except (KeyError, ValueError) as exc:
            errors.append(f"{pid}: gecersiz tarih ({exc})")

    appointment_ids: set[str] = set()
    buckets = {"past": 0, "today": 0, "future": 0}
    # Referans tarih: veri setinin uretim ani (meta.generated_at). Yoksa simdi.
    now = _utc_now()
    generated_at = data.get("meta", {}).get("generated_at") if isinstance(data.get("meta"), dict) else None
    if generated_at:
        try:
            now = parse(generated_at)
        except ValueError:
            errors.append(f"meta.generated_at gecersiz: {generated_at}")
    for appointment in data["appointments"]:
        aid = appointment.get("ExternalAppointmentId")
        if not aid:
            errors.append("Randevuda ExternalAppointmentId eksik.")
            continue
        if aid in appointment_ids:
            errors.append(f"Tekrarlanan randevu kimligi: {aid}")
        appointment_ids.add(aid)

        pid = appointment.get("ExternalPatientId")
        cid = appointment.get("ExternalClinicId")
        if pid not in patient_ids:
            errors.append(f"{aid}: bilinmeyen hasta {pid}")
        if cid not in clinic_ids:
            errors.append(f"{aid}: bilinmeyen klinik {cid}")
        if pid in patient_clinic and cid != patient_clinic[pid]:
            errors.append(f"{aid}: hasta ve randevu klinigi uyusmuyor")
        if appointment.get("Status") not in APPOINTMENT_STATUSES:
            errors.append(f"{aid}: gecersiz durum {appointment.get('Status')}")
        if not appointment.get("ProcedureType"):
            errors.append(f"{aid}: ProcedureType bos")
        try:
            start = parse(appointment["AppointmentDateTime"])
            end = parse(appointment["EndDateTime"])
            if end <= start:
                errors.append(f"{aid}: EndDateTime <= AppointmentDateTime")
            day = start.date()
            if day < now.date():
                buckets["past"] += 1
            elif day == now.date():
                buckets["today"] += 1
            else:
                buckets["future"] += 1
        except (KeyError, ValueError) as exc:
            errors.append(f"{aid}: gecersiz tarih ({exc})")

    if not any(buckets.values()):
        errors.append("Hic randevu yok.")
    elif len(data["appointments"]) >= 20 and (
        buckets["past"] == 0 or buckets["future"] == 0
    ):
        errors.append(
            "Gecmis ve gelecek tarihli randevu ornekleri bulunmuyor "
            f"(past={buckets['past']}, future={buckets['future']})."
        )
    return errors


def write_dataset(
    data: dict[str, Any], output: Path = DEFAULT_OUTPUT, force: bool = False
) -> Path:
    errors = validate_dataset(data)
    if errors:
        raise ValueError("Uretilen veri gecersiz: " + "; ".join(errors[:10]))

    output = output if output.is_absolute() else PROJECT_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not force:
        raise FileExistsError(
            f"Dosya zaten var: {output}. Uzerine yazmak icin --force kullanin. "
            "Mevcut dosya silinmez; --force ile once yedek alinir."
        )

    backup_path: Path | None = None
    if output.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"{output.stem}_{stamp}.json"
        backup_path.write_text(output.read_text(encoding="utf-8"), encoding="utf-8")

    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp.replace(output)
    if backup_path:
        print(f"Onceki dosya yedeklendi: {backup_path}")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sentetik veri uretici")
    parser.add_argument("--clinics", type=int, default=3)
    parser.add_argument("--patients", type=int, default=500)
    parser.add_argument("--appointments", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="Baz tarih (ISO-8601). Ayni tohum + ayni tarih ayni veriyi uretir.",
    )
    parser.add_argument("--force", action="store_true", help="Mevcut dosyanin uzerine yaz")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Yeni veri uretmeden mevcut dosyayi dogrula",
    )
    args = parser.parse_args(argv)

    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output

    if args.validate_only:
        try:
            data = json.loads(output.read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"HATA: Dosya bulunamadi: {output}")
            return 2
        errors = validate_dataset(data)
        if errors:
            print(f"DOGRULAMA BASARISIZ ({len(errors)} hata):")
            for error in errors[:25]:
                print(" -", error)
            return 1
        print(f"DOGRULAMA BASARILI: {output}")
        print(
            "Kayitlar: "
            f"{len(data['clinics'])} klinik, {len(data['patients'])} hasta, "
            f"{len(data['appointments'])} randevu"
        )
        return 0

    as_of = None
    if args.as_of:
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))

    data = generate_dataset(
        clinics=args.clinics,
        patients=args.patients,
        appointments=args.appointments,
        seed=args.seed,
        as_of=as_of,
    )
    try:
        path = write_dataset(data, output=output, force=args.force)
    except FileExistsError as exc:
        print(f"HATA: {exc}")
        return 2
    except ValueError as exc:
        print(f"HATA: {exc}")
        return 1

    print(f"Sentetik veri olusturuldu: {path}")
    print(
        f"  {len(data['clinics'])} klinik, {len(data['patients'])} hasta, "
        f"{len(data['appointments'])} randevu (seed={args.seed})"
    )
    print("Dogrulama: BASARILI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
