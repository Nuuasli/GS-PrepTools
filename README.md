# 🎥 GS-Prep — Gaussian Splatting & 3D Reconstruction Dataset Preparation Tool

<p align="center">
  <b>Pipeline Preprocessing Otomatis untuk 3D Reconstruction, COLMAP, Gaussian Splatting (3DGS), dan NeRF.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js" alt="Next.js">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/OpenCV-4.11-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white" alt="OpenCV">
  <img src="https://img.shields.io/badge/Tailwind_CSS-4-38B2AC?style=for-the-badge&logo=tailwind-css" alt="Tailwind CSS">
</p>

---

## 📌 Deskripsi

**GS-Prep** adalah standalone preprocessing utility yang mengubah rekaman video mentah menjadi kumpulan foto yang lebih bersih dan terkurasi. Dataset hasilnya dapat dipindahkan secara manual ke project rekonstruksi atau training yang terpisah.

Proses penyeleksian frame dilakukan otomatis. Frame intermediate dapat dipertahankan melalui mode audit (`Keep Intermediates`), sedangkan mode normal membersihkannya setelah export untuk menghemat storage.

### Batas Scope

Pipeline project ini berhenti pada `VIDEO → CURATED PHOTOS → EXPORT`. GS-Prep tidak menyertakan atau menjalankan `convert.py`, COLMAP, camera pose estimation, point-cloud reconstruction, image undistortion, maupun training 3DGS/NeRF.

---

## ✨ Fitur Utama

- 🎞️ **Frame Extraction Presisi**: Ekstraksi frame otomatis berdasarkan FPS yang dapat disesuaikan (default: 2 FPS) dengan pengontrolan kualitas JPEG.
- 🔍 **Blur Detection (Variance of Laplacian)**: Mendeteksi dan menyaring gambar yang blur/buram secara otomatis agar hasil rekonstruksi 3D lebih tajam.
- ♊ **Duplicate Removal (ORB Feature Matching / SSIM)**: Membandingkan pasangan frame untuk menghapus foto yang terlalu identik, menghemat waktu training secara signifikan.
- 📐 **Resize Presets**: Pengecilan ukuran gambar ke satu resolusi pilihan (1080p, 720p, 480p, atau Original).
- 📂 **Nama Folder Otomatis**: Folder dataset hasil ekstraksi otomatis disesuaikan dengan nama file video yang diunggah (`{video_name}/processed/`).
- 📄 **Laporan PDF Report Auto-Generated**: Rekapitulasi statistik pemrosesan yang rapi dan siap diunduh dalam format PDF.
- 📊 **Per-Frame Manifest**: Setiap hasil dilengkapi CSV audit berisi posisi frame sumber, blur score, similarity score, frame pembanding, status, dan alasan penolakan.
- 🎨 **UI Modern & Animated**: Tampilan berestetika tinggi dengan *dark mode*, *glassmorphism*, indikator persentase real-time, dan animasi task feed.

---

## 🔄 Alur Pemrosesan (Pipeline Workflow)

```
 ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
 │ Upload Video │ ───► │   Extract    │ ───► │ Blur Filter  │
 └──────────────┘      │   Frames     │      │ (Laplacian)  │
                       └──────────────┘      └──────────────┘
                                                    │
 ┌──────────────┐      ┌──────────────┐             ▼
 │ ZIP/PDF/CSV  │ ◄─── │    Resize    │ ◄─── ┌──────────────┐
 │    Export    │      │  Resizing    │      │  Duplicate   │
 └──────────────┘      └──────────────┘      │   Filter     │
                                             └──────────────┘
```

---

## 🛠️ Teknologi yang Digunakan

### Frontend
- **Framework**: Next.js 16 (App Router) + React 19
- **State Management**: Zustand
- **Data Fetching**: TanStack Query (React Query v5)
- **Styling**: Tailwind CSS + Glassmorphism Aesthetic
- **Icons**: Lucide React

### Backend
- **Framework**: FastAPI (Python 3.11+)
- **Computer Vision**: OpenCV (`cv2`), Scikit-Image, SciPy
- **PDF Generation**: ReportLab
- **Server**: Uvicorn

---

## 🚀 Panduan Memulai (Quick Start)

### Prasyarat
- **Node.js**: v18.0.0 atau lebih baru
- **Python**: v3.11 atau lebih baru
- **FFmpeg**: Terinstal pada sistem

---

### 1. Menjalankan Backend (FastAPI)

