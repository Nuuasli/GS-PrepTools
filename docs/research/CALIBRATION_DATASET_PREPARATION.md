# Calibration Dataset Preparation

Dokumen ini mengatur persiapan data untuk kalibrasi threshold algoritma yang
sudah ada. Tahap ini tidak memilih threshold final dan tidak mengubah runtime
Data Preparation Tool.

## 1. Pemisahan data penelitian

Tetapkan pembagian video sebelum melihat hasil evaluasi utama:

```text
datasets/
|-- calibration/   # boleh digunakan untuk memilih kandidat threshold
`-- evaluation/    # hanya digunakan setelah konfigurasi dibekukan
```

Gunakan video yang berbeda pada kedua set jika memungkinkan. Hindari membagi
frame berdekatan dari video yang sama ke calibration dan evaluation karena
isinya sangat berkorelasi. Catat ID video, kondisi pengambilan, dan alasan
pembagian dalam log penelitian.

Jika jumlah video terbatas, alternatif yang paling defensible adalah membagi
per sesi pengambilan atau per lintasan kamera, bukan mengacak frame individual.
Bekukan threshold setelah calibration. Hasil evaluation tidak boleh digunakan
untuk menyetel threshold kembali; perubahan setelah melihat evaluation harus
dicatat sebagai eksperimen baru dengan evaluation set baru.

## 2. Sumber data dan gambar

Sampling membutuhkan manifest. Pembuatan paket visual juga membutuhkan file
gambar yang namanya sesuai dengan `filename` dan `compared_with` pada manifest.
Gunakan salah satu sumber berikut:

1. run penelitian dengan **Keep Intermediate Files** aktif; atau
2. salinan frame sumber/export yang sengaja dipertahankan.

Jangan mengubah lifecycle production untuk calibration. Lokasi gambar diberikan
secara eksplisit dengan `--images-root DATASET_ID=PATH`. Untuk blur, frame yang
ditolak mungkin tidak ada di curated export sehingga intermediate penelitian
perlu dipertahankan. Utility menyalin file byte-for-byte dan tidak melakukan
resize, recompression, enhancement, atau modifikasi piksel.

## 3. Stratified sampling

Untuk setiap video secara terpisah, utility:

1. memfilter score yang relevan (`blur`, `SSIM`, atau `ORB`);
2. mengurutkan kandidat berdasarkan score;
3. membagi urutan tersebut ke quantile/rank bin dengan ukuran mendekati sama;
4. mengambil kandidat secara round-robin dari setiap bin;
5. menyeimbangkan kuota antar-video selama kapasitasnya memungkinkan;
6. mengacak urutan akhir menggunakan deterministic seed.

SSIM dan ORB selalu dijalankan sebagai sampling terpisah. Range atau bin SSIM
tidak pernah digunakan untuk ORB. `--samples-per-dataset` dapat membatasi
dominasi satu video. Jika permintaan sampel melebihi data yang tersedia setelah
batas tersebut, utility berhenti dengan error dan tidak mengurangi jumlah secara
diam-diam.

Quantile sampling mencakup score rendah, tengah, dan tinggi, bukan hanya kasus
ekstrem. Gunakan cukup banyak bin/sampel agar area keputusan yang sedang diteliti
ikut terwakili. Jangan mengurutkan kembali file blind berdasarkan score.

## 4. Membuat candidate CSV

Contoh blur dari beberapa video:

```cmd
cd backend
.venv\Scripts\python.exe -m tools.calibration_sampling ^
  --dataset patung_a=C:\research\patung_a_manifest.csv ^
  --dataset patung_b=C:\research\patung_b_manifest.csv ^
  --type blur ^
  --samples 150 ^
  --bins 10 ^
  --samples-per-dataset 75 ^
  --seed 42 ^
  --output C:\research\labeling\blur_candidates.csv
```

Jalankan duplicate sebagai dua eksperimen:

```cmd
.venv\Scripts\python.exe -m tools.calibration_sampling ^
  --dataset patung_a=C:\research\patung_a_manifest.csv ^
  --dataset patung_b=C:\research\patung_b_manifest.csv ^
  --type ssim --samples 150 --bins 10 --seed 42 ^
  --output C:\research\labeling\ssim_candidates.csv

.venv\Scripts\python.exe -m tools.calibration_sampling ^
  --dataset patung_a=C:\research\patung_a_manifest.csv ^
  --dataset patung_b=C:\research\patung_b_manifest.csv ^
  --type orb --samples 150 --bins 10 --seed 42 ^
  --output C:\research\labeling\orb_candidates.csv
```

Output default adalah blind dan tidak memuat score. `--include-scores` tersedia
hanya untuk audit sampling oleh peneliti setelah proses labeling; jangan berikan
file non-blind tersebut kepada annotator.

Ukuran 100-200 frame/pair dapat dipakai sebagai contoh pilot praktis, bukan
syarat statistik universal. Tentukan jumlah aktual berdasarkan jumlah video,
variasi kondisi, hasil pilot, dan analisis metodologi penelitian.

## 5. Membuat paket labeling offline

Tambahkan sumber gambar eksplisit untuk menghasilkan paket blind:

```cmd
.venv\Scripts\python.exe -m tools.calibration_sampling ^
  --dataset patung_a=C:\research\patung_a_manifest.csv ^
  --dataset patung_b=C:\research\patung_b_manifest.csv ^
  --type ssim --samples 150 --bins 10 --seed 42 ^
  --output C:\research\audit\ssim_selection.csv ^
  --package-dir C:\research\labeling\ssim_package ^
  --images-root patung_a=C:\research\images\patung_a ^
  --images-root patung_b=C:\research\images\patung_b
