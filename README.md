# DentSync Demo — MSSQL + Python API Otomatik Veri Senkronizasyonu

Bu proje, **tamamen sentetik** klinik verilerini uçtan uca şu akışla taşır:

```
Sentetik veri üreticisi
        │  (data/synthetic_source.json)
        ▼
Kaynak API (sahte dış sistem)  ── port 8001
        │  HTTP / JSON
        ▼
Senkronizasyon servisi (Python)
        │  upsert + checkpoint + retry
        ▼
MSSQL  (DentSyncDemo)
        │
        ▼
Hedef API (kendi REST API'miz) ── port 8000
        │
        ▼
API istemcisi (tarayıcı / curl / başka uygulama)
```

Projenin amacı öğrenmektir: Python, REST API, MSSQL, sentetik veri ve otomatik
senkronizasyonun nasıl birlikte çalıştığını çalışan bir sistem üzerinde gösterir.

> **Önemli:** Bu sistemde gerçek hasta verisi yoktur ve olmamalıdır. E-postalar
> `@example.test`, telefonlar `TEST_PHONE_000001` gibidir. API'lerde kimlik
> doğrulama yoktur; yalnızca kendi bilgisayarınızda kullanın.

---

## 1. Bu makinede yapılan ortam tespiti

Kurulum sırasında bulunanlar (sizin makinenizde de benzer olabilir):

| Bileşen | Durum |
|---|---|
| Python | 3.12.5 (`python --version`) |
| SQL Server Express (`.\SQLEXPRESS`) | **Kurulu değil** (servis yok) |
| SQL Server LocalDB (`(localdb)\MSSQLLocalDB`) | **Kurulu ve çalışıyor** |
| ODBC Driver 18 | **Kurulu değil** |
| ODBC Driver 17 for SQL Server | **Kurulu** |
| SSMS | Kurulu değil (zorunlu değil) |

Bu nedenle proje bu makinede **LocalDB + ODBC Driver 17** ile gerçek MSSQL
bağlantısı kurularak test edildi. `.\SQLEXPRESS` kurulduğunda yalnızca `.env`
dosyasındaki `DB_SERVER` ve `DB_DRIVER` değerlerini değiştirmeniz yeterlidir.

### SQL Server Express kurmak isterseniz (isteğe bağlı)

1. Microsoft'un resmî sayfasından **SQL Server 2022 Express** indirin.
2. Kurulumda **Basic** seçeneğini seçin; örnek adı `SQLEXPRESS` olsun.
3. Kurulumdan sonra `services.msc` → `SQL Server (SQLEXPRESS)` servisinin
   **Running** olduğunu kontrol edin.
4. ODBC sürücüsü için **Microsoft ODBC Driver 18 for SQL Server** kurun.
5. İsteğe bağlı: **SQL Server Management Studio (SSMS)** kurun.
6. `.env` içinde:
   ```
   DB_SERVER=.\SQLEXPRESS
   DB_DRIVER=ODBC Driver 18 for SQL Server
   ```
7. Doğrulayın:
   ```powershell
   .\.venv\Scripts\python.exe scripts\init_db.py --check-only
   ```

Kurulum yönetici izni isterse bu adımı sizin yapmanız gerekir; proje geri
kalanıyla yönetici izni olmadan çalışır.

---

## 2. Her araç ne işe yarıyor?

| Araç | Görevi (basit anlatım) |
|---|---|
| **Python** | Bütün işleri yapan programlama dili. |
| **FastAPI** | "API" yani programlar arası konuşma kapısı kurar. |
| **Uvicorn** | FastAPI uygulamasını gerçekten dinleyen web sunucusu. |
| **SQLAlchemy** | Python nesneleri ile veritabanı tabloları arasında tercüman. |
| **pyodbc** | Python'un MSSQL'e konuşmasını sağlayan köprü. |
| **ODBC Driver** | Windows'un SQL Server ile konuşma sürücüsü. |
| **httpx** | Python'un başka API'lere istek atmasını sağlar. |
| **Faker** | Sahte isim/veri üretir. |
| **python-dotenv** | Ayarları `.env` dosyasından okur. |
| **pytest** | Testleri otomatik çalıştırır. |
| **MSSQL** | Verilerin kalıcı olarak saklandığı veritabanı. |

