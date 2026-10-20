# Duplicate Labeling Protocol

## Tujuan

Menentukan apakah current frame menambah informasi visual/viewpoint yang layak
dibanding reference frame yang benar-benar digunakan detector. Ground truth
ditentukan dari pasangan gambar, bukan similarity score atau hasil proses lain.

## Tampilan annotator

Selalu tampilkan berdampingan:

- **reference**: frame pada kolom `compared_with`;
- **current**: frame pada kolom `filename`.

Tampilkan `item_id` dan identifier file, tetapi sembunyikan similarity score,
method score, threshold, status, rejection reason, dan keputusan production.
Jangan mengubah isi gambar.

## Definisi label

### `duplicate`

Current frame tidak memberikan perubahan visual atau viewpoint yang bermakna
dibanding reference dan secara praktis redundan.

### `keep`

Current frame masih memberikan informasi visual/viewpoint tambahan yang layak
dipertahankan, misalnya:

- perubahan sudut pandang atau posisi kamera;
- parallax yang terlihat;
- bagian objek atau detail permukaan baru;
- perubahan framing yang signifikan dan informatif.

Noise kecil, compression artifact, atau perubahan brightness sangat kecil tanpa
informasi baru bukan alasan otomatis untuk `keep`. Sebaliknya, kemiripan visual
yang tinggi bukan alasan otomatis untuk `duplicate` bila perubahan viewpoint
masih bermakna.

## Prosedur

1. Pastikan pasangan sesuai `compared_with` versus `filename`.
2. Bandingkan struktur, viewpoint, bagian objek, parallax, dan framing.
3. Abaikan perbedaan yang hanya berasal dari noise/artifact kecil.
4. Pilih `duplicate` hanya bila current praktis redundan; jika masih menambah
   informasi bermakna, pilih `keep`.
5. Catat kasus ambigu atau pasangan bermasalah di `notes`; jangan menebak score.
6. Jangan menggunakan hasil rekonstruksi atau output algoritma sebagai label.

## Konsistensi

Jalankan pilot pasangan terlebih dahulu. Untuk satu annotator, ulangi subset
kecil setelah jeda. Untuk dua annotator, gunakan file terpisah dan label secara
independen. Adjudikasi disagreement harus merujuk definisi operasional di atas,
bukan similarity score.
