# Image Downscale Utility

Standalone utility untuk menurunkan resolusi folder image yang sudah diekstrak.
Utility ini tidak memanggil atau mengubah runtime frame extraction, blur
detection, duplicate detection, maupun manifest processing utama.

```text
EXTRACTED IMAGE FOLDER -> DOWNSCALE -> NEW IMAGE FOLDER
```

Jalankan dari folder `backend`:

```cmd
python -m tools.image_downscale ^
  --input "D:\TA_DATA\patung01\extracted" ^
  --output "D:\TA_DATA\patung01\extracted_1080p" ^
  --max-width 1920 ^
  --max-height 1080
```

Preview tanpa menulis file:

```cmd
python -m tools.image_downscale ^
  --input "D:\TA_DATA\patung01\extracted" ^
  --output "D:\TA_DATA\patung01\extracted_1080p" ^
  --dry-run
```

Default behavior menolak filename yang sudah ada. Gunakan `--force` hanya untuk
overwrite yang disengaja. JPEG hasil resize memakai quality `100` secara
default dan dapat diubah dengan `--jpeg-quality`. File yang sudah berada dalam
batas `max_width AND max_height` diklasifikasikan sebagai `unchanged` dan
disalin byte-for-byte tanpa decode, resize, re-encode, atau recompression.

Format top-level yang dipindai: `.jpg`, `.jpeg`, dan `.png`. Urutan selalu
berdasarkan filename. Hasil aktual menyertakan `downscale_manifest.csv` yang
terpisah dari manifest pipeline utama.

## Web UI: single folder dan dataset root

Halaman `/image-downscale` menyediakan tiga mode yang tetap memakai implementasi
`tools.image_downscale` di atas:

- **Single Image Folder**: semua image berada langsung dalam satu folder.
- **Dataset Root Folder**: setiap subfolder top-level adalah satu dataset dan
  image berada langsung di dalam subfolder tersebut.
- **Local Path**: backend membaca dataset root lokal dan menulis langsung ke
  output path tanpa upload browser.

Pada fase ini nested image directory yang lebih dalam dari
`root/dataset/image` ditolak dengan pesan eksplisit; file tidak pernah
diratakan. Browser mengirim relative path, bukan absolute path lokal. Backend
memvalidasi traversal, path absolut, drive prefix, nama invalid/reserved, serta
collision setelah sanitasi sebelum menulis uploaded copy ke workspace job.

Dry run memeriksa seluruh dataset. Satu image corrupt memblokir actual batch
secara default sehingga tidak ada research batch parsial. Actual processing
berjalan sequential per dataset dan menghasilkan struktur berikut:

```text
{root}_downscaled/
|-- dataset_a/
|   |-- images...
|   `-- downscale_manifest.csv
|-- dataset_b/
|   |-- images...
|   `-- downscale_manifest.csv
`-- batch_downscale_summary.csv
```

Web export adalah satu ZIP yang mempertahankan struktur tersebut. Source lokal
user tidak disentuh; backend hanya memproses uploaded/temp copies.
`batch_downscale_summary.csv` melaporkan `input_images`, `resized_images`,
`unchanged_images`, dan `output_images` per dataset. Dataset successful wajib
memenuhi `resized_images + unchanged_images = output_images`.

## Local Path mode

Untuk pemakaian trusted localhost, halaman `/image-downscale` juga menerima
path input dan output secara langsung. Frontend hanya mengirim string path;
backend Python membaca filesystem lokal dan menulis hasil secara atomik ke
exact output path. Dataset tidak di-upload dan ZIP tidak diwajibkan.

Local dry run memvalidasi input directory, akses baca, output yang berbeda dan
tidak berada di dalam input, parent output yang writable, collision output,
serta sample image yang dipilih. Output yang sudah ada ditolak secara default.
Full preflight saat Start memastikan satu image corrupt di mana pun memblokir
actual run dan tidak menghasilkan partial final dataset.

Local Path menggunakan **Quick Dry Run** untuk preview awal. Default-nya dua
sample deterministic per dataset: file supported pertama dan terakhir setelah
sorting filename. Jumlah dataset dan seluruh filename tetap dihitung, tetapi
hanya sample yang dibuka untuk membaca resolusi. Quick Dry Run tidak menulis
image, manifest, summary, atau output directory.

Quick Dry Run bukan full validation. Saat Start Downscale ditekan, batch runner
tetap menjalankan full preflight terhadap setiap image sebelum staging atau
final output dibuat. Karena itu corrupt image yang tidak masuk sample tetap
memblokir actual processing tanpa menghasilkan partial dataset.