### Kavramlar

- **API**: Bir programın başka bir programa "şu veriyi ver" dediği kapı.
  Adres + yol + HTTP metodu ile çalışır: `GET /api/v1/patients`.
- **Port**: Aynı bilgisayarda farklı programların farklı kapıları.
  Kaynak API `8001`, hedef API `8000`.
- **JSON**: API'lerin veri alışverişi formatı.
- **UTC**: Ortak saat dilimi. Projede bütün tarihler UTC saklanır ve
  `2026-10-24T09:30:00Z` biçiminde gösterilir (sondaki `Z` = UTC).
- **Upsert**: Kayıt varsa güncelle, yoksa ekle. Tekrar çalıştırma mükerrer
  kayıt üretmez.
- **Checkpoint**: "Şu zamana kadar olan veriler aktarıldı" işareti
  (`SyncState` tablosu).
- **Soft delete**: Kaydı silmek yerine `IsDeleted = 1` yapmak. Böylece
  silme bilgisi de senkronize edilebilir.

---

## 3. Klasör yapısı

```
MssqlPythonSync/
├── app/
│   ├── main.py              # Hedef API (port 8000) + /dashboard
│   ├── config.py            # .env okuma, bağlantı dizesi, CORS
│   ├── db.py                # SQLAlchemy motoru / oturum
│   ├── models.py            # Tablo karşılıkları (ORM)
│   ├── schemas.py           # Hedef API çıktı şemaları
│   ├── source_schemas.py    # Kaynak API cevap doğrulaması
│   ├── sync_engine.py       # Senkronizasyon motoru (retry + upsert)
│   ├── logging_setup.py     # Konsol + dosya log
│   ├── static/
│   │   └── dashboard.html   # Canlı analitik paneli (CDN'siz)
│   └── routers/             # clinics, patients, appointments, sync, analytics
├── mock_source/
│   ├── main.py              # Kaynak API (port 8001)
│   └── storage.py           # Kilitli, atomik JSON deposu
├── scripts/
│   ├── generate_synthetic_data.py
│   ├── init_db.py
│   ├── sync_api_to_mssql.py
│   ├── run_source_api.ps1
│   ├── run_target_api.ps1
│   ├── run_sync.ps1
│   ├── register_sync_task.ps1
│   └── unregister_sync_task.ps1
├── data/synthetic_source.json   # Üretilen sentetik veri
├── sql/create_tables.sql        # Şema (yıkıcı değil)
├── tests/                       # pytest testleri
├── logs/                        # sync.log, api.log, init_db.log
├── .env                         # Bu makineye özel ayarlar (git'e girmez)
├── .env.example                 # Örnek ayarlar
├── requirements.txt
└── README.md
```

---

## 4. Kurulum (sırayla)

Aşağıdaki komutlar **PowerShell** içinde ve **proje klasöründe** çalıştırılır:

```powershell
cd C:\Users\realb\Desktop\veri_canli\MssqlPythonSync
```

### 4.1 Sanal ortam

Sanal ortam, projenin paketlerini bilgisayarın geri kalanından ayırır.

```powershell
python -m venv .venv
```

Etkinleştirme (her yeni terminalde gerekir):

```powershell
.\.venv\Scripts\Activate.ps1
```

PowerShell "script çalıştırma devre dışı" derse, o terminal için:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

> İsterseniz etkinleştirmeden de `.\.venv\Scripts\python.exe ...` şeklinde
> çalıştırabilirsiniz. Bu README'deki komutlar bu yolu kullanır.

### 4.2 Paketler

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Beklenen: `Successfully installed ...` satırları.

### 4.3 Ayarlar

`.env.example` dosyasını kopyalayıp `.env` oluşturun:

```powershell
Copy-Item .env.example .env
```

