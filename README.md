# 🎥 GS-Prep — Gaussian Splatting & 3D Reconstruction Dataset Preparation Tool

<p align="center">
  <b>Pipeline Preprocessing Otomatis untuk 3D Reconstruction, COLMAP, Gaussian Splatting (3DGS), dan NeRF.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Next.js-15-black?style=for-the-badge&logo=next.js" alt="Next.js">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/OpenCV-4.11-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white" alt="OpenCV">
  <img src="https://img.shields.io/badge/Tailwind_CSS-3.4-38B2AC?style=for-the-badge&logo=tailwind-css" alt="Tailwind CSS">
</p>

---

## 📌 Deskripsi

**GS-Prep** adalah alat preprocessing modern berkinerja tinggi yang mengubah rekaman video mentah (*raw footage*) menjadi dataset foto siap latih (*training dataset*) berkualitas tinggi untuk keperluan **3D Gaussian Splatting**, **COLMAP**, **NeRF**, dan **Scaffold-GS**.

Proses penyeleksian frame dilakukan secara non-destruktif dan otomatis tanpa memerlukan konfigurasi rumit.

---

## ✨ Fitur Utama

- 🎞️ **Frame Extraction Presisi**: Ekstraksi frame otomatis berdasarkan FPS yang dapat disesuaikan (default: 2 FPS) dengan pengontrolan kualitas JPEG.
- 🔍 **Blur Detection (Variance of Laplacian)**: Mendeteksi dan menyaring gambar yang blur/buram secara otomatis agar hasil rekonstruksi 3D lebih tajam.
- ♊ **Duplicate Removal (ORB Feature Matching / SSIM)**: Membandingkan pasangan frame untuk menghapus foto yang terlalu identik, menghemat waktu training secara signifikan.
- 📐 **Multi-Scale Resizing**: Pengecilan ukuran gambar (*bicubic downscaling*) ke resolusi standar (1080p, 720p, 480p, atau Original).
- 📂 **Nama Folder Otomatis**: Folder dataset hasil ekstraksi otomatis disesuaikan dengan nama file video yang diunggah (`{video_name}/processed/`).
- 📄 **Laporan PDF Report Auto-Generated**: Rekapitulasi statistik pemrosesan yang rapi dan siap diunduh dalam format PDF.
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
 │ PDF Report & │ ◄─── │ Multi-Scale  │ ◄─── ┌──────────────┐
 │ Dataset ZIP  │      │  Resizing    │      │  Duplicate   │
 └──────────────┘      └──────────────┘      │   Filter     │
                                             └──────────────┘
```

---

## 🛠️ Teknologi yang Digunakan

### Frontend
- **Framework**: Next.js 15 (App Router) + React 19
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
| **JPEG Quality** | `95` | **90-95** untuk kualitas visual maksimal |
| **Blur Threshold** | `100.0` | **100** (Standar), tingkatkan ke **150** jika ingin sangat selektif |
| **Duplicate Threshold** | `0.85` | **0.85** (85% kemiripan disaring), kurangi jika ingin foto lebih bervariasi |
| **Resize Width** | `1920` | **1920px (1080p)** disarankan untuk COLMAP / Gaussian Splatting |

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

## 📜 Lisensi

Proyek ini dilisensikan di bawah **MIT License**.
