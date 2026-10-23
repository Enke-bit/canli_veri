/*
  DentSyncDemo semasi (SQL Server 2019/2022 uyumlu)
  -------------------------------------------------
  Bu betik YIKICI DEGILDIR:
  - Var olan tablolarin icine dokunmaz.
  - Yalnizca eksik tablo ve indeksleri olusturur.
  - Veri silmez, tablo dusurmez.

  Calistirma:
    python scripts/init_db.py
  veya SSMS'te DentSyncDemo veritabanina baglanip bu betigi calistirin.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

IF OBJECT_ID(N'dbo.Clinics', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Clinics
    (
        ClinicId          INT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_Clinics PRIMARY KEY,
        ExternalClinicId  NVARCHAR(50)  NOT NULL,
        Name              NVARCHAR(200) NOT NULL,
        CreatedAt         DATETIME2(3)  NOT NULL,
        UpdatedAt         DATETIME2(3)  NOT NULL,
        IsDeleted         BIT           NOT NULL
            CONSTRAINT DF_Clinics_IsDeleted DEFAULT (0),
        SyncedAt          DATETIME2(3)  NOT NULL
            CONSTRAINT DF_Clinics_SyncedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UX_Clinics_ExternalClinicId UNIQUE (ExternalClinicId)
    );
END;
GO

IF OBJECT_ID(N'dbo.Patients', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Patients
    (
        PatientId          INT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_Patients PRIMARY KEY,
        ExternalPatientId  NVARCHAR(50)  NOT NULL,
        ExternalClinicId   NVARCHAR(50)  NOT NULL,
        FirstName          NVARCHAR(100) NOT NULL,
        LastName           NVARCHAR(100) NOT NULL,
        Email              NVARCHAR(200) NULL,
        Phone              NVARCHAR(50)  NULL,
        CreatedAt          DATETIME2(3)  NOT NULL,
        UpdatedAt          DATETIME2(3)  NOT NULL,
        IsDeleted          BIT           NOT NULL
            CONSTRAINT DF_Patients_IsDeleted DEFAULT (0),
        SyncedAt           DATETIME2(3)  NOT NULL
            CONSTRAINT DF_Patients_SyncedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UX_Patients_ExternalPatientId UNIQUE (ExternalPatientId),
        CONSTRAINT FK_Patients_Clinics FOREIGN KEY (ExternalClinicId)
            REFERENCES dbo.Clinics (ExternalClinicId)
    );
END;
GO

IF OBJECT_ID(N'dbo.Appointments', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Appointments
    (
        AppointmentId           INT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_Appointments PRIMARY KEY,
        ExternalAppointmentId   NVARCHAR(50)  NOT NULL,
        ExternalPatientId       NVARCHAR(50)  NOT NULL,
        ExternalClinicId        NVARCHAR(50)  NOT NULL,
        AppointmentDateTime     DATETIME2(3)  NOT NULL,
        EndDateTime             DATETIME2(3)  NOT NULL,
        ProcedureType           NVARCHAR(100) NOT NULL,
        Status                  NVARCHAR(30)  NOT NULL,
        CreatedAt               DATETIME2(3)  NOT NULL,
        UpdatedAt               DATETIME2(3)  NOT NULL,
        IsDeleted               BIT           NOT NULL
            CONSTRAINT DF_Appointments_IsDeleted DEFAULT (0),
        SyncedAt                DATETIME2(3)  NOT NULL
            CONSTRAINT DF_Appointments_SyncedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UX_Appointments_ExternalAppointmentId UNIQUE (ExternalAppointmentId),
        CONSTRAINT CK_Appointments_Status CHECK
            (Status IN ('Scheduled', 'Confirmed', 'Completed', 'Cancelled')),
        CONSTRAINT FK_Appointments_Patients FOREIGN KEY (ExternalPatientId)
            REFERENCES dbo.Patients (ExternalPatientId),
        CONSTRAINT FK_Appointments_Clinics FOREIGN KEY (ExternalClinicId)
            REFERENCES dbo.Clinics (ExternalClinicId),
        CONSTRAINT CK_Appointments_EndAfterStart CHECK (EndDateTime > AppointmentDateTime)
    );
END;
GO

IF OBJECT_ID(N'dbo.SyncState', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.SyncState
    (
        SyncStateId          INT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_SyncState PRIMARY KEY,
        EntityType           NVARCHAR(50) NOT NULL,
        LastSyncedAt         DATETIME2(3) NULL,
        LastSuccessfulRunAt  DATETIME2(3) NULL,
        UpdatedAt            DATETIME2(3) NOT NULL
            CONSTRAINT DF_SyncState_UpdatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UX_SyncState_EntityType UNIQUE (EntityType)
    );
END;
GO

IF OBJECT_ID(N'dbo.SyncLog', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.SyncLog
    (
        SyncLogId            BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_SyncLog PRIMARY KEY,
        JobId                UNIQUEIDENTIFIER NOT NULL,
        EntityType           NVARCHAR(50) NOT NULL,
        OperationType        NVARCHAR(50) NOT NULL,
        StartedAt            DATETIME2(3) NOT NULL,
        FinishedAt           DATETIME2(3) NULL,
        Status               NVARCHAR(20) NOT NULL,
        RecordsRead          INT NOT NULL
            CONSTRAINT DF_SyncLog_RecordsRead DEFAULT (0),
        RecordsInserted      INT NOT NULL
            CONSTRAINT DF_SyncLog_RecordsInserted DEFAULT (0),
        RecordsUpdated       INT NOT NULL
            CONSTRAINT DF_SyncLog_RecordsUpdated DEFAULT (0),
        RecordsDeletedMarked INT NOT NULL
            CONSTRAINT DF_SyncLog_RecordsDeletedMarked DEFAULT (0),
        ErrorCount           INT NOT NULL
            CONSTRAINT DF_SyncLog_ErrorCount DEFAULT (0),
        ErrorSummary         NVARCHAR(2000) NULL,
        CONSTRAINT CK_SyncLog_Status CHECK
            (Status IN ('Running', 'Success', 'Failed', 'Skipped'))
    );
END;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Clinics_UpdatedAt' AND object_id = OBJECT_ID(N'dbo.Clinics'))
    CREATE INDEX IX_Clinics_UpdatedAt ON dbo.Clinics (UpdatedAt);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Patients_UpdatedAt' AND object_id = OBJECT_ID(N'dbo.Patients'))
    CREATE INDEX IX_Patients_UpdatedAt ON dbo.Patients (UpdatedAt);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Patients_ExternalClinicId' AND object_id = OBJECT_ID(N'dbo.Patients'))
    CREATE INDEX IX_Patients_ExternalClinicId ON dbo.Patients (ExternalClinicId);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Appointments_UpdatedAt' AND object_id = OBJECT_ID(N'dbo.Appointments'))
    CREATE INDEX IX_Appointments_UpdatedAt ON dbo.Appointments (UpdatedAt);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Appointments_AppointmentDateTime' AND object_id = OBJECT_ID(N'dbo.Appointments'))
    CREATE INDEX IX_Appointments_AppointmentDateTime ON dbo.Appointments (AppointmentDateTime);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Appointments_Status' AND object_id = OBJECT_ID(N'dbo.Appointments'))
    CREATE INDEX IX_Appointments_Status ON dbo.Appointments (Status);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Appointments_ExternalPatientId' AND object_id = OBJECT_ID(N'dbo.Appointments'))
    CREATE INDEX IX_Appointments_ExternalPatientId ON dbo.Appointments (ExternalPatientId);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_SyncLog_StartedAt' AND object_id = OBJECT_ID(N'dbo.SyncLog'))
    CREATE INDEX IX_SyncLog_StartedAt ON dbo.SyncLog (StartedAt DESC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_SyncLog_EntityType' AND object_id = OBJECT_ID(N'dbo.SyncLog'))
    CREATE INDEX IX_SyncLog_EntityType ON dbo.SyncLog (EntityType);
GO

PRINT 'DentSyncDemo semasi hazir (mevcut veriler korunmustur).';
GO
