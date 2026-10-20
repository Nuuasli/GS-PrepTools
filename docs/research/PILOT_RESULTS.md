# Pilot Results

Status: **TEMPLATE — belum diisi sampai manual labeling selesai.**

Dokumen ini tidak menetapkan threshold final dan tidak boleh digunakan untuk
mengubah production configuration secara otomatis.

## A. Data composition

- Jumlah video calibration:
- Dataset IDs:
- Sampling seed: `42`
- Quantile/rank bins:

### Blur

- Total labeled:
- Sharp:
- Blur:
- Borderline:
- Borderline policy untuk binary analysis: `exclude`

### SSIM

- Total labeled:
- Duplicate:
- Keep:

### ORB

- Total labeled:
- Duplicate:
- Keep:

## B. Blur pilot

- Ringkasan distribusi score per manual label:
- Kandidat threshold dengan F1 tertinggi:
- Kandidat threshold dengan balanced accuracy tertinggi:
- Kandidat threshold untuk target recall:
- Confusion matrix:
- False positive count (`manual=sharp`, `prediction=blur`):
- False negative count (`manual=blur`, `prediction=sharp`):
- Catatan: kandidat di atas bukan threshold final.

## C. SSIM pilot

- Ringkasan distribusi score duplicate/keep:
- Kandidat berdasarkan F1:
- Kandidat berdasarkan balanced accuracy:
- Kandidat untuk target recall:
- Confusion matrix:
- False positive (`manual=keep`, `prediction=duplicate`):
- False negative (`manual=duplicate`, `prediction=keep`):
- Catatan false positive useful-frame:

## D. ORB pilot

- Ringkasan distribusi score duplicate/keep:
- Kandidat berdasarkan F1:
- Kandidat berdasarkan balanced accuracy:
- Kandidat untuk target recall:
- Confusion matrix:
- False positive (`manual=keep`, `prediction=duplicate`):
- False negative (`manual=duplicate`, `prediction=keep`):
- Catatan false positive useful-frame:

Nilai threshold ORB tidak dibandingkan langsung dengan nilai threshold SSIM.

## E. Misclassification review

| Method | Dataset | Filename | Compared with | Error type | Original label | Corrected label | Reason | Date/revision |
|---|---|---|---|---|---|---|---|---|

Manual ground truth tidak diubah hanya karena berbeda dari detector. Koreksi
hanya dilakukan bila review menemukan kesalahan labeling yang dapat dijelaskan.

## F. Protocol review

### Blur

- Apakah sharp/blur mudah dibedakan?
- Proporsi borderline:
- Evidence bahwa definisi perlu/tidak perlu diperjelas:

### Duplicate

- Apakah duplicate/keep cukup jelas?
- Apakah viewpoint/parallax menyebabkan banyak keraguan?
- Apakah pasangan dengan previous accepted frame masuk akal untuk dinilai?

### Sampling

- Apakah seluruh rentang score terwakili?
- Apakah komposisi antar-video cukup seimbang?
- Apakah ada dataset dengan kandidat tidak mencukupi?

## G. Readiness for full calibration

- [ ] Package valid.
- [ ] Label dapat diberikan secara cukup konsisten.
- [ ] Ambiguitas protocol dapat diterima atau sudah direvisi dengan evidence.
- [ ] Tidak ada masalah besar pada `compared_with`.
- [ ] Pilot Calibration Analysis berhasil dijalankan.
- [ ] Semua kelas penting memiliki contoh.
- [ ] Rentang score terwakili.

Keputusan: `LANJUT / REVISI PROTOCOL / TAMBAH PILOT DATA`

Alasan:
