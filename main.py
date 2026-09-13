"""
Bot Otomatisasi Pencari Info Loker & Magang dari X (Twitter)
=============================================================
Sumber data : RSS Xcancel (https://xcancel.com/{akun}/rss)
Tujuan      : Discord Webhook (2 channel terpisah: Loker & Magang)
Hosting     : GitHub Actions (cron 30 menit + workflow_dispatch)

Author  : Senior Python Developer & Automation Expert (generated)
"""

import os
import re
import json
import time
import logging
import calendar
from datetime import datetime, timezone

import requests
import feedparser

# ============================================================
# 1. KONFIGURASI
# ============================================================

XCANCEL_BASE_URL = "https://xcancel.com/{}/rss"
MAX_ENTRIES_PER_ACCOUNT = 5
POSTED_LOG_FILE = "posted_tweets.json"
MAX_LOG_HISTORY = 500

REQUEST_TIMEOUT = 15  # detik
FETCH_RETRIES = 2
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# --- Akun target per kategori ---
ACCOUNTS_LOKER = [
    "lokerdotid", "lokerjogjax", "jogjalowker", "disiniloker",
    "magnecareer", "twitlowongan", "sobatmagang_id",
]
ACCOUNTS_MAGANG = ["sobatmagang_id", "disiniloker", "magnecareer"]

# Gabungan unik semua akun yang perlu di-fetch (agar tidak fetch dobel
# untuk akun yang muncul di kedua daftar, mis. disiniloker & magnecareer)
ALL_ACCOUNTS = sorted(set(ACCOUNTS_LOKER + ACCOUNTS_MAGANG))

# --- Keyword per kategori (dicocokkan case-insensitive) ---
LOKER_KEYWORDS = [
    "#infoloker", "#loker", "info loker", "#lowker",
    "#lowongan", "loker jogja", "#lokerpam", "#lowongan",
]
MAGANG_KEYWORDS = [
    "#infomagang", "#magangid", "#magangyuk", "#magang", "#magangpam",
]

# --- Discord Webhook & Role (diambil dari GitHub Secrets / env var) ---
DISCORD_WEBHOOK_LOKER = os.getenv("DISCORD_WEBHOOK_LOKER", "").strip()
DISCORD_WEBHOOK_MAGANG = os.getenv("DISCORD_WEBHOOK_MAGANG", "").strip()
ROLE_ID_LOKER = os.getenv("ROLE_ID_LOKER", "").strip()
ROLE_ID_MAGANG = os.getenv("ROLE_ID_MAGANG", "").strip()

EMBED_COLOR_LOKER = 0x2ECC71   # hijau
EMBED_COLOR_MAGANG = 0x3498DB  # biru

# ============================================================
# 2. LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("loker-magang-bot")

STATUS_ID_PATTERN = re.compile(r"/status/(\d+)")


# ============================================================
# 3. PENYIMPANAN LOG (ANTI-DUPLIKASI)
# ============================================================

