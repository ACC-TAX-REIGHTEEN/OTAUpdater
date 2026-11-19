# 🚀 OTAUpdater

![Python](https://img.shields.io/badge/Python-3.x-blue?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Cross--Platform-lightgrey)
![Status](https://img.shields.io/badge/Status-Active-success)

**OTAUpdater** adalah sistem pembaruan otomatis (*Over-The-Air Updater*) berbasis Python yang dirancang untuk mengelola proses pengemasan paket pembaruan, validasi integritas file menggunakan SHA-256, pencadangan (*backup*) otomatis, hingga eksekusi *patch* secara terstruktur.

---

## ✨ Fitur Utama

* 🔄 **Pembaruan OTA Otomatis:** Menangani proses unduh dan penerapan pembaruan melalui skrip utama (`00_OTAUpdater.py`).
* 🔐 **Verifikasi Integritas (SHA-256):** Memastikan file paket pembaruan aman dan tidak rusak menggunakan generator hash (`MakeSHA256.py`).
* 📦 **Pengemasan Paket Otomatis:** Dilengkapi skrip PowerShell (`MakeAmain.zip.ps`) untuk membuat arsip paket pembaruan.
* 🧩 **Orkestrasi Patch:** Mengatur alur penerapan *patch* secara sistematis melalui `_patchOrchestra_.py`.
* 💾 **Backup & Logging:** Mencadangkan file penting sebelum pembaruan di folder `backup/` dan mencatat seluruh aktivitas di `ota.log`.
* ⚙️ **Konfigurasi Fleksibel:** Pengaturan parameter OTA dipisahkan secara rapi di dalam file `ota.conf`.

---

## 📂 Struktur Proyek

Berikut adalah susunan direktori dan fungsi masing-masing file dalam proyek ini:

```text
OTAUpdater-main/
├── Dapur/
│   ├── 00_OTAUpdater.py        # Skrip inti untuk menjalankan proses OTA Update
│   └── OTA/
│       ├── backup/             # Direktori penyimpanan cadangan file sebelum update
│       │   └── __init__.py.bak # Contoh file cadangan (backup)
│       ├── ota.conf            # File konfigurasi utama (URL server, versi, path, dll.)
│       └── ota.log             # File log untuk mencatat riwayat dan error pembaruan
├── MakeAmain.zip.ps            # Skrip PowerShell untuk mengemas file update menjadi arsip ZIP
├── MakeSHA256.py               # Skrip Python untuk menghasilkan checksum SHA-256 paket update
├── _patchOrchestra_.py         # Skrip pengatur (orchestrator) proses penerapan patch
└── README.md                   # Dokumentasi proyek
```

---

## 📋 Prasyarat

Sebelum menjalankan proyek ini, pastikan perangkatmu sudah terpasang:

* **Python 3.x** ([Unduh Python](https://www.python.org/downloads/))
* **PowerShell** (untuk menjalankan skrip pengemasan `MakeAmain.zip.ps` di Windows)
* Library tambahan Python (jika ada, silakan sesuaikan):
  ```bash
  # Contoh jika menggunakan library requests
  pip install [nama-library-yang-digunakan]
  ```

---

## ⚙️ Instalasi & Konfigurasi

1. **Clone repositori ini** ke komputermu:
   ```bash
   git clone https://github.com/[username-github]/[nama-repo].git
   cd OTAUpdater-main
   ```

2. **Sesuaikan file konfigurasi** di `Dapur/OTA/ota.conf`:
   Buka file `Dapur/OTA/ota.conf` menggunakan teks editor, lalu atur parameter sesuai kebutuhan proyekmu (misalnya URL repositori/server update, versi aplikasi saat ini, dan direktori target).

   ```ini
   # Contoh isi ota.conf (sesuaikan dengan format di file aslimu)
   [OTA]
   update_url = https://contoh-server.com/update/
   current_version = 1.0.0
   ```

---

## 🚀 Cara Penggunaan

### 1. Membuat Paket Pembaruan (Untuk Developer/Rilis)
* **Kemas file pembaruan ke dalam ZIP:**
  Jalankan skrip PowerShell untuk membungkus file aplikasi:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\MakeAmain.zip.ps
  ```
* **Buat Checksum SHA-256:**
  Jalankan skrip Python berikut untuk menghasilkan kode hash validasi:
  ```bash
  python MakeSHA256.py
  ```

### 2. Menjalankan Proses OTA Update (Di sisi Pengguna/Aplikasi)
Jalankan skrip utama updater dari direktori proyek:
```bash
python Dapur/00_OTAUpdater.py
```

> **Catatan:** Jika ada proses *patching* lanjutan, modul `_patchOrchestra_.py` akan berperan mengatur tahapan eksekusi patch sesuai alur yang dikonfigurasi.

---

## 🛠️ Backup & Troubleshooting

* **Pemulihan (*Rollback*):** Jika terjadi kendala saat pembaruan, file cadangan sebelumnya tersimpan di dalam folder `Dapur/OTA/backup/`.
* **Cek Riwayat & Error:** Buka file `Dapur/OTA/ota.log` untuk melihat catatan detail apabila proses update gagal atau mengalami error.

---

## 🤝 Kontribusi

Kontribusi selalu terbuka! Jika ingin membantu mengembangkan proyek ini:
1. *Fork* repositori ini.
2. Buat *branch* fitur baru (`git checkout -b fitur-baru`).
3. *Commit* perubahanmu (`git commit -m "Menambahkan fitur baru"`).
4. *Push* ke *branch* tersebut (`git push origin fitur-baru`).
5. Ajukan *Pull Request*.

--- 

## 📜 Lisensi

Proyek ini dikembangkan untuk keperluan internal perusahaan. Silakan sesuaikan dengan kebutuhan organisasi Anda.

---

*Dikembangkan oleh [ACC-TAX-REIGHTEEN](https://github.com/ACC-TAX-REIGHTEEN)*