Bu makinede hazır `.env` dosyası şu değerlerle oluşturuldu:

```
DB_SERVER=(localdb)\MSSQLLocalDB
DB_DATABASE=DentSyncDemo
DB_DRIVER=ODBC Driver 17 for SQL Server
DB_TRUSTED_CONNECTION=true
DB_ENCRYPT=false
DB_TRUST_SERVER_CERTIFICATE=true
```

`.env` **asla** paylaşılmaz ve `.gitignore` ile hariç tutulur. Parola
kullanmıyorsanız (Windows Authentication) parola alanı boş kalır.

**Şifreleme hakkında:** `DB_ENCRYPT=true` üretimde beklenen ayardır. Ancak
eski ODBC sürücüsü + LocalDB kombinasyonunda "Encryption not supported on SQL
Server" hatası alınabilir; bu durumda **yalnızca yerel geliştirmede**
`DB_ENCRYPT=false` kullanılır. `TrustServerCertificate=true` yalnızca yerel
self-signed sertifika içindir; üretimde sertifika doğrulanmalıdır.

---

## 5. Sentetik veri

### 5.1 İlk üretim

```powershell
.\.venv\Scripts\python.exe scripts\generate_synthetic_data.py
```

Beklenen çıktı:

```
Sentetik veri olusturuldu: ...\data\synthetic_source.json
  3 klinik, 500 hasta, 2000 randevu (seed=42)
Dogrulama: BASARILI
```

Varsayılanlar: 3 klinik, 500 hasta, 2.000 randevu, `seed=42`.
Aynı `seed` + aynı `--as-of` tarihi aynı veriyi üretir (tekrarlanabilir test).

### 5.2 Yeniden üretim (dikkat)

Dosya zaten varsa üretici **üzerine yazmaz** ve hata verir:

```
HATA: Dosya zaten var: ...\synthetic_source.json. Uzerine yazmak icin --force kullanin.
```

Bilinçli olarak yeniden üretmek için:

```powershell
.\.venv\Scripts\python.exe scripts\generate_synthetic_data.py --force
```

Bu durumda önceki dosya `data/backups/` altına zaman damgalı olarak yedeklenir.
Hiçbir dosya sessizce silinmez.

### 5.3 Farklı boyut / doğrulama

```powershell
.\.venv\Scripts\python.exe scripts\generate_synthetic_data.py --patients 50 --appointments 200 --force
.\.venv\Scripts\python.exe scripts\generate_synthetic_data.py --validate-only
```

`--validate-only` şunları kontrol eder: hasta/klinik referansları, e-posta ve
telefonların sentetikliği, tarih tutarlılığı, durum değerleri, geçmiş/bugün/
gelecek randevu varlığı.

---

## 6. MSSQL veritabanı ve şema

### 6.1 Kurulum

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py
```

Bu komut:
1. `DentSyncDemo` veritabanı yoksa oluşturur (varsa dokunmaz).
2. `sql/create_tables.sql` dosyasını uygular; yalnızca **eksik** tablo ve
   indeksleri oluşturur.
3. Tabloları ve satır sayılarını raporlar.

Yalnızca kontrol:

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py --check-only
```