```cmd
# Pindah ke direktori backend
cd backend

# Buat & aktifkan Virtual Environment (Windows)
python -m venv .venv
.venv\Scripts\activate

# Install dependensi
pip install -r requirements.txt

# Jalankan server FastAPI
.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

> 🌐 **Backend API Swagger Docs**: `http://localhost:8000/docs`

---

### 2. Menjalankan Frontend (Next.js)

```cmd
# Pindah ke direktori frontend
cd frontend

# Install paket node
npm install

# Menjalankan mode pengembangan
npm run dev
```

> 🌐 **Aplikasi Web GS-Prep**: `http://localhost:3000`

---

## ⚙️ Parameter Konfigurasi

| Parameter | Default | Rekomendasi Penggunaan |
| :--- | :---: | :--- |
| **Extraction FPS** | `2` | **1-2 FPS** untuk rekaman pelan, **3-5 FPS** untuk rekaman cepat |
| **JPEG Quality** | `100` | Kualitas JPEG maksimum |
| **Blur Threshold** | `10.0` | Naikkan jika ingin penyaringan blur lebih selektif |
| **Duplicate Threshold** | `0.5` | Naikkan jika hanya ingin membuang frame yang lebih mirip |
| **Resize Width** | `0` | Mempertahankan resolusi asli |
| **Keep Intermediates** | `true` | Menyimpan frame extracted, blur, dan duplicate untuk kebutuhan audit; membutuhkan storage lebih besar |

Job metadata disimpan sebagai JSON kecil agar status dan hasil tetap dapat dipulihkan setelah restart. Secara default, video asli dan folder intermediate dihapus setelah ZIP, PDF, manifest CSV, dan preview berhasil dibuat. Job selesai kedaluwarsa setelah 24 jam dan dibersihkan otomatis.

Maximum upload size adalah **3072 MB (~3 GB)**, dikendalikan oleh
`GSPREP_MAX_UPLOAD_SIZE_MB`. Backend menerima upload secara streaming dalam
chunk 1 MB dan menulisnya langsung ke disk, sehingga file multi-GB tidak dibaca
seluruhnya ke RAM aplikasi sekaligus.

### Manifest Per-Frame

Setiap completed job menghasilkan `{video_name}_manifest.csv` yang dapat diunduh terpisah dan juga disertakan sebagai `{video_name}/manifest.csv` di dalam ZIP dataset. Manifest tetap tersedia meskipun `Keep Intermediates` tidak diaktifkan.

Struktur ZIP dataset:

```text
{video_name}/
|-- images/
|   |-- IMG_000001.jpg
|   `-- ...
|-- metadata.pdf
`-- manifest.csv
```

`metadata.pdf` berisi metadata video dan ringkasan hasil pemrosesan yang sama
dengan PDF report yang tersedia melalui tombol download terpisah.

| Field | Arti |
| :--- | :--- |
| `filename` | Nama JPEG hasil ekstraksi |
| `source_frame_index` | Indeks frame yang benar-benar dibaca dari video sumber |
| `source_timestamp` | Posisi frame sumber dalam detik (`source_frame_index / video_fps`) |
| `blur_score` | Variance of Laplacian yang dipakai blur detector |
| `similarity_score` | Nilai ORB atau SSIM yang dipakai duplicate detector; kosong jika tidak dibandingkan |
| `duplicate_method` | `ORB` atau `SSIM` untuk frame yang masuk duplicate detection |
| `compared_with` | Frame referensi yang benar-benar digunakan; kosong untuk referensi pertama |
| `status` | `accepted` atau `rejected` |
| `rejection_reason` | `blur`, `duplicate`, atau kosong untuk frame yang diterima |

### Metadata Video

Upload menggunakan FFprobe sebagai sumber metadata utama dan OpenCV sebagai
cross-check/fallback. Probe utama hanya membaca header agar video besar tidak
perlu didekode seluruhnya. Jumlah frame dari header digunakan bila tersedia;
penghitungan frame penuh dijalankan terpisah hanya saat diperlukan, sehingga
timeout penghitungan tidak membuang metadata teknis lain. Selain durasi, FPS,
frame count, resolusi, dan codec,
respons API menyertakan container, bitrate, pixel format, aspect ratio,
rotation, color metadata, ringkasan audio, sumber frame count, warning, serta
SHA-256 file. FFprobe menghitung frame ketika informasi header tidak cukup.

Jika FFprobe tidak tersedia, aplikasi tetap menerima video yang dapat dibaca
OpenCV, tetapi `metadata_source` menjadi `opencv_fallback` dan warning dikirim ke
frontend. Pastikan `ffprobe` tersedia di `PATH` untuk hasil paling lengkap.
Deployment Docker sudah memasang FFmpeg. Binary dan timeout dapat dikonfigurasi
melalui `GSPREP_FFPROBE_BINARY` dan `GSPREP_FFPROBE_TIMEOUT_SECONDS`.

