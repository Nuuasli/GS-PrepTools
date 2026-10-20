# Pilot Labeling Checklist

Checklist ini digunakan untuk Subfase A dan manual labeling. Jangan menjalankan
threshold analysis sebelum seluruh label manusia selesai dan divalidasi.

## Sebelum labeling

- [ ] Pastikan semua `dataset_id` berasal dari Calibration Set, bukan Evaluation Set.
- [ ] Baca `BLUR_LABELING_PROTOCOL.md` dan `DUPLICATE_LABELING_PROTOCOL.md`.
- [ ] Pastikan `PILOT_PACKAGE_REPORT.md` menyatakan package siap.
- [ ] Pastikan `candidates.csv` tidak memuat `blur_score`, `similarity_score`,
      threshold, status, rejection reason, atau keputusan detector.
- [ ] Buka beberapa item acak dari setiap package untuk memastikan seluruh
      gambar dapat dibuka.
- [ ] Untuk SSIM dan ORB, pastikan setiap folder memiliki `reference` dan
      `current`, serta cocok dengan `compared_with` dan `filename`.
- [ ] Pastikan seed, bin, jumlah video, dan komposisi per dataset tercatat.
- [ ] Buat salinan kerja CSV; pertahankan package asli sebagai audit trail.

## Selama labeling

- [ ] Jangan membuka manifest atau file audit yang memuat score.
- [ ] Ikuti definisi label pada protocol, bukan dugaan keputusan detector.
- [ ] Blur menggunakan `sharp`, `blur`, atau `borderline`.
- [ ] Duplicate menggunakan `duplicate` atau `keep`.
- [ ] Gunakan `borderline` hanya jika keputusan blur memang tidak meyakinkan.
- [ ] Isi `annotator_id` secara konsisten.
- [ ] Gunakan `notes` untuk kasus aneh, gambar rusak, pasangan meragukan, atau
      alasan borderline.
- [ ] Jangan melihat label lama ketika mengerjakan consistency-repeat.

## Setelah labeling

- [ ] Simpan file label dengan nama/version baru sebelum analysis.
- [ ] Pastikan tidak ada label utama yang kosong.
- [ ] Pastikan tidak ada label di luar vocabulary protocol.
- [ ] Pastikan `dataset_id`, `filename`, dan `compared_with` tidak diedit.
- [ ] Periksa kembali integritas seluruh duplicate pair.
- [ ] Hitung jumlah `sharp`, `blur`, `borderline`, `duplicate`, dan `keep`.
- [ ] Bandingkan consistency-repeat dengan label asli secara terpisah.
- [ ] Jangan masukkan consistency-repeat ke threshold analysis.
- [ ] Jika dua annotator digunakan, buat satu CSV consensus/adjudicated; jangan
      memasukkan dua label untuk item yang sama ke calibration utility.
- [ ] Gunakan `--borderline-policy exclude` untuk binary pilot analysis utama.
- [ ] Catat setiap koreksi label: original label, corrected label, alasan,
      tanggal, dan revision ID.

## Gate sebelum Subfase B

- [ ] Package valid dan seluruh gambar/pasangan dapat dinilai.
- [ ] Semua kelas penting memiliki contoh.
- [ ] Kasus borderline/ambigu sudah direview tanpa melihat score.
- [ ] Sampling mewakili dataset dan quantile score sesuai package report.
- [ ] Label final manusia sudah dibekukan untuk pilot analysis.