Farklı sunucu için (`.env` değiştirmeden):

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py --server ".\SQLEXPRESS" --driver "ODBC Driver 18 for SQL Server"
```

### 6.2 Tablolar

| Tablo | Amaç |
|---|---|
| `Clinics` | Klinikler (`ExternalClinicId` tekil) |
| `Patients` | Hastalar (`ExternalPatientId` tekil, kliniğe FK) |
| `Appointments` | Randevular (hasta + kliniğe FK, durum CHECK kısıtı) |
| `SyncState` | Her veri türü için son başarılı checkpoint |
| `SyncLog` | Her senkronizasyon turunun geçmişi |

Kurallar:
- Birincil anahtarlar `IDENTITY`.
- Dış kimliklerde **benzersiz indeks/kısıt** (tekrar aktarımda mükerrer yok).
- `datetime2(3)` tarihler, **UTC**.
- `IsDeleted` ile soft delete.
- `Appointments.Status` yalnızca `Scheduled, Confirmed, Completed, Cancelled`.
- `EndDateTime > AppointmentDateTime` kontrolü.

### 6.3 SSMS ile kontrol

SSMS'te `(localdb)\MSSQLLocalDB` (veya `.\SQLEXPRESS`) sunucusuna
**Windows Authentication** ile bağlanın, `DentSyncDemo` veritabanında:

```sql
SELECT COUNT(*) FROM dbo.Clinics;        -- 3
SELECT COUNT(*) FROM dbo.Patients;       -- 500
SELECT COUNT(*) FROM dbo.Appointments;   -- 2000
SELECT TOP (5) * FROM dbo.SyncLog ORDER BY SyncLogId DESC;
SELECT * FROM dbo.SyncState;
```

`sql/create_tables.sql` dosyasını SSMS'te doğrudan da çalıştırabilirsiniz;
betik yıkıcı değildir.

---

## 7. Kaynak API (port 8001)

Ayrı bir PowerShell penceresinde:

```powershell
.\.venv\Scripts\python.exe -m uvicorn mock_source.main:app --host 127.0.0.1 --port 8001
```

veya:

```powershell
.\scripts\run_source_api.ps1
```

Açılacak adresler:
- Dokümantasyon: <http://127.0.0.1:8001/docs>
- Sağlık: <http://127.0.0.1:8001/health>
- Özet: <http://127.0.0.1:8001/source/stats>

### Uç noktalar

| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/health` | API ve veri dosyası durumu |
| GET | `/source/stats` | Kayıt ve durum özeti |
| GET | `/source/clinics` | Klinikler |
| GET | `/source/patients` | Hastalar |
| GET | `/source/appointments` | Randevular |
| GET | `/source/appointments/{id}` | Tek randevu |
| POST | `/source/appointments` | Yeni randevu |
| PATCH | `/source/appointments/{id}` | Randevu güncelle |
| POST | `/source/appointments/{id}/cancel` | İptal et |
| DELETE | `/source/appointments/{id}` | Soft delete (`IsDeleted=true`) |

Liste uç noktaları: `limit` (1–500), `offset`, `updated_since` (ISO-8601 UTC),
`include_deleted`, ayrıca `clinic_id` / `patient_id`.

Sıralama deterministiktir: `(UpdatedAt, dış kimlik)`.

### Elle deneme

```powershell
# Sağlık
Invoke-RestMethod http://127.0.0.1:8001/health

# İlk 5 randevu
Invoke-RestMethod "http://127.0.0.1:8001/source/appointments?limit=5"

# Randevu iptali
Invoke-RestMethod -Method Post http://127.0.0.1:8001/source/appointments/APT-000002/cancel

# Soft delete
Invoke-WebRequest -Method Delete http://127.0.0.1:8001/source/appointments/APT-000003
```

Veri dosyası yoksa API uydurma veri döndürmez; `503` ve
"önce generate_synthetic_data.py çalıştırın" mesajı verir.

---

## 8. Senkronizasyon

Kaynak API çalışırken, başka bir terminalde:

```powershell
.\.venv\Scripts\python.exe scripts\sync_api_to_mssql.py
```

veya `.\scripts\run_sync.ps1`.

Beklenen çıktı (ilk çalıştırma):

```
==============================================================
Senkronizasyon job_id: ...
Durum               : BASARILI
--------------------------------------------------------------
Tur             Okunan  Eklenen  Guncel  Silinen  Hata
clinics              3        3       0        0     0
patients           500      500       0        0     0
appointments      2000     2000       0        0     0
==============================================================
```

İkinci çalıştırma **mükerrer kayıt oluşturmaz**; genellikle `0` okunan veya
yalnızca örtüşme penceresindeki kayıtlar görünür.

### Seçenekler

