"""API -> MSSQL senkronizasyon motoru.

Tasarim:
- Tur bazli sira: clinics -> patients -> appointments (foreign key guvenligi).
- Sayfa bazli transaction; checkpoint yalnizca tum sayfalar basarili olunca ilerler.
- Upsert: dis kimlige gore kayit varsa guncelle, yoksa ekle.
- updated_since + ortusme penceresi ile sinir kacaklarini onler.
- 429/5xx/timeout icin sinirli, artan beklemeli retry.
- Her tur icin SyncLog satiri; basarisizlik asla 'Success' yazilmaz.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Appointment, Clinic, Patient, SyncLog, SyncState
from app.source_schemas import (
    SourceAppointment,
    SourceAppointmentPage,
    SourceClinic,
    SourceClinicPage,
    SourcePatient,
    SourcePatientPage,
)

logger = logging.getLogger(__name__)

ENTITY_ORDER = ("clinics", "patients", "appointments")
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class SyncError(RuntimeError):
    """Senkronizasyonun durdurulmasi gereken hata."""


@dataclass
class EntityStats:
    entity: str
    read: int = 0
    inserted: int = 0
    updated: int = 0
    deleted_marked: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int | str]:
        return {
            "entity": self.entity,
            "read": self.read,
            "inserted": self.inserted,
            "updated": self.updated,
            "deleted_marked": self.deleted_marked,
            "errors": self.errors,
        }


@dataclass
class SyncRunResult:
    job_id: str
    started_at: datetime
    finished_at: datetime | None = None
    success: bool = False
    entities: list[EntityStats] = field(default_factory=list)
    error: str | None = None
    skipped_entities: list[str] = field(default_factory=list)


def utc_now_naive() -> datetime:
    """Veritabaninda naive UTC saklariz."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(microsecond=0)
    return value.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def to_iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


