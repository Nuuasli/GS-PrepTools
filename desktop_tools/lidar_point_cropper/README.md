# LiDAR Point Cloud Object Cropper — desktop MVP

Aplikasi **desktop lokal Windows** untuk memilih bagian point cloud PLY, LAS, atau LAZ melalui bounding box 3D interaktif. Dirancang sebagai *modul terpisah* untuk ekosistem GS-PrepTools.

## Yang sudah diimplementasikan

- Import PLY **ASCII / binary** dengan `plyfile`; validasi `vertex`, `x/y/z`, atribut, koordinat nonfinite; klasifikasi point cloud, mesh, Gaussian.
- Import LAS/LAZ standar dengan `laspy` dan `lazrs`. Informasi LAS meliputi versi, point format, dimensi, scale/offset, status RGB, serta CRS dan satuannya jika metadata dapat dibaca.
- GUI **PySide6 + PyVista/VTK**: orbit/zoom/pan, camera preset enam arah + isometric, axis, ukuran titik, RGB/elevation/intensity (jika ada).
- **Axis-aligned / Oriented Bounding Box** yang dapat digeser, di-resize, dan (OBB) dirotasi menggunakan mouse. Klik **Preview Crop** untuk melihat titik terpilih, dengan original transparan opsional.
- **Polygon Selection** berbasis proyeksi kamera, dengan depth range dan rangkaian operasi Keep/Remove dari beberapa sudut. Seleksi disimpan dan diputar ulang dari matriks dan poligon, termasuk setelah ukuran viewport berubah.
- **Selection History** untuk Undo dan Redo atas perubahan kotak, Keep/Remove, dan Reset. History menyimpan parameter geometri dan urutan operasi.
- **Fine Cropping Brush** untuk menghapus dan memulihkan titik dengan sapuan mouse, radius layar, dan batas kedalaman.
- Preview subsampling deterministik maksimal **250.000** titik. **Ekspor selalu membaca semua vertex asli** (bukan hanya preview).
- Binary little-endian PLY, semua **scalar vertex properties** kompatibel dipertahankan secara bit-exact termasuk RGB, intensity, normal, dan atribut Gaussian. Tidak ada transformasi XYZ, decimation ekspor, denoising, atau smoothing.
- Dua lintasan streaming + verifikasi seluruh field, supaya tidak perlu memuat seluruh hasil crop ke RAM sekaligus. Export atomik (file PLY); metadata JSON otomatis menyimpan 6 bidang seleksi dan statistik titik.
- **Load Saved Selection** untuk replay ROI yang sama terhadap PLY sumber: batas kotak ditampilkan *static/locked*, lalu Preview dan Export bisa diulang; **Reset / New Box** mengaktifkan editing kotak kembali.
- File `.ply` asli tidak diubah. Ada konfirmasi overwrite output.

## Batasan MVP (penting dibaca)

1. Polygon dan brush memilih pusat vertex berdasarkan proyeksi dan depth. Titik yang tertutup geometri lain bisa ikut terpilih.
2. Jika PLY berisi `face`, `edge`, atau elemen non-vertex lain, output **vertex-only**. GUI meminta konfirmasi sebelum menghilangkannya. Tidak melakukan remap face mesh.
3. Vertex properties bertipe **list** atau tipe scalar nonstandar ditolak dengan pesan; sifatnya agar tidak ada atribut yang terbuang diam-diam.
4. Cropping Gaussian PLY hanya menyaring record vertex, **bukan** menghasilkan LiDAR ground truth. File contoh `train_gs.ply` perlu diaudit struktur atributnya dan sumber geometrinya dahulu.
5. Metadata history versi 5 menyimpan stroke brush dan memeriksa SHA-256 saat replay. History versi 4 tetap dapat dimuat. Metadata crop kotak PLY yang lebih lama mengecek nama dan ukuran sumber dan dimuat sebagai satu keadaan awal.
6. Preview adalah subset titik, sehingga estimasi jumlah titik dan bounds saat preview tidak persis sama dengan data lengkap. Statistik full-resolution dikalkulasi saat export.
7. VTK renderer memakai OpenGL; di komputer Windows tanpa dukungan OpenGL yang memadai, GUI mungkin gagal menggambar. Gunakan mesin dengan driver grafis kompatibel. Tidak butuh CUDA atau WSL.
8. Batas yang ditampilkan bersatuan **koordinat PLY**, bukan otomatis meter. Cropping bukan registrasi/alignment. Chamfer Distance mensyaratkan frame, orientasi, skala/satuan, dan sampling/evaluasi yang kompatibel.
9. Aplikasi ini terpisah dari frontend web: **tidak otomatis muncul sebagai route di Next.js**.