def load_posted_ids():
    """Baca daftar ID tweet yang sudah pernah dikirim."""
    if not os.path.exists(POSTED_LOG_FILE):
        logger.info(f"{POSTED_LOG_FILE} belum ada, memulai dari daftar kosong.")
        return []
    try:
        with open(POSTED_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        logger.warning("Isi posted_tweets.json bukan list, reset ke kosong.")
        return []
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Gagal membaca {POSTED_LOG_FILE}: {e}. Reset ke daftar kosong.")
        return []


def save_posted_ids(posted_ids):
    """Simpan daftar ID, dibatasi maksimal MAX_LOG_HISTORY entri terakhir."""
    trimmed = posted_ids[-MAX_LOG_HISTORY:]
    try:
        with open(POSTED_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, indent=2, ensure_ascii=False)
        logger.info(f"Berhasil menyimpan {len(trimmed)} ID ke {POSTED_LOG_FILE}.")
    except OSError as e:
        logger.error(f"Gagal menulis {POSTED_LOG_FILE}: {e}")


# ============================================================
# 4. EKSTRAKSI & PARSING
# ============================================================

def extract_tweet_id(link):
    """
    Ambil ID tweet secara presisi dari URL status.
    Mengabaikan tautan non-status atau yang mengandung kata 'rss'.
    """
    if not link:
        return None
    if "rss" in link.lower():
        return None
    match = STATUS_ID_PATTERN.search(link)
    return match.group(1) if match else None


def clean_text(raw_html):
    """Bersihkan tag HTML dasar yang biasa muncul di isi RSS Xcancel."""
    if not raw_html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw_html)
    text = re.sub(r"<.*?>", "", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return text.strip()


def get_iso_timestamp(entry):
    """Konversi waktu publish RSS (RFC822) ke format ISO8601 untuk Discord embed."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            dt = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
            return dt.isoformat()
        except (OverflowError, ValueError, TypeError):
            pass
    return datetime.now(timezone.utc).isoformat()


def match_keywords(text, keywords):
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def determine_categories(account, combined_text):
    """
    Tentukan kategori (loker/magang) berdasarkan asal akun ATAU kecocokan
    keyword. Satu postingan bisa masuk ke dua kategori sekaligus.
    """
    categories = set()
    if account in ACCOUNTS_LOKER or match_keywords(combined_text, LOKER_KEYWORDS):
        categories.add("loker")
    if account in ACCOUNTS_MAGANG or match_keywords(combined_text, MAGANG_KEYWORDS):
        categories.add("magang")
    return categories


# ============================================================
# 5. PENGAMBILAN RSS FEED
# ============================================================

def fetch_feed(account):
    """Ambil & parse RSS feed sebuah akun, dengan retry sederhana."""
    url = XCANCEL_BASE_URL.format(account)
    last_error = None

    for attempt in range(1, FETCH_RETRIES + 2):
        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            if feed.entries or not feed.bozo:
                return feed
            last_error = getattr(feed, "bozo_exception", "unknown parse error")
        except requests.RequestException as e:
            last_error = e

        if attempt <= FETCH_RETRIES:
            logger.warning(f"[{account}] Percobaan {attempt} gagal ({last_error}), mencoba lagi...")
            time.sleep(2)

    logger.error(f"[{account}] Gagal mengambil RSS setelah beberapa percobaan: {last_error}")
    return None


# ============================================================
# 6. INTEGRASI DISCORD
# ============================================================

def build_embed(account, title, description, link, timestamp_iso, color):
    display_title = (title or "").strip() or f"Postingan baru dari @{account}"
    display_desc = (description or "").strip() or "(tidak ada teks tambahan)"

    return {
        "title": display_title[:256],
        "url": link,
        "description": display_desc[:4096],
        "color": color,
        "author": {
            "name": f"@{account}",
            "url": f"https://xcancel.com/{account}",
        },
        "timestamp": timestamp_iso,
        "footer": {"text": "Sumber: Xcancel RSS Feed"},
    }


def send_to_discord(webhook_url, role_id, embed):
    """Kirim satu embed ke webhook Discord tertentu, dengan mention role jika ada."""
    if not webhook_url:
        logger.warning("Webhook URL kosong/tidak diset, pengiriman dilewati.")
        return False

    content = f"<@&{role_id}>" if role_id else ""
    allowed_roles = [role_id] if role_id else []

    payload = {
        "content": content,
        "embeds": [embed],
        "allowed_mentions": {"parse": [], "roles": allowed_roles},
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)

        if resp.status_code == 429:
            retry_after = 1.0
            try:
                retry_after = float(resp.json().get("retry_after", 1.0))
            except (ValueError, json.JSONDecodeError):
                pass
            logger.warning(f"Terkena rate limit Discord, menunggu {retry_after:.1f}s...")
            time.sleep(retry_after + 0.5)
            resp = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)

        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error(f"Gagal mengirim ke Discord: {e}")
        return False


# ============================================================
# 7. PROSES UTAMA PER AKUN
# ============================================================

def process_account(account, posted_ids, new_posted_ids, stats):
    feed = fetch_feed(account)
    if feed is None:
        return

    entries = feed.entries[:MAX_ENTRIES_PER_ACCOUNT]

    # Proses dari yang terlama ke terbaru agar urutan pesan di Discord rapi
    for entry in reversed(entries):
        link = entry.get("link", "")
        tweet_id = extract_tweet_id(link)
        if not tweet_id:
            continue
        if tweet_id in posted_ids or tweet_id in new_posted_ids:
            continue  # sudah pernah dikirim sebelumnya

        raw_desc = entry.get("summary", "") or entry.get("description", "")
        text_content = clean_text(raw_desc)
        title_raw = clean_text(entry.get("title", ""))
        timestamp_iso = get_iso_timestamp(entry)

        categories = determine_categories(account, f"{title_raw} {text_content}")
        if not categories:
            continue  # tidak cocok kategori manapun, abaikan

        sent_any = False

        if "loker" in categories:
            embed = build_embed(account, title_raw, text_content, link, timestamp_iso, EMBED_COLOR_LOKER)
            if send_to_discord(DISCORD_WEBHOOK_LOKER, ROLE_ID_LOKER, embed):
                logger.info(f"[{account}] -> Terkirim ke channel LOKER (ID {tweet_id})")
                sent_any = True
                stats["loker"] += 1

        if "magang" in categories:
            embed = build_embed(account, title_raw, text_content, link, timestamp_iso, EMBED_COLOR_MAGANG)
            if send_to_discord(DISCORD_WEBHOOK_MAGANG, ROLE_ID_MAGANG, embed):
                logger.info(f"[{account}] -> Terkirim ke channel MAGANG (ID {tweet_id})")
                sent_any = True
                stats["magang"] += 1

        if sent_any:
            new_posted_ids.append(tweet_id)
            time.sleep(1)  # jaga jarak antar request ke Discord agar tidak rate-limit


# ============================================================
# 8. ENTRY POINT
# ============================================================

def main():
    logger.info("=== Mulai proses pencarian Loker & Magang ===")

    if not DISCORD_WEBHOOK_LOKER and not DISCORD_WEBHOOK_MAGANG:
        logger.warning(
            "Kedua DISCORD_WEBHOOK_LOKER dan DISCORD_WEBHOOK_MAGANG kosong. "
            "Bot tetap berjalan (untuk cek parsing) tapi tidak akan mengirim apapun."
        )

    posted_ids = load_posted_ids()
    new_posted_ids = []
    stats = {"loker": 0, "magang": 0}

    for account in ALL_ACCOUNTS:
        logger.info(f"Memeriksa akun: @{account}")
        try:
            process_account(account, posted_ids, new_posted_ids, stats)
        except Exception as e:  # noqa: BLE001 - jangan sampai 1 akun error menghentikan semua
            logger.error(f"[{account}] Error tak terduga: {e}")
        time.sleep(1.5)  # jeda sopan antar request ke Xcancel

    if new_posted_ids:
        updated = posted_ids + new_posted_ids
        save_posted_ids(updated)
        logger.info(
            f"Selesai. Postingan baru terkirim -> Loker: {stats['loker']}, "
            f"Magang: {stats['magang']} (total unik: {len(new_posted_ids)})"
        )
    else:
        logger.info("Tidak ada postingan baru yang cocok kategori pada siklus ini.")

    logger.info("=== Selesai ===")


if __name__ == "__main__":
    main()