```powershell
# Belirli türler
.\.venv\Scripts\python.exe scripts\sync_api_to_mssql.py --entities clinics,patients

# Checkpoint'i yok say, tüm veriyi çek (upsert güvenli)
.\.venv\Scripts\python.exe scripts\sync_api_to_mssql.py --full

# Farklı kaynak adresi
.\.venv\Scripts\python.exe scripts\sync_api_to_mssql.py --source-url http://127.0.0.1:8001
```

### Nasıl çalışır?

1. `clinics → patients → appointments` sırasıyla çalışır (FK güvenliği).
2. `SyncState`'teki son checkpoint'ten itibaren, **120 saniyelik örtüşme**
   penceresiyle veri çeker (zaman sınırında kayıt kaçmaz).
3. Her sayfa tek transaction'da upsert edilir.
4. Bir türün **tüm sayfaları** başarılı olursa checkpoint ilerler.
5. Hata olursa `SyncLog` → `Failed`; checkpoint ilerlemez; sonraki çalışma
   aynı veriyi yeniden işler.
6. 429/5xx/timeout için sınırlı retry + artan bekleme (varsayılan 4 deneme).
7. Aynı anda ikinci çalışmayı `logs/sync.lock` engeller.

### Çıkış kodları

| Kod | Anlamı |
|---|---|
| 0 | Başarılı |
| 1 | Senkronizasyon hatası (`SyncLog` = Failed) |
| 2 | Yapılandırma / MSSQL bağlantı hatası |
| 3 | Başka bir senkronizasyon çalışıyor (kilit) |

---

## 9. Hedef API (port 8000)

Ayrı bir PowerShell penceresinde:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

veya `.\scripts\run_target_api.ps1`.

Açılacak adresler:
- Dokümantasyon: <http://127.0.0.1:8000/docs>
- **Canlı panel: <http://127.0.0.1:8000/dashboard>**
- Sağlık (MSSQL dahil): <http://127.0.0.1:8000/health>

### Uç noktalar

| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/health` | API + MSSQL bağlantı kontrolü |
| GET | `/api/v1/clinics` | Klinikler |
| GET | `/api/v1/patients` | Hastalar |
| GET | `/api/v1/appointments` | Randevular |
| GET | `/api/v1/appointments/{external_id}` | Tek randevu |
| PATCH | `/api/v1/appointments/{external_id}/status` | Durum güncelle |
| GET | `/api/v1/sync/status` | Son senkronizasyon durumu |
| GET | `/api/v1/sync/logs` | Senkronizasyon geçmişi |
| POST | `/api/v1/sync/run` | Senkronizasyonu çalıştır (dashboard) |
| GET | `/api/v1/analytics/summary` | Dashboard özeti (MSSQL agregasyonu) |
| GET | `/dashboard` | Canlı analitik paneli |

Liste parametreleri: `limit` (1–200), `offset`, `include_deleted`;
randevularda ek olarak `status`, `date_from`, `date_to`, `clinic_id`,
`patient_id`.

### Elle deneme

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/appointments?limit=5&status=Confirmed"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/appointments/APT-000001"

# Durum güncelle
Invoke-RestMethod -Method Patch `
  -Uri "http://127.0.0.1:8000/api/v1/appointments/APT-000001/status" `
  -ContentType "application/json" `
  -Body '{"status":"Confirmed"}'