## Folder yang disarankan dalam repo GS-PrepTools

```
GS-PrepTools/
  backend/                     # aplikasi lama (tidak diubah)
  frontend/                    # aplikasi lama (tidak diubah)
  desktop_tools/
    lidar_point_cropper/
      run.py
      requirements.txt
      generate_demo_ply.py
      lidar_cropper/
        __init__.py
        core.py
        gui.py
      tests/
        test_core.py
```

## Instalasi di VS Code Windows / PowerShell (Python 3.10)

Pilih interpreter Python 3.10 pada terminal, lalu gunakan virtual environment di folder modul.

```powershell
cd C:\Project_Guweh\dataprep4gs\desktop_tools\lidar_point_cropper
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe generate_demo_ply.py
.\.venv\Scripts\python.exe run.py
```

Jika aktivasi script diblokir PowerShell, jalankan `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` **hanya pada sesi terminal itu**, lalu aktifkan `.venv` lagi. Alternatif tanpa aktivasi:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Jika menggunakan Git Bash:

```bash
cd /c/Project_Guweh/dataprep4gs/desktop_tools/lidar_point_cropper
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python run.py
```

Dalam VS Code, **Python: Select Interpreter** lalu pilih `.venv\Scripts\python.exe` dari folder modul ini.

## Cara memakai

1. Klik **Open Point Cloud…** dan pilih PLY, LAS, atau LAZ. Tunggu validasi dan preview.
2. Putar kamera dengan mouse, lalu geser/resize/rotate widget kotak untuk membatasi patung. Pilih Axis-Aligned jika ingin kotak tanpa rotasi.
3. Klik **Preview Crop**. Tombol **Export** baru aktif setelah preview dan akan nonaktif saat kotak digeser lagi.
4. Klik **Export Crop + JSON** dan pilih path lain dari file sumber. Konfirmasi vertex-only jika input mesh. Tunggu seleksi full-resolution dan verifikasi.
5. Hasil adalah file crop dan `<nama>_crop_selection.json` di folder tujuan. Untuk input LAS/LAZ, pilih LAS atau LAZ untuk mempertahankan point record dan header native. PLY turunan menyimpan XYZ terdekode sebagai `float64` dan atribut scalar kompatibel. Metadata LAS yang terbaca tersedia di JSON. Properti yang tidak dapat diwakili oleh PLY scalar memblokir ekspor PLY.
6. Untuk mereproduksi, buka kembali sumber yang sama, klik **Load Saved Selection…** dan pilih JSON tadi. Replay LAS/LAZ memeriksa SHA-256 sumber. Kotak yang dimuat bersifat statis sampai **Reset / New Box**.

LAS/LAZ dibaca per chunk. Jika RGB absen atau sampel RGB seluruhnya nol, tampilan menggunakan intensity yang bervariasi atau elevation. Pewarnaan hanya berlaku di viewport. Ekspor native mempertahankan scale, offset, point format, atribut, dan metadata spasial serta menghitung ulang point count dan bounds. COPC dan point format yang membawa waveform belum didukung.

### Polygon Selection

1. Atur sudut dan pilih **Perspective** atau **Orthographic**. Buat AABB/OBB dahulu jika ingin menjadikannya batas awal.
2. Klik **Draw Polygon**. Klik kiri untuk menambah titik. Gunakan Backspace untuk menghapus titik terakhir atau Escape untuk membatalkan draft. Kamera terkunci selama draft aktif. Perubahan ukuran atau DPI viewport membatalkan draft supaya posisi klik tetap konsisten.
3. Atur **Depth near** dan **Depth far**, yaitu jarak sepanjang sumbu pandang kamera dalam satuan koordinat sumber. Pilih **Keep Selected** untuk menyisakan irisan atau **Remove Selected** untuk mengurangi area. Klik **Confirm Polygon** untuk menerapkan dan memperbarui preview.
4. Pindah sudut dan ulangi sesuai kebutuhan. **Reset / New Box** membuat seleksi kotak baru dan mencatat satu langkah Reset di history. **Load Saved Selection** memulihkan rangkaian dari JSON.
5. Preview menampilkan jumlah pada sampel. **Export Crop + JSON** menghitung jumlah sebenarnya dari seluruh vertex. Untuk Gaussian PLY, poligon menguji pusat Gaussian.

### Selection History