---

## 📁 Struktur Direktori Monorepo

```
dataprep4gs/
├── frontend/                  # Next.js Application
│   ├── app/                   # App Router (/, /processing, /result)
│   ├── components/            # UI Components & Providers
│   ├── hooks/                 # Zustand Store (usePipelineStore)
│   ├── services/              # API Client (Fetch & Upload)
│   └── types/                 # TypeScript Interfaces
│
└── backend/                   # FastAPI Backend
    ├── app/
    │   ├── api/v1/            # API Endpoints (upload, pipeline, health)
    │   ├── core/              # Config, Logging, Exceptions
    │   ├── models/            # Pydantic Schemas
    │   ├── modules/           # Frame Extractor, Blur, Duplicate, Resize, Report
    │   └── services/          # Pipeline Orchestrator Service
    ├── storage/               # File Storage (Uploads & Jobs Dataset)
    └── main.py                # App Entrypoint & Lifespan Cleanups
```

---

## Workflow Analisis Kalibrasi (Offline)

Tool riset di `backend/tools/calibration/` membandingkan score pada manifest
dengan label manual. Tool ini hanya menganalisis kandidat threshold: hasilnya
tidak mengubah konfigurasi pipeline, tidak menjalankan pemrosesan video, dan
tidak mengintegrasikan project rekonstruksi/training apa pun.

Workflow penelitiannya adalah:

1. Jalankan Data Preparation Tool sampai menghasilkan curated image dataset.
2. Download manifest CSV dari halaman hasil.
3. Beri ground-truth manual pada frame/pasangan frame yang akan dievaluasi.
4. Jalankan calibration CLI terhadap manifest dan label manual tersebut.
5. Bandingkan seluruh threshold, metrik, confusion matrix, dan frame yang salah
   klasifikasi.
6. Pilih beberapa candidate threshold untuk eksperimen.
7. Terapkan threshold final secara manual pada eksperimen utama setelah
   evaluasi; calibration tool tidak menerapkannya otomatis.

### 1. Instal dependensi grafik opsional

Dependensi riset dipisahkan dari dependensi runtime FastAPI:

```cmd
cd backend
.venv\Scripts\python.exe -m pip install -r requirements-calibration.txt
```

Gunakan `--no-plots` bila hanya membutuhkan CSV/JSON tanpa Matplotlib.

### 2. Buat label manual

Label blur menggunakan `filename,label`; `dataset_id` wajib bila menganalisis
lebih dari satu dataset:

```csv
dataset_id,filename,label
video_ruang,IMG_000001.jpg,sharp
video_ruang,IMG_000002.jpg,blur
video_ruang,IMG_000003.jpg,borderline
```

Nilai label yang diterima adalah `sharp`, `blur`, dan opsional `borderline`.
Penanganan `borderline` harus dipilih eksplisit dengan
`--borderline-policy error|exclude|blur|sharp` (default `error`).

Label duplicate harus merujuk pasangan yang benar-benar tercatat dalam
manifest melalui `filename,compared_with,label`:

```csv
dataset_id,filename,compared_with,label
video_ruang,IMG_000010.jpg,IMG_000009.jpg,keep
video_ruang,IMG_000011.jpg,IMG_000010.jpg,duplicate
```

Template tersedia di
`backend/tools/calibration/examples/manual_blur_labels.csv` dan
`backend/tools/calibration/examples/manual_duplicate_labels.csv`.

### 3. Jalankan analisis

Satu dataset (ID diturunkan dari nama `{id}_manifest.csv`):

```cmd
cd backend
.venv\Scripts\python.exe -m tools.calibration ^
  --manifest storage\jobs\JOB_ID\video_manifest.csv ^
  --blur-labels labels\manual_blur_labels.csv ^
  --duplicate-labels labels\manual_duplicate_labels.csv ^
  --borderline-policy exclude ^
  --output calibration-output
```

Beberapa dataset sebaiknya memakai ID eksplisit agar nama file yang sama tidak
bertabrakan:

```cmd
.venv\Scripts\python.exe -m tools.calibration ^
  --dataset ruang_a=C:\data\ruang_a_manifest.csv ^
  --dataset ruang_b=C:\data\ruang_b_manifest.csv ^
  --blur-labels C:\labels\blur.csv ^
  --duplicate-labels C:\labels\duplicate.csv ^
  --output calibration-output
```