```

Geçersiz durum → `422`; olmayan kayıt → `404`; silinmiş kayıt → `409`.

> Not: Hedef API üzerinden yapılan durum değişikliği MSSQL'de kalıcıdır ve
> `SyncLog`'a `api_status_update` olarak yazılır. Kaynak sistem aynı kaydı
> tekrar gönderirse **kaynak değeri kazanır** (kaynak sistem doğruluk
> kaynağıdır). Bu davranış bilinçli bir tasarım tercihidir.

---

## 10. Testler

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Beklenen: `63 passed`.

- `test_synthetic_data.py` — üretim, tekrarlanabilirlik, referans bütünlüğü,
  sentetik iletişim verisi, üzerine yazma koruması.
- `test_source_api.py` — JSON biçimi, sayfalama boşluksuzluğu, filtreler,
  oluşturma/güncelleme/iptal/silme, hata kodları.
- `test_sync.py` — ilk aktarım, tekrar aktarımda mükerrer olmaması, güncellenen
  ve iptal edilen kayıt, soft delete, retry, doğrulama hatası, başarısız işin
  `Failed` yazılması, checkpoint'in erken ilerlememesi, sonraki çalışmada
  toparlanma.
- `test_destination_api.py` — API'nin gerçekten MSSQL'den okuduğu, filtreler,
  durum güncellemesi, 404/422, sync uç noktaları, **dashboard analitik özeti**,
  CORS, panelin sunulması ve senkronizasyon tetikleme kuralları.

MSSQL entegrasyon testleri **ayrı** `DentSyncTest` veritabanını kullanır ve
yalnızca o veritabanındaki tabloları temizler. `DentSyncDemo` verinize
dokunmaz. SQL Server bulunamazsa bu testler otomatik **skip** olur; saf Python
testleri yine çalışır.

---

## 11. Canlı analitik paneli (dashboard)

Panel, hedef API tarafından sunulur; ayrı bir web sunucusu veya internet
bağlantısı gerekmez (CDN yok, tüm stil ve grafikler yerel).

```
http://127.0.0.1:8000/dashboard
```

Hedef API çalışmıyorsa tarayıcıda `http://127.0.0.1:8000/dashboard` açılmaz.
Bu durumda önce:

```powershell
.\scripts\run_target_api.ps1
```

Panelin gösterdiği her sayı **MSSQL'den** gelir:

| Bölüm | Kaynak |
|---|---|
| Toplam klinik / hasta / randevu | `Clinics`, `Patients`, `Appointments` (silinmemiş) |
| Randevu durum dağılımı | `Appointments.Status` gruplaması |
| Hasta kayıt trendi | `Patients.CreatedAt` ay bazında |
| Klinik hasta hacmi | Klinik başına hasta ve randevu sayısı |
| Senkronizasyon başarısı | `SyncLog` (yalnızca `operation_type='sync'`) |
| Gecikme (lag) | `SyncState.LastSuccessfulRunAt` |
| Canlı akış | Son `SyncLog` kayıtları |
| Bugün / 7 gün / geçmiş | `AppointmentDateTime` karşılaştırmaları |

- Veri yoksa panel **sahte sayı üretmez**; `—` gösterir ve nedenini yazar.
- Hedef API kapalıysa kırmızı uyarı görünür, grafikler boş kalır.
- Kaynak API kapalıysa hedef API verisi yine gösterilir; yalnızca senkronizasyon
  çalıştırılamaz.
- `Yenile` düğmesi ve 10 saniyelik otomatik yenileme vardır; `Canlı akış`
  düğmesiyle kapatılabilir.

### Panelden uçtan uca deneme

Sayfanın altındaki panelde bir randevu seçip:

1. **Kaynakta iptal et** → kaynak API'de (`:8001`) randevu iptal edilir,
   ardından senkronizasyon otomatik çalışır, hedef API yeni durumu gösterir.
2. **Kaynakta işlem türünü değiştir** → `PATCH` ile işlem türü değişir ve
   senkronize edilir.
3. **Senkronize et** → yalnızca senkronizasyonu çalıştırır.
4. **Hedef API'de Confirmed yap** → `PATCH /api/v1/appointments/{id}/status`
   ile MSSQL'deki durumu değiştirir (kaynak sistem sonra tekrar gönderirse
   kaynak değeri kazanır).

Panelden senkronizasyon tetikleme varsayılan olarak **açıktır** (`.env`:
`ENABLE_SYNC_TRIGGER=true`). Kapatmak isterseniz `false` yapıp hedef API'yi
yeniden başlatın; panel `403` alır ve size terminal komutunu gösterir. Kapalı
olması veri kaybına yol açmaz, yalnızca panelden tetiklemeyi engeller.

### Panelin kullandığı yeni uç noktalar

| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/dashboard` | Paneli sunar |
| GET | `/api/v1/analytics/summary?months=6` | Tüm özet (tek istek) |
| POST | `/api/v1/sync/run` | Senkronizasyonu tetikler (`ENABLE_SYNC_TRIGGER` gerekir) |

Örnek:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/analytics/summary?months=12"
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/v1/sync/run"
```

### CORS

Tarayıcı, panelden API'lere istek attığı için CORS gerekir. Varsayılan olarak
yalnızca **loopback** adresleri (`127.0.0.1`, `localhost`, herhangi bir port)
izinlidir. `.env` içinde daraltabilirsiniz:

```
CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
CORS_ORIGIN_REGEX=^https?://(localhost|127\.0\.0\.1)(:\d+)?$
```

İnternete açık bir ortamda `CORS_ORIGIN_REGEX` boşaltılmalı ve yalnızca
bilinen kaynaklar `CORS_ORIGINS` içinde bırakılmalıdır.

### Panel ile ilgili notlar

- Panel, orijinal HTML tasarımındaki **sahte veri üreten** "Simulate Live Feed"
  davranışını içermez. Amaç, sistemin görünürlüğünü **gerçek** veriyle
  göstermektir; uydurma sayı üretilmez.
- Grafikler harici `Chart.js` yerine satır içi SVG ile çizilir; böylece
  çevrimdışı da çalışır.
- Tasarım koyu tema, duyarlı (mobil/tablet/masaüstü) ve Türkçedir.

---

## 12. Windows Task Scheduler ile otomasyon

Kaynak API ve MSSQL çalışır durumda olmalıdır. Görev, senkronizasyonu her
5 dakikada bir çalıştırır. **Yönetici izni gerekmez**; görev sizin
kullanıcınız için oluşturulur.

```powershell
# 5 dakikada bir, hemen bir kez de çalıştır
.\scripts\register_sync_task.ps1 -IntervalMinutes 5 -RunNow

# 10 dakikada bir
.\scripts\register_sync_task.ps1 -IntervalMinutes 10
```

Kontrol:

```powershell
schtasks /Query /TN "DentSync - API to MSSQL" /V /FO LIST
```

Kaldırma:

```powershell
.\scripts\unregister_sync_task.ps1
```

Görev yalnızca oturum açıkken çalışır. Bilgisayar uykuya girerse çalışmaz.

### Senaryolar

| Durum | Ne olur? |
|---|---|
| **Kaynak API kapalı** | Bağlantı hatası, sınırlı retry, `SyncLog` = `Failed`, çıkış kodu 1. Checkpoint ilerlemez. API açılınca sonraki çalışma tüm bekleyen veriyi alır. |
| **MSSQL erişilemez** | Çıkış kodu 2, logda açık bağlantı hatası. Hiçbir veri "başarılı" yazılmaz. |
| **Önceki çalışma bitmedi** | `logs/sync.lock` nedeniyle yeni çalışma başlamaz (çıkış kodu 3). Kilit 1 saatten eskiyse otomatik devralınır. |
| **Aktarım yarıda kaldı** | O türün checkpoint'i ilerlemez; sayfa transaction'ları geri alınır; sonraki çalışma aynı veriyi yeniden işler (upsert güvenli). |
| **Loglar nerede?** | `logs\sync.log`, `logs\api.log`, `logs\init_db.log`; ayrıca MSSQL'de `dbo.SyncLog`. |

---

## 13. Sistemi durdurma

1. API pencerelerinde `Ctrl + C`.
2. Zamanlanmış görev varsa: `.\scripts\unregister_sync_task.ps1`.
3. Veritabanını silmek istemiyorsanız hiçbir şey yapmayın; durdurmak veriyi
   silmez.
4. Takılı kalmış kilit varsa ve çalışan işlem yoksa: `logs\sync.lock` dosyasını
   silebilirsiniz.

---

## 14. Sık karşılaşılan hatalar

