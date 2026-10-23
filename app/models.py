"""MSSQL tablolarinin SQLAlchemy karsiliklari.

Semarinin tek kaynagi sql/create_tables.sql dosyasidir; bu modeller
kolon adlari ve tipleriyle o dosyayla birebir uyumludur.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Clinic(Base):
    __tablename__ = "Clinics"

    clinic_id: Mapped[int] = mapped_column(
        "ClinicId", Integer, primary_key=True, autoincrement=True
    )
    external_clinic_id: Mapped[str] = mapped_column(
        "ExternalClinicId", String(50), nullable=False
    )
    name: Mapped[str] = mapped_column("Name", String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("UpdatedAt", DateTime, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        "IsDeleted", Boolean, nullable=False, server_default=text("0")
    )
    synced_at: Mapped[datetime] = mapped_column(
        "SyncedAt", DateTime, nullable=False, server_default=text("SYSUTCDATETIME()")
    )

    __table_args__ = (
        UniqueConstraint("ExternalClinicId", name="UX_Clinics_ExternalClinicId"),
        Index("IX_Clinics_UpdatedAt", "UpdatedAt"),
    )


class Patient(Base):
    __tablename__ = "Patients"

    patient_id: Mapped[int] = mapped_column(
        "PatientId", Integer, primary_key=True, autoincrement=True
    )
    external_patient_id: Mapped[str] = mapped_column(
        "ExternalPatientId", String(50), nullable=False
    )
    external_clinic_id: Mapped[str] = mapped_column(
        "ExternalClinicId",
        String(50),
        ForeignKey("Clinics.ExternalClinicId", name="FK_Patients_Clinics"),
        nullable=False,
    )
    first_name: Mapped[str] = mapped_column("FirstName", String(100), nullable=False)
    last_name: Mapped[str] = mapped_column("LastName", String(100), nullable=False)
    email: Mapped[str | None] = mapped_column("Email", String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column("Phone", String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("UpdatedAt", DateTime, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        "IsDeleted", Boolean, nullable=False, server_default=text("0")
    )
    synced_at: Mapped[datetime] = mapped_column(
        "SyncedAt", DateTime, nullable=False, server_default=text("SYSUTCDATETIME()")
    )

    __table_args__ = (
        UniqueConstraint("ExternalPatientId", name="UX_Patients_ExternalPatientId"),
        Index("IX_Patients_UpdatedAt", "UpdatedAt"),
        Index("IX_Patients_ExternalClinicId", "ExternalClinicId"),
    )


class Appointment(Base):
    __tablename__ = "Appointments"

    appointment_id: Mapped[int] = mapped_column(
        "AppointmentId", Integer, primary_key=True, autoincrement=True
    )
    external_appointment_id: Mapped[str] = mapped_column(
        "ExternalAppointmentId", String(50), nullable=False
    )
    external_patient_id: Mapped[str] = mapped_column(
        "ExternalPatientId",
        String(50),
        ForeignKey("Patients.ExternalPatientId", name="FK_Appointments_Patients"),
        nullable=False,
    )
    external_clinic_id: Mapped[str] = mapped_column(
        "ExternalClinicId",
        String(50),
        ForeignKey("Clinics.ExternalClinicId", name="FK_Appointments_Clinics"),
        nullable=False,
    )
    appointment_datetime: Mapped[datetime] = mapped_column(
        "AppointmentDateTime", DateTime, nullable=False
    )
    end_datetime: Mapped[datetime] = mapped_column(
        "EndDateTime", DateTime, nullable=False
    )
    procedure_type: Mapped[str] = mapped_column(
        "ProcedureType", String(100), nullable=False
    )
    status: Mapped[str] = mapped_column("Status", String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("UpdatedAt", DateTime, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        "IsDeleted", Boolean, nullable=False, server_default=text("0")
    )
    synced_at: Mapped[datetime] = mapped_column(
        "SyncedAt", DateTime, nullable=False, server_default=text("SYSUTCDATETIME()")
    )

    __table_args__ = (
        UniqueConstraint(
            "ExternalAppointmentId", name="UX_Appointments_ExternalAppointmentId"
        ),
        CheckConstraint(
            "Status IN ('Scheduled','Confirmed','Completed','Cancelled')",
            name="CK_Appointments_Status",
        ),
        CheckConstraint(
            "EndDateTime > AppointmentDateTime",
            name="CK_Appointments_EndAfterStart",
        ),
        Index("IX_Appointments_UpdatedAt", "UpdatedAt"),
        Index("IX_Appointments_AppointmentDateTime", "AppointmentDateTime"),
        Index("IX_Appointments_Status", "Status"),
        Index("IX_Appointments_ExternalPatientId", "ExternalPatientId"),
    )


class SyncState(Base):
    __tablename__ = "SyncState"

    sync_state_id: Mapped[int] = mapped_column(
        "SyncStateId", Integer, primary_key=True, autoincrement=True
    )
    entity_type: Mapped[str] = mapped_column("EntityType", String(50), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        "LastSyncedAt", DateTime, nullable=True
    )
    last_successful_run_at: Mapped[datetime | None] = mapped_column(
        "LastSuccessfulRunAt", DateTime, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        "UpdatedAt", DateTime, nullable=False, server_default=text("SYSUTCDATETIME()")
    )

    __table_args__ = (
        UniqueConstraint("EntityType", name="UX_SyncState_EntityType"),
    )


class SyncLog(Base):
    __tablename__ = "SyncLog"

    sync_log_id: Mapped[int] = mapped_column(
        "SyncLogId", BigInteger, primary_key=True, autoincrement=True
    )
    job_id: Mapped[str] = mapped_column("JobId", String(36), nullable=False)
    entity_type: Mapped[str] = mapped_column("EntityType", String(50), nullable=False)
    operation_type: Mapped[str] = mapped_column(
        "OperationType", String(50), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column("StartedAt", DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        "FinishedAt", DateTime, nullable=True
    )
    status: Mapped[str] = mapped_column("Status", String(20), nullable=False)
    records_read: Mapped[int] = mapped_column(
        "RecordsRead", Integer, nullable=False, server_default=text("0")
    )
    records_inserted: Mapped[int] = mapped_column(
        "RecordsInserted", Integer, nullable=False, server_default=text("0")
    )
    records_updated: Mapped[int] = mapped_column(
        "RecordsUpdated", Integer, nullable=False, server_default=text("0")
    )
    records_deleted_marked: Mapped[int] = mapped_column(
        "RecordsDeletedMarked", Integer, nullable=False, server_default=text("0")
    )
    error_count: Mapped[int] = mapped_column(
        "ErrorCount", Integer, nullable=False, server_default=text("0")
    )
    error_summary: Mapped[str | None] = mapped_column(
        "ErrorSummary", String(2000), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "Status IN ('Running','Success','Failed','Skipped')",
            name="CK_SyncLog_Status",
        ),
        Index("IX_SyncLog_StartedAt", "StartedAt"),
        Index("IX_SyncLog_EntityType", "EntityType"),
    )