```

Paket blur berisi `images/`. Paket duplicate berisi pasangan berikut:

```text
ssim_package/
|-- candidates.csv
|-- instructions.md
`-- pairs/
    `-- item_0001/
        |-- reference.jpg
        `-- current.jpg
```

`candidates.csv` di dalam package selalu blind, walaupun CSV audit eksternal
dibuat dengan `--include-scores`.

## 6. Blind labeling dan bias control

Annotator hanya boleh melihat identifier dan gambar. Sembunyikan:

- blur/similarity score;
- status dan rejection reason;
- threshold serta keputusan production;
- label lama atau label annotator lain.

Urutan hasil sudah diacak menggunakan seed. Simpan command, seed, jumlah bin,
jumlah sampel, daftar manifest, dan tanggal sampling sebagai bagian dari audit
trail. Jangan mengubah label berdasarkan score setelah score dibuka.

## 7. Pilot dan konsistensi annotator

Pilot pertama digunakan untuk menemukan definisi ambigu, banyaknya borderline,
pasangan yang salah, serta cakupan distribusi—bukan untuk mengesahkan threshold
final.

Jika hanya ada satu annotator, salin dan acak ulang sebagian kecil item setelah
jeda, lalu label tanpa melihat jawaban lama untuk mengecek konsistensi internal.
Jika ada dua annotator, keduanya bekerja pada salinan CSV terpisah. Simpan
`annotator_id`; selesaikan disagreement dengan aturan adjudikasi yang ditulis
sebelum membuka score. Calibration Analysis hanya menerima satu label final per
item, sehingga label antar-annotator harus direkonsiliasi menjadi CSV consensus,
bukan digabung mentah.

## 8. Menggunakan label pada Calibration Analysis

Kolom `item_id`, `annotator_id`, dan `notes` diabaikan dengan aman oleh utility
calibration. Setelah label selesai dan consensus dibuat bila perlu:

```cmd
.venv\Scripts\python.exe -m tools.calibration ^
  --dataset patung_a=C:\research\patung_a_manifest.csv ^
  --dataset patung_b=C:\research\patung_b_manifest.csv ^
  --blur-labels C:\research\labeling\blur_labeled.csv ^
  --duplicate-labels C:\research\labeling\ssim_labeled.csv ^
  --duplicate-labels C:\research\labeling\orb_labeled.csv ^
  --borderline-policy exclude ^
  --output C:\research\analysis\calibration
```

Pastikan setiap `filename` dan `compared_with` tetap sama dengan manifest.
Perlakuan borderline wajib eksplisit:
`exclude`, `blur`, atau `sharp`; jangan menggabungkannya diam-diam.

Setelah meninjau distribusi label, confusion matrix, false positive/negative,
dan seluruh threshold sweep, pilih kandidat untuk eksperimen calibration.
Bekukan konfigurasi sebelum membuka hasil Main Evaluation Set.

## 9. Menyiapkan tiga package pilot sekaligus

Setelah manifest dan images root Calibration Set tersedia, jalankan:

```cmd
cd backend
.venv\Scripts\python.exe -m tools.pilot_labeling ^
  --dataset patung_a=C:\research\patung_a_manifest.csv ^
  --dataset patung_b=C:\research\patung_b_manifest.csv ^
  --dataset patung_c=C:\research\patung_c_manifest.csv ^
  --images-root patung_a=C:\research\images\patung_a ^
  --images-root patung_b=C:\research\images\patung_b ^
  --images-root patung_c=C:\research\images\patung_c ^
  --source-video patung_a=patung_a ^
  --source-video patung_b=patung_b ^
  --source-video patung_c=patung_c ^
  --blur-samples 60 ^
  --ssim-samples 60 ^
  --orb-samples 60 ^
  --samples-per-dataset 20 ^
  --bins 10 ^
  --seed 42 ^
  --repeat-fraction 0.1 ^
  --output C:\research\pilot_labeling
```

Command melakukan preflight seluruh data sebelum membuat output. Jika gambar
current/reference hilang, pair manifest tidak valid, atau jumlah kandidat tidak
mencukupi, proses berhenti dengan error. Setelah berhasil, baca
`PILOT_PACKAGE_REPORT.md`, lakukan checklist, lalu berhenti untuk manual
labeling. Folder `pilot_consistency/` hanya untuk pemeriksaan intra-annotator dan
tidak boleh dimasukkan ke threshold analysis.

Jika video yang sama memiliki run manifest SSIM dan ORB terpisah, jangan biarkan
kedua run masuk sebagai duplikat pada pilot blur. Gunakan filter repeatable
`--blur-dataset-id`, `--ssim-dataset-id`, dan `--orb-dataset-id` untuk menentukan
manifest mana yang dipakai masing-masing eksperimen. Tanpa filter, seluruh
dataset yang diberikan dipakai untuk metode tersebut.

Untuk run SSIM dan ORB yang berasal dari video fisik yang sama, gunakan
`--source-video DATASET_ID=SOURCE_VIDEO_ID`. Mapping ini hanya digunakan untuk
pelaporan jumlah unique source video dan tidak memengaruhi score atau sampling.

Jika fase penelitian hanya mengizinkan blur pilot, tambahkan `--method blur`.
Mode ini tidak membaca kandidat duplicate dan tidak membuat folder SSIM/ORB.