Secara default kandidat sweep berasal dari setiap score unik yang teramati,
ditambah batas di bawah minimum dan di atas maksimum. Range eksplisit dapat
ditentukan secara terpisah, misalnya `--blur-min 0 --blur-max 300
--blur-step 5`; opsi serupa tersedia untuk `ssim` dan `orb`. SSIM dan ORB
selalu dianalisis terpisah karena skala serta perilaku score-nya tidak boleh
dicampur.

Aturan klasifikasinya mengikuti keputusan detector: blur positif jika
`blur_score < threshold`, sedangkan duplicate positif jika
`similarity_score >= threshold`. Untuk setiap threshold tool menghitung
TP/FP/TN/FN, accuracy, precision, recall, F1, specificity, false-positive
rate, dan balanced accuracy. Rekomendasi menampilkan seluruh threshold yang
seri untuk F1 tertinggi, balanced accuracy tertinggi, serta FPR terendah pada
target recall (`--target-recall`, default `0.9`). Ini adalah bahan evaluasi,
bukan perubahan otomatis terhadap default aplikasi.

### 4. Periksa hasil

Setiap analisis yang tersedia (`blur/`, `ssim/`, atau `orb/`) menghasilkan:

```text
calibration-output/
|-- calibration_summary.md
|-- blur/
|   |-- threshold_analysis.csv
|   |-- misclassified_frames.csv
|   |-- confusion_matrix.csv
|   |-- summary.json
|   |-- score_distribution.png
|   |-- threshold_metrics.png
|   `-- confusion_matrix.png
`-- ssim/ atau orb/ ...
```

Input divalidasi secara ketat. Proses berhenti dengan pesan error untuk
referensi file yang hilang, score kosong/non-numerik, method duplicate yang
tidak dikenal, pasangan `compared_with` yang tidak cocok, label ambigu, atau
ID dataset yang bertabrakan.

### Persiapan dataset dan protokol labeling

Sebelum menjalankan analisis, gunakan panduan penelitian berikut:

- [Calibration Dataset Preparation](docs/research/CALIBRATION_DATASET_PREPARATION.md)
- [Blur Labeling Protocol](docs/research/BLUR_LABELING_PROTOCOL.md)
- [Duplicate Labeling Protocol](docs/research/DUPLICATE_LABELING_PROTOCOL.md)

Candidate sampling yang reproducible tersedia melalui
`python -m tools.calibration_sampling`. Output default bersifat blind dan tidak
menampilkan score algoritma. Utility ini terpisah dari runtime aplikasi.

### Standalone image downscale

Folder image hasil ekstraksi dapat diturunkan resolusinya secara terpisah tanpa
menjalankan ulang pipeline menggunakan `python -m tools.image_downscale`.
Utility ini memakai bounding box default `1920x1080`, mempertahankan aspect
ratio, tidak crop, tidak upscale, tidak menimpa source, serta menghasilkan
`downscale_manifest.csv`. Panduan lengkap tersedia di
[`backend/tools/image_downscale/README.md`](backend/tools/image_downscale/README.md).

Web UI di `/image-downscale` mendukung satu folder image maupun satu dataset
root dengan beberapa subfolder patung. Directory upload mempertahankan relative
path, dry run memeriksa semua dataset, corrupt image memblokir batch, dan output
ZIP mempertahankan folder per patung beserta manifest per dataset serta
`batch_downscale_summary.csv`. Untuk perilaku deterministic, image yang berada
lebih dalam dari `root/dataset/image` ditolak dan tidak pernah di-flatten.

Untuk dataset besar pada mesin yang menjalankan backend, mode **Local Path**
menerima input/output filesystem path dan memprosesnya langsung tanpa browser
upload atau ekstraksi ZIP. Mode ini ditujukan hanya untuk trusted localhost;
source tetap read-only dan output existing ditolak.

Preview Local Path memakai Quick Dry Run deterministic (default dua sample per
dataset: first/last). Ini hanya preview resolusi; Start Downscale selalu
menjalankan full preflight seluruh image sebelum membuat output.

Untuk menyiapkan package pilot blur, SSIM, dan ORB sekaligus setelah path data
calibration tersedia, gunakan `python -m tools.pilot_labeling`. Perintah ini
melakukan preflight seluruh gambar dan pasangan, membuat repeat blind untuk
consistency check, dan berhenti sebelum Calibration Analysis. Lihat
[Pilot Labeling Checklist](docs/research/PILOT_LABELING_CHECKLIST.md) dan
[Pilot Results Template](docs/research/PILOT_RESULTS.md).

---

## 📜 Lisensi

Proyek ini dilisensikan di bawah **MIT License**.