| Hata | Neden / Çözüm |
|---|---|
| `Encryption not supported on SQL Server` | Eski sürücü + şifreleme. Yerelde `DB_ENCRYPT=false`; ya da ODBC Driver 18 kurun. |
| `Login failed` / `Cannot open database` | `DB_SERVER`, veritabanı adı veya Windows Authentication izni. `init_db.py` çalıştırın. |
| `ODBC surucusu bulunamadi` | `.env` içindeki `DB_DRIVER` kurulu değil. ODBC Driver 17/18 kurun veya adı düzeltin. |
| `Sentetik veri dosyasi bulunamadi` | `python scripts/generate_synthetic_data.py` çalıştırın. |
| `Baska bir senkronizasyon calisiyor` | `logs/sync.lock`; çalışan işlem yoksa dosyayı silin. |
| `Port 8000/8001 kullanimda` | Aynı portta başka süreç var. O süreci kapatın veya `--port` değiştirin. |
| `Hasta kayitlari icin klinik bulunamadi` | Kaynak veri tutarsız; `--validate-only` ile kontrol edin, gerekirse `--force` ile yeniden üretin. |
| Testlerde `skipped` (MSSQL) | SQL Server kapalı ya da ODBC sürücüsü yok. Bağlantıyı düzeltip tekrar çalıştırın. |

---

## 15. Güvenlik ve üretime geçiş

Bu proje **yerel geliştirme/demo** içindir.

- API'lerde kimlik doğrulama, yetkilendirme ve hız sınırı **yoktur**.
  `127.0.0.1` dışına açmayın.
- `.env` sır içerir; git'e eklemeyin (`.gitignore` hazır).
- Loglarda parola/bağlantı sırrı yazılmaz; hata özetlerinde parola maskelenir.
- SQL sorguları SQLAlchemy üzerinden parametrelidir.
- Yalnızca sentetik veri kullanılır; gerçek kişisel/ sağlık verisi girmeyin.
- Üretimde: `DB_ENCRYPT=true`, geçerli sertifika (`TrustServerCertificate=false`),
  en az yetkili veritabanı kullanıcısı, API'lerde OAuth2/API key + TLS,
  hız sınırı, ağ segmentasyonu, merkezi log ve yedekleme gerekir.
- Windows Authentication yerine üretimde ayrı bir servis hesabı ve
  yönetilen sır saklama (ör. Windows Credential Manager, Azure Key Vault)
  kullanılmalıdır.

---

## 16. Uçtan uca hızlı başlangıç (özet)

Üç ayrı PowerShell penceresi:

**Pencere 1 — Kaynak API**
```powershell
cd C:\Users\realb\Desktop\veri_canli\MssqlPythonSync
.\scripts\run_source_api.ps1
```

**Pencere 2 — Hedef API**
```powershell
cd C:\Users\realb\Desktop\veri_canli\MssqlPythonSync
.\scripts\run_target_api.ps1
```

**Pencere 3 — Kurulum ve senkronizasyon**
```powershell
cd C:\Users\realb\Desktop\veri_canli\MssqlPythonSync
.\.venv\Scripts\python.exe scripts\init_db.py
.\.venv\Scripts\python.exe scripts\sync_api_to_mssql.py
```

Sonra tarayıcıda:
- <http://127.0.0.1:8001/docs> — kaynak API
- <http://127.0.0.1:8000/docs> — hedef API
- **<http://127.0.0.1:8000/dashboard> — canlı analitik paneli**
- <http://127.0.0.1:8000/health> — MSSQL bağlantısı dahil sağlık
- <http://127.0.0.1:8000/api/v1/appointments?limit=5> — MSSQL'den gelen veri

Değişiklik senaryosunu denemek için:

```powershell
# 1) Kaynakta değiştir
Invoke-RestMethod -Method Patch `
  -Uri "http://127.0.0.1:8001/source/appointments/APT-000001" `
  -ContentType "application/json" `
  -Body '{"procedure_type":"Dolgu"}'

# 2) Senkronize et
.\.venv\Scripts\python.exe scripts\sync_api_to_mssql.py

# 3) Hedef API'den doğrula
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/appointments/APT-000001"
```