class SourceApiClient:
    """Kaynak API istemcisi; retry ve dogrulama burada yapilir."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 15.0,
        max_retries: int = 4,
        backoff_seconds: float = 1.0,
        client: httpx.Client | None = None,
        sleep=time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(1, max_retries)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url, timeout=timeout, follow_redirects=True
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error = "bilinmeyen hata"
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.get(path, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt >= self.max_retries:
                    raise SyncError(
                        f"Kaynak API'ye ulasilamadi ({path}): {last_error}"
                    ) from exc
                self._sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                continue

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise SyncError(f"Kaynak API gecerli JSON dondurmedi ({path}).") from exc
                if not isinstance(payload, dict):
                    raise SyncError(f"Kaynak API beklenmeyen cevap dondurdu ({path}).")
                return payload

            snippet = response.text[:300].replace("\n", " ")
            if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                retry_after = response.headers.get("Retry-After")
                delay = None
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = None
                if delay is None:
                    delay = self.backoff_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "Kaynak API %s dondurdu (%s), %.2fs sonra tekrar denenecek (%s/%s).",
                    response.status_code,
                    path,
                    delay,
                    attempt,
                    self.max_retries,
                )
                self._sleep(delay)
                continue

            raise SyncError(
                f"Kaynak API istegi basarisiz ({path}) HTTP {response.status_code}: {snippet}"
            )

        raise SyncError(f"Kaynak API istegi basarisiz ({path}): {last_error}")

    def _fetch_all(
        self,
        path: str,
        page_model,
        updated_since: datetime | None,
        page_size: int,
    ) -> Iterable[Any]:
        offset = 0
        while True:
            params: dict[str, Any] = {
                "limit": page_size,
                "offset": offset,
                "include_deleted": "true",
            }
            if updated_since is not None:
                params["updated_since"] = to_iso_z(updated_since)
            payload = self._get_json(path, params)
            try:
                page = page_model.model_validate(payload)
            except ValidationError as exc:
                raise SyncError(
                    f"Kaynak API cevabi dogrulanamadi ({path}, offset={offset}): {exc}"
                ) from exc
            if page.pagination.offset != offset:
                raise SyncError(
                    f"Kaynak API sayfalama tutarsiz ({path}): beklenen offset {offset}, "
                    f"gelen {page.pagination.offset}."
                )
            yield page.data
            if not page.pagination.has_more:
                break
            next_offset = page.pagination.next_offset
            if next_offset is None or next_offset <= offset:
                raise SyncError(
                    f"Kaynak API gecersiz next_offset dondurdu ({path}): {next_offset}."
                )
            if next_offset > page.pagination.total + page_size:
                raise SyncError(
                    f"Kaynak API next_offset degeri toplamla uyumsuz ({path})."
                )
            offset = next_offset

    def fetch_clinics(self, updated_since, page_size) -> Iterable[list[SourceClinic]]:
        return self._fetch_all(
            "/source/clinics", SourceClinicPage, updated_since, page_size
        )

    def fetch_patients(self, updated_since, page_size) -> Iterable[list[SourcePatient]]:
        return self._fetch_all(
            "/source/patients", SourcePatientPage, updated_since, page_size
        )

    def fetch_appointments(
        self, updated_since, page_size
    ) -> Iterable[list[SourceAppointment]]:
        return self._fetch_all(
            "/source/appointments", SourceAppointmentPage, updated_since, page_size
        )


class SyncEngine:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        client: SourceApiClient | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self._owns_client = client is None
        self.client = client or SourceApiClient(
            settings.source_api_url,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            backoff_seconds=settings.http_backoff_seconds,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    # ------------------------------------------------------------------ run
    def run(
        self,
        entities: Sequence[str] = ENTITY_ORDER,
        force_full: bool = False,
    ) -> SyncRunResult:
        job_id = str(uuid.uuid4())
        run = SyncRunResult(job_id=job_id, started_at=utc_now_naive())
        logger.info("Senkronizasyon basladi. job_id=%s, turler=%s", job_id, entities)

        for position, entity in enumerate(entities):
            stats = EntityStats(entity=entity)
            try:
                self._sync_entity(entity, stats, job_id, force_full)
                run.entities.append(stats)
                logger.info("Tur tamamlandi: %s %s", entity, stats.as_dict())
            except Exception as exc:  # noqa: BLE001 - tum hata ozeti loglanir
                message = self._safe_error(exc)
                stats.errors += 1
                run.entities.append(stats)
                run.error = f"{entity}: {message}"
                run.skipped_entities = list(entities[position + 1 :])
                if isinstance(exc, SyncError):
                    # Beklenen operasyonel hata: kisa mesaj, tam traceback dosyaya.
                    logger.error("Tur basarisiz: %s -> %s", entity, message)
                    logger.debug("Ayrinti:", exc_info=True)
                else:
                    logger.exception("Tur basarisiz: %s -> %s", entity, message)
                break

        run.finished_at = utc_now_naive()
        run.success = run.error is None
        if run.success:
            logger.info("Senkronizasyon basarili. job_id=%s", job_id)
        else:
            logger.error(
                "Senkronizasyon BASARISIZ. job_id=%s hata=%s", job_id, run.error
            )
        return run

    def _safe_error(self, exc: Exception) -> str:
        message = f"{type(exc).__name__}: {exc}"
        password = self.settings.db_password
        if password:
            message = message.replace(password, "***")
        return message[:1900]

    # -------------------------------------------------------------- entities
    def _sync_entity(
        self, entity: str, stats: EntityStats, job_id: str, force_full: bool
    ) -> None:
        log_id = self._start_log(job_id, entity)
        run_started = utc_now_naive()
        last_synced = None if force_full else self._get_state(entity)
        since = None
        if last_synced is not None:
            since = last_synced - timedelta(seconds=self.settings.sync_overlap_seconds)

        try:
            if entity == "clinics":
                pages = self.client.fetch_clinics(since, self.settings.sync_page_size)
                upsert = self._upsert_clinic_page
            elif entity == "patients":
                pages = self.client.fetch_patients(since, self.settings.sync_page_size)
                upsert = self._upsert_patient_page
            elif entity == "appointments":
                pages = self.client.fetch_appointments(since, self.settings.sync_page_size)
                upsert = self._upsert_appointment_page
            else:
                raise SyncError(f"Bilinmeyen tur: {entity}")

            seen_ids: set[str] = set()
            for page in pages:
                if not page:
                    continue
                ids = [self._external_id(entity, record) for record in page]
                duplicates = {value for value in ids if value in seen_ids}
                if duplicates:
                    raise SyncError(
                        f"Kaynak ayni sayfa(lar)da tekrarlanan kimlik dondurdu: {duplicates}"
                    )
                seen_ids.update(ids)
                stats.read += len(page)
                with Session(self.engine) as session:
                    with session.begin():
                        upsert(session, page, stats)
                logger.debug("%s: %s kayit islendi.", entity, stats.read)

            with Session(self.engine) as session:
                with session.begin():
                    self._save_state(session, entity, run_started)
            self._finish_log(log_id, "Success", stats, None)
        except Exception as exc:
            self._finish_log(log_id, "Failed", stats, self._safe_error(exc))
            raise

    @staticmethod
    def _external_id(entity: str, record: Any) -> str:
        if entity == "clinics":
            return record.external_clinic_id
        if entity == "patients":
            return record.external_patient_id
        return record.external_appointment_id

    # ------------------------------------------------------------------ logs
    def _start_log(self, job_id: str, entity: str) -> int:
        with Session(self.engine) as session:
            with session.begin():
                log = SyncLog(
                    job_id=job_id,
                    entity_type=entity,
                    operation_type="sync",
                    started_at=utc_now_naive(),
                    status="Running",
                )
                session.add(log)
                session.flush()
                return int(log.sync_log_id)

    def _finish_log(
        self,
        log_id: int,
        status: str,
        stats: EntityStats,
        error_summary: str | None,
    ) -> None:
        try:
            with Session(self.engine) as session:
                with session.begin():
                    log = session.get(SyncLog, log_id)
                    if log is None:
                        return
                    log.status = status
                    log.finished_at = utc_now_naive()
                    log.records_read = stats.read
                    log.records_inserted = stats.inserted
                    log.records_updated = stats.updated
                    log.records_deleted_marked = stats.deleted_marked
                    log.error_count = stats.errors
                    log.error_summary = error_summary
        except Exception:  # noqa: BLE001
            logger.exception("SyncLog guncellenemedi (log_id=%s).", log_id)

    def _get_state(self, entity: str) -> datetime | None:
        with Session(self.engine) as session:
            state = session.execute(
                select(SyncState).where(SyncState.entity_type == entity)
            ).scalar_one_or_none()
            return state.last_synced_at if state else None

    def _save_state(self, session: Session, entity: str, checkpoint: datetime) -> None:
        state = session.execute(
            select(SyncState).where(SyncState.entity_type == entity)
        ).scalar_one_or_none()
        now = utc_now_naive()
        if state is None:
            state = SyncState(entity_type=entity)
            session.add(state)
        state.last_synced_at = checkpoint
        state.last_successful_run_at = now
        state.updated_at = now

    # ---------------------------------------------------------------- upserts
    def _upsert_clinic_page(
        self, session: Session, page: list[SourceClinic], stats: EntityStats
    ) -> None:
        ids = [record.external_clinic_id for record in page]
        existing = {
            row.external_clinic_id: row
            for row in session.execute(
                select(Clinic).where(Clinic.external_clinic_id.in_(ids))
            ).scalars()
        }
        now = utc_now_naive()
        for record in page:
            row = existing.get(record.external_clinic_id)
            created = to_naive_utc(record.created_at)
            updated = to_naive_utc(record.updated_at)
            if row is None:
                session.add(
                    Clinic(
                        external_clinic_id=record.external_clinic_id,
                        name=record.name,
                        created_at=created,
                        updated_at=updated,
                        is_deleted=record.is_deleted,
                        synced_at=now,
                    )
                )
                stats.inserted += 1
                if record.is_deleted:
                    stats.deleted_marked += 1
                continue
            changed = (
                row.name != record.name
                or row.created_at != created
                or row.updated_at != updated
                or bool(row.is_deleted) != record.is_deleted
            )
            if changed:
                if record.is_deleted and not row.is_deleted:
                    stats.deleted_marked += 1
                row.name = record.name
                row.created_at = created
                row.updated_at = updated
                row.is_deleted = record.is_deleted
                row.synced_at = now
                stats.updated += 1

    def _upsert_patient_page(
        self, session: Session, page: list[SourcePatient], stats: EntityStats
    ) -> None:
        ids = [record.external_patient_id for record in page]
        existing = {
            row.external_patient_id: row
            for row in session.execute(
                select(Patient).where(Patient.external_patient_id.in_(ids))
            ).scalars()
        }
        clinic_ids = {record.external_clinic_id for record in page}
        known_clinics = set(
            session.execute(
                select(Clinic.external_clinic_id).where(
                    Clinic.external_clinic_id.in_(clinic_ids)
                )
            ).scalars()
        )
        missing = clinic_ids - known_clinics
        if missing:
            raise SyncError(
                "Hasta kayitlari icin klinik bulunamadi: " + ", ".join(sorted(missing))
            )

        now = utc_now_naive()
        for record in page:
            row = existing.get(record.external_patient_id)
            created = to_naive_utc(record.created_at)
            updated = to_naive_utc(record.updated_at)
            if row is None:
                session.add(
                    Patient(
                        external_patient_id=record.external_patient_id,
                        external_clinic_id=record.external_clinic_id,
                        first_name=record.first_name,
                        last_name=record.last_name,
                        email=record.email,
                        phone=record.phone,
                        created_at=created,
                        updated_at=updated,
                        is_deleted=record.is_deleted,
                        synced_at=now,
                    )
                )
                stats.inserted += 1
                if record.is_deleted:
                    stats.deleted_marked += 1
                continue
            changed = (
                row.external_clinic_id != record.external_clinic_id
                or row.first_name != record.first_name
                or row.last_name != record.last_name
                or row.email != record.email
                or row.phone != record.phone
                or row.created_at != created
                or row.updated_at != updated
                or bool(row.is_deleted) != record.is_deleted
            )
            if changed:
                if record.is_deleted and not row.is_deleted:
                    stats.deleted_marked += 1
                row.external_clinic_id = record.external_clinic_id
                row.first_name = record.first_name
                row.last_name = record.last_name
                row.email = record.email
                row.phone = record.phone
                row.created_at = created
                row.updated_at = updated
                row.is_deleted = record.is_deleted
                row.synced_at = now
                stats.updated += 1

    def _upsert_appointment_page(
        self, session: Session, page: list[SourceAppointment], stats: EntityStats
    ) -> None:
        ids = [record.external_appointment_id for record in page]
        existing = {
            row.external_appointment_id: row
            for row in session.execute(
                select(Appointment).where(Appointment.external_appointment_id.in_(ids))
            ).scalars()
        }
        patient_ids = {record.external_patient_id for record in page}
        clinic_ids = {record.external_clinic_id for record in page}
        known_patients = set(
            session.execute(
                select(Patient.external_patient_id).where(
                    Patient.external_patient_id.in_(patient_ids)
                )
            ).scalars()
        )
        known_clinics = set(
            session.execute(
                select(Clinic.external_clinic_id).where(
                    Clinic.external_clinic_id.in_(clinic_ids)
                )
            ).scalars()
        )
        missing_patients = patient_ids - known_patients
        missing_clinics = clinic_ids - known_clinics
        if missing_patients or missing_clinics:
            details = []
            if missing_patients:
                details.append("hasta: " + ", ".join(sorted(missing_patients)))
            if missing_clinics:
                details.append("klinik: " + ", ".join(sorted(missing_clinics)))
            raise SyncError(
                "Randevular icin iliskili kayit bulunamadi (" + "; ".join(details) + ")."
            )

        now = utc_now_naive()
        for record in page:
            row = existing.get(record.external_appointment_id)
            start = to_naive_utc(record.appointment_datetime)
            end = to_naive_utc(record.end_datetime)
            created = to_naive_utc(record.created_at)
            updated = to_naive_utc(record.updated_at)
            if row is None:
                session.add(
                    Appointment(
                        external_appointment_id=record.external_appointment_id,
                        external_patient_id=record.external_patient_id,
                        external_clinic_id=record.external_clinic_id,
                        appointment_datetime=start,
                        end_datetime=end,
                        procedure_type=record.procedure_type,
                        status=record.status,
                        created_at=created,
                        updated_at=updated,
                        is_deleted=record.is_deleted,
                        synced_at=now,
                    )
                )
                stats.inserted += 1
                if record.is_deleted:
                    stats.deleted_marked += 1
                continue
            changed = (
                row.external_patient_id != record.external_patient_id
                or row.external_clinic_id != record.external_clinic_id
                or row.appointment_datetime != start
                or row.end_datetime != end
                or row.procedure_type != record.procedure_type
                or row.status != record.status
                or row.created_at != created
                or row.updated_at != updated
                or bool(row.is_deleted) != record.is_deleted
            )
            if changed:
                if record.is_deleted and not row.is_deleted:
                    stats.deleted_marked += 1
                row.external_patient_id = record.external_patient_id
                row.external_clinic_id = record.external_clinic_id
                row.appointment_datetime = start
                row.end_datetime = end
                row.procedure_type = record.procedure_type
                row.status = record.status
                row.created_at = created
                row.updated_at = updated
                row.is_deleted = record.is_deleted
                row.synced_at = now
                stats.updated += 1


def run_sync(settings: Settings, engine: Engine, **kwargs) -> SyncRunResult:
    sync = SyncEngine(settings, engine)
    try:
        return sync.run(**kwargs)
    finally:
        sync.close()