- Gunakan **Undo** (`Ctrl+Z`) dan **Redo** (`Ctrl+Y`) untuk berpindah satu langkah. Satu drag selesai adalah satu langkah, begitu pula satu konfirmasi poligon atau Reset. Preview diperbarui saat berpindah langkah.
- Operasi baru setelah Undo menggantikan cabang Redo dalam sesi. **Save Selection** membuat JSON dari langkah yang masih aktif sampai posisi sekarang. Langkah yang sudah dibatalkan dikecualikan. **Load Saved Selection** mengganti history sesi dengan history aktif dari file.
- **Full retained** hanya muncul jika jumlah full-resolution sudah tersedia untuk langkah aktif, misalnya dari ekspor yang terverifikasi. Undo atau Redo yang kembali ke langkah tersebut juga mengembalikan angkanya.
- Membuka sumber baru memulai history baru. History berlaku untuk seleksi. Kamera, perubahan tampilan, dan file yang sudah diekspor berada di luar history.

### Fine Cropping Brush

1. Atur arah kamera, lalu klik **Enable Brush**. Pilih **Remove Brush** atau **Restore Brush**. Atur radius dalam piksel logis dan depth sepanjang sumbu kamera sebelum menggambar.
2. Klik dan geser untuk menggambar satu sapuan. Kamera dikunci selama stroke aktif. Ketika mouse dilepas, titik sampel yang akan berubah disorot dan jumlahnya ditampilkan.
3. Klik **Confirm Stroke** untuk mencatat satu langkah atau **Cancel Stroke** untuk kembali ke seleksi saat ini. Kamera dapat digerakkan lagi setelah konfirmasi atau pembatalan. Perubahan ukuran viewport atau DPI membatalkan draft.
4. Restore hanya memulihkan titik yang dihapus oleh brush dan masih berada di dalam ROI awal serta lolos operasi poligon. Batas radius diputar ulang dengan snapshot kamera, viewport, dan DPI saat sapuan dibuat.
5. **Export Crop + JSON** menerapkan riwayat ke seluruh vertex per chunk. **Cancel Export** menghentikan pekerjaan pada batas chunk selama hasil belum dipublikasikan. Jumlah full-resolution tersedia setelah ekspor terverifikasi.

## Pengujian

`python -m pytest -q` menguji:

- crop AABB/OBB (rotasi) pada posisi jauh dari origin;
- mask dan replay JSON;
- read ASCII / binary PLY;
- atribut vertex dan koordinat dipertahankan;
- file sumber tidak berubah;
- mesh memerlukan persetujuan eksplisit;
- Gaussian dideteksi;
- crop kosong, output existing, dan mismatch sumber metadata.

Untuk menjalankan smoke test interaktif pada Windows, buat `demo_scan.ply` dengan perintah di atas lalu jalankan:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/gui_smoke.py -q -s
```

Smoke test GUI tambahan dengan LAZ sintetis:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/gui_las_smoke.py -q -s
```

Set `LIDAR_SMOKE_SOURCE` ke satu path LAS/LAZ untuk menjalankan smoke test pada file tersebut. Output uji ditulis ke folder sementara pytest.

Untuk Polygon Selection, jalankan `.\.venv\Scripts\python.exe -m pytest tests/gui_polygon_smoke.py -q -s` di desktop Windows. Set `LIDAR_POLYGON_SMOKE_SOURCE` ke satu LAS aktual untuk mengaktifkan pengujian preview read-only.

Untuk Selection History, jalankan `.\.venv\Scripts\python.exe -m pytest tests/gui_history_smoke.py -q -s`. Set `LIDAR_HISTORY_SMOKE_SOURCE` ke satu LAS aktual untuk pengujian Undo/Redo preview read-only.

Untuk Fine Cropping Brush, jalankan `.\.venv\Scripts\python.exe -m pytest tests/gui_brush_smoke.py -q -s`. Set `LIDAR_BRUSH_SMOKE_SOURCE` ke satu LAS aktual untuk pengujian preview read-only.

Tes membuka jendela Qt/VTK dan menggerakkan kotak AABB/OBB dengan event mouse. Dialog file otomatis memakai fixture dan direktori sementara pytest. Hasil ekspor diverifikasi per record dan diuji ulang lewat metadata JSON.

Binary PLY dengan properti vertex scalar mendukung pembacaan memory-mapped. File ASCII dan elemen list dapat membutuhkan RAM lebih besar ketika dibaca oleh plyfile. Gunakan file kecil terlebih dahulu untuk mengecek format scan.
