# 🤖 Loker-Magang-Bot

Bot otomatisasi scraping **X (Twitter)** yang memilah postingan ke **2 channel Discord** berbeda
berdasarkan kategori **Lowongan Kerja (Loker)** dan **Magang**.

Berjalan otomatis 24/7 lewat **GitHub Actions** (default: setiap **30 menit**).

---

## ✨ Fitur

- 🔎 Scraping RSS dari beberapa akun X sekaligus.
- 🔁 **Failover multi-sumber**: twstalker → sotwe → xcancel → nitter (+ instance cadangan).
- 🧭 **Routing 2 kategori** ke 2 webhook Discord berbeda.
- 🚫 **Anti-duplikat** berbasis `posted_tweets.json` (per tweet & per kategori).
- 🖼️ Mengirim caption + gambar (jika ada) sebagai embed Discord.
- 📣 Opsional mention role (`@Loker` / `@Magang`).
- ♻️ Retry otomatis bila Discord rate-limit / error sementara.

---

## 📁 Struktur Proyek

```
Loker-Magang-Bot/
├── main.py                     # Script utama
├── requirements.txt            # Dependensi
├── posted_tweets.json          # Log anti-duplikat (auto-update)
├── .env.example                # Contoh konfigurasi
├── .gitignore
└── .github/
    └── workflows/
        └── scheduler.yml       # Penjadwal GitHub Actions
```

---

## 🚀 Cara Menjalankan

### A. Jalankan Lokal (untuk uji coba)

1. **Install dependensi**
   ```bash
   pip install -r requirements.txt
   ```

2. **Buat file `.env`** (salin dari `.env.example`) lalu isi webhook & role ID:
   ```env
   DISCORD_WEBHOOK_LOKER=https://discord.com/api/webhooks/...
   DISCORD_WEBHOOK_MAGANG=https://discord.com/api/webhooks/...
   ROLE_ID_LOKER=
   ROLE_ID_MAGANG=
   ```

3. **Jalankan**
   ```bash
   python main.py
   ```

### B. Deploy 24/7 via GitHub Actions (Rekomendasi)

1. **Push** seluruh file ke repository GitHub (pastikan folder `.github/workflows/` ikut ter-push).

2. Buka **Settings → Secrets and variables → Actions → New repository secret**, tambahkan:
   | Nama Secret | Isi |
   |---|---|
   | `DISCORD_WEBHOOK_LOKER` | URL webhook channel Loker |
   | `DISCORD_WEBHOOK_MAGANG` | URL webhook channel Magang |
   | `ROLE_ID_LOKER` | ID role Loker (opsional) |
   | `ROLE_ID_MAGANG` | ID role Magang (opsional) |

3. Buka tab **Actions**, pilih workflow **Loker & Magang Discord Bot**, klik **Run workflow** untuk tes manual.

4. Bot otomatis berjalan tiap 30 menit. Ingin tiap 60 menit? Ubah cron di
   `.github/workflows/scheduler.yml`:
   ```yaml
   - cron: '0 * * * *'    # tiap 60 menit
   ```

> **Catatan:** GitHub Actions `schedule` dapat tertunda beberapa menit saat server sibuk,
> dan **dinonaktifkan otomatis bila repo tidak aktif 60 hari**. Pastikan ada commit berkala
> (log `posted_tweets.json` otomatis di-commit tiap run, jadi biasanya aman).

---

## ⚙️ Kustomisasi

| Yang ingin diubah | Lokasi di `main.py` |
|---|---|
| Daftar akun Loker | `ACCOUNTS_LOKER` |
| Daftar akun Magang | `ACCOUNTS_MAGANG` |
| Keyword Loker | `LOKER_KEYWORDS` |
| Keyword Magang | `MAGANG_KEYWORDS` |
| Urutan / tambah sumber RSS | `SOURCE_TEMPLATES` |
| Batas tweet per akun | `MAX_TWEETS_PER_ACCOUNT` |
| Maksimal gambar per tweet | `MULTIPLE_IMAGES_LIMIT` |

---

## 🧠 Cara Kerja Routing

Sebuah tweet masuk kategori **Loker** jika akunnya ada di `ACCOUNTS_LOKER`
**atau** teksnya mengandung salah satu `LOKER_KEYWORDS`.
Begitu pula kategori **Magang** dengan `ACCOUNTS_MAGANG` / `MAGANG_KEYWORDS`.

Jika sebuah tweet cocok untuk **keduanya**, tweet akan dikirim ke **kedua channel**
tetapi hanya **sekali per channel** (dicek dari log), sehingga tidak ada duplikasi.

---

## 🔐 Keamanan

- **Jangan** commit file `.env` ke GitHub (sudah masuk `.gitignore`).
- Di GitHub Actions, rahasia disimpan sebagai **Repository Secrets**.

---

## ⚠️ Catatan Penting tentag Sumber RSS

Layanan mirror RSS X/Nitter sering berubah status (blokir Cloudflare, shutdown, dll).
Saat repo ini dibuat, hasil pengecekan domain: **twstalker (403 Cloudflare)**,
**sotwe (SSL kedaluwarsa)**, **xcancel (451)**, **nitter.net (410/mati)**.

Script tetap mencoba semua sumber secara berurutan dan akan otomatis lanjut ke sumber
berikutnya bila gagal. Bila semua sumber sedang down, cukup tambahkan mirror nitter
terbaru yang aktif ke `SOURCE_TEMPLATES` tanpa perlu mengubah logika lain.