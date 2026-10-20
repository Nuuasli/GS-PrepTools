# Blur Labeling Protocol

## Tujuan

Menentukan ground truth visual apakah suatu frame masih cukup mempertahankan
detail penting. Keputusan tidak boleh menggunakan `blur_score`, threshold,
status production, atau rejection reason.

## Tampilan annotator

Tampilkan satu gambar dalam ukuran yang memungkinkan pemeriksaan detail, bersama
`item_id`, `dataset_id`, dan `filename`. Gunakan file asli dari paket; jangan
melakukan sharpening, denoise, resize permanen, atau enhancement. Urutan item
harus berasal dari hasil shuffle deterministic sampling.

## Definisi label

### `sharp`

- detail objek terlihat cukup jelas;
- edge utama dapat dikenali;
- tidak ada motion/focus blur yang secara nyata menghilangkan detail penting;
- frame masih layak dipertahankan berdasarkan kualitas detail visual.

### `blur`

- motion blur atau focus blur jelas menghilangkan detail objek;
- edge penting tidak lagi dapat dikenali dengan baik;
- kualitas visual tidak layak dipertahankan dibanding frame yang wajar dari
  pengambilan yang sama.

### `borderline`

- bukti visual berada di antara `sharp` dan `blur`; atau
- annotator tidak dapat mengambil keputusan dengan yakin setelah mengikuti
  prosedur pemeriksaan yang sama.

`borderline` bukan sinonim untuk `sharp` atau `blur`. Catat alasan singkat di
`notes`. Kebijakan analisis (`exclude`, `blur`, atau `sharp`) harus dinyatakan
eksplisit dan dilaporkan.

## Prosedur

1. Pastikan score dan keputusan algoritma tidak terlihat.
2. Lihat keseluruhan frame, lalu periksa edge/detail objek penting.
3. Bedakan blur dari noise, exposure, compression artifact, atau resolusi rendah.
4. Pilih satu label sesuai definisi operasional.
5. Gunakan `notes` untuk borderline atau kasus tidak biasa.
6. Jangan mengubah keputusan setelah membuka score tanpa mencatatnya sebagai
   relabeling terpisah.

## Konsistensi

Lakukan pilot lebih dahulu. Untuk satu annotator, ulangi subset kecil setelah
jeda tanpa melihat label lama. Untuk dua annotator, label secara independen dan
simpan `annotator_id`; disagreement diselesaikan menggunakan aturan adjudikasi
yang sama dan didokumentasikan.
