"""
==========================================================
  BOT OTOMATISASI SCRAPING X (TWITTER) -> 2 DISCORD WEBHOOK
  Kategori : LOWONGAN KERJA (Loker) & MAGANG
  Sumber   : twstalker / sotwe / xcancel / nitter (+ failover)
  Penjadwal: GitHub Actions (cron 30 menit) / bisa jalan 24/7
==========================================================

Alur kerja singkat:
  1. Ambil RSS tiap akun X dari sumber (failover otomatis).
  2. Parse tiap tweet -> ambil ID, teks, gambar.
  3. Tentukan kategori (loker / magang) berdasarkan akun & keyword.
  4. Cek log `posted_tweets.json` agar tidak kirim ulang (anti-duplikat).
  5. Kirim ke webhook Discord sesuai kategori (embed + gambar + role mention).
"""

import os
import re
import json
import time
import random
import html
from datetime import datetime, timezone

import requests
import feedparser

# Muat variabel dari file .env bila ada (untuk dijalankan lokal / VPS)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Di GitHub Actions variabel disuntik lewat environment/secrets.
    pass


# ==========================================================
# 1. KONFIGURASI DISCORD (diambil dari .env / GitHub Secrets)
# ==========================================================
WEBHOOK_LOKER = os.getenv("DISCORD_WEBHOOK_LOKER")
WEBHOOK_MAGANG = os.getenv("DISCORD_WEBHOOK_MAGANG")

ROLE_ID_LOKER = os.getenv("ROLE_ID_LOKER", "")
ROLE_ID_MAGANG = os.getenv("ROLE_ID_MAGANG", "")


# ==========================================================
# 2. DAFTAR AKUN, KEYWORD, DAN SUMBER RSS
# ==========================================================

# Akun yang postingannya dianggap kategori Loker
ACCOUNTS_LOKER = [
    "lokerdotid",
    "lokerjogjax",
    "jogjalowker",
    "disiniloker",
    "magnecareer",
    "twitlowongan",
    "sobatmagang_id",
]

# Akun yang postingannya dianggap kategori Magang
ACCOUNTS_MAGANG = [
    "sobatmagang_id",
    "disiniloker",
    "magnecareer",
]

# Keyword (huruf kecil semua) penanda kategori Loker
LOKER_KEYWORDS = [
    kw.lower() for kw in [
        "#InfoLoker", "#Loker", "INFO LOKER", "#lowker",
        "#lowongan", "Loker Jogja", "#LokerPam", "#Lowongan",
    ]
]

# Keyword (huruf kecil semua) penanda kategori Magang
MAGANG_KEYWORDS = [
    kw.lower() for kw in [
        "#infoMagang", "#magangID", "#magangYuk", "#magang", "#MagangPam",
    ]
]

# File log database anti-duplikat
LOG_FILE = "posted_tweets.json"

# ----------------------------------------------------------
# Sumber RSS dengan urutan prioritas (failover).
# Prioritas utama: twstalker.com lalu sotwe.com,
# selanjutnya xcancel + instance nitter sebagai cadangan.
# {account} akan diganti dengan username X.
# ----------------------------------------------------------
SOURCE_TEMPLATES = [
    # --- Prioritas utama ---
    "https://twstalker.com/{account}/rss",
    "https://sotwe.com/{account}/rss",
    # --- Prioritas berikutnya ---
    "https://xcancel.com/{account}/rss",
    "https://nitter.net/{account}/rss",
    # --- Cadangan instance nitter lain (jika salah satu dihidupkan kembali) ---
    "https://nitter.privacyredirect.com/{account}/rss",
    "https://nitter.tiekoetter.com/{account}/rss",
    "https://nitter.projectsegfau.lt/{account}/rss",
    "https://nitter.eu/{account}/rss",
]

# Beberapa User-Agent agar lebih tahan terhadap pemblokiran dasar
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

REQUEST_TIMEOUT = 20          # detik
MAX_TWEETS_PER_ACCOUNT = 15   # batasi jumlah tweet yang diproses / akun (feed bisa panjang)
MULTIPLE_IMAGES_LIMIT = 4     # maksimal gambar yang dikirim per tweet


# ==========================================================
# 3. LOG DATABASE ANTI-DUPLIKAT
#    Struktur: { "tweet_id": ["loker", "magang"] }
#    (menyimpan ke kategori mana saja tweet sudah dikirim)
# ==========================================================
def load_posted_log():
    """Baca log. Mendukung format lama (list id) maupun format baru (dict)."""
    if not os.path.exists(LOG_FILE):
        return {}

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    # Migrasi format lama: list -> dict (anggap sudah terkirim ke semua kategori)
    if isinstance(data, list):
        return {str(tid): ["loker", "magang"] for tid in data}

    if isinstance(data, dict):
        return data

    return {}


def save_posted_log(log):
    """Simpan log ke disk."""
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def already_sent(log, tweet_id, category):
    """Cek apakah tweet sudah pernah dikirim ke kategori tertentu."""
    return category in log.get(tweet_id, [])


def mark_sent(log, tweet_id, category):
    """Tandai tweet sudah dikirim ke kategori tertentu."""
    log.setdefault(tweet_id, [])
    if category not in log[tweet_id]:
        log[tweet_id].append(category)


# ==========================================================
# 4. UTILITAS PARSING
# ==========================================================
_TAG_RE = re.compile(r"<[^>]+>")
_IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)


def strip_html(text):
    """Bersihkan tag HTML dari teks RSS."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_tweet_id(link):
    """Ambil ID numerik tweet dari URL (mis. .../status/1234567890)."""
    if not link:
        return ""
    match = re.search(r"/status/(\d+)", link)
    if match:
        return match.group(1)
    # Fallback: ambil segmen terakhir URL
    clean = link.split("?")[0].split("#")[0].rstrip("/")
    return clean.split("/")[-1]


def extract_images(entry):
    """Kumpulkan URL gambar dari sebuah entry RSS."""
    images = []

    # a) media:content / media:thumbnail (feedparser -> media_content/media_thumbnail)
    for key in ("media_content", "media_thumbnail"):
        for media in getattr(entry, key, []) or []:
            url = media.get("url")
            if url:
                images.append(url)

    # b) enclosure
    for enc in getattr(entry, "enclosures", []) or []:
        href = enc.get("href") or enc.get("url")
        mime = enc.get("type", "")
        if href and (mime.startswith("image") or mime == ""):
            images.append(href)

    # c) <img src="..."> di dalam description/summary
    raw_html = ""
    if getattr(entry, "description", None):
        raw_html = entry.description
    elif getattr(entry, "summary", None):
        raw_html = entry.summary
    images.extend(_IMG_RE.findall(raw_html))

    # Bersihkan: buang avatar/emoji umum, hilangkan duplikat, jaga urutan
    cleaned = []
    seen = set()
    for url in images:
        if not url or url.startswith("data:"):
            continue
        low = url.lower()
        if "profile_images" in low or "emoji" in low or "abs.twimg.com" in low:
            continue
        if url not in seen:
            seen.add(url)
            cleaned.append(url)

    return cleaned[:MULTIPLE_IMAGES_LIMIT]


def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ==========================================================
# 5. PENGAMBILAN FEED (FAILOVER MULTI-SUMBER)
# ==========================================================
def fetch_feed(rss_url):
    """
    Ambil & parse RSS dari URL.
    Mengembalikan objek feedparser jika sukses, atau None bila gagal.
    """
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(rss_url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200 or not resp.content:
            return None
        feed = feedparser.parse(resp.content)
        if getattr(feed, "entries", None) and len(feed.entries) > 0:
            # Pastikan isinya RSS/Atom, bukan halaman HTML (blokir Cloudflare dsb.)
            content_head = resp.text[:400].lower()
            if "<?xml" in content_head or "<rss" in content_head or "<feed" in content_head:
                return feed
        return None
    except requests.RequestException:
        return None
    except Exception:
        return None


def get_feed_for_account(account):
    """Coba setiap sumber berurutan sampai ada yang berhasil."""
    for template in SOURCE_TEMPLATES:
        rss_url = template.format(account=account)
        feed = fetch_feed(rss_url)
        if feed:
            return feed, rss_url
    return None, None


# ==========================================================
# 6. INTEGRASI DISCORD WEBHOOK
# ==========================================================
def build_embeds(text, tweet_link, images, account):
    """Susun embed Discord; gambar pertama jadi thumbnail utama."""
    color = 3447003  # biru

    main_embed = {
        "author": {"name": f"@{account} · X/Twitter"},
        "description": (text[:3900] if text else "_(tanpa teks)_"),
        "url": tweet_link,
        "color": color,
        "footer": {"text": f"Loker-Magang Bot · {now_utc_str()}"},
    }
    # Gambar pertama sebagai gambar utama embed
    if images:
        main_embed["image"] = {"url": images[0]}

    embeds = [main_embed]

    # Gambar tambahan sebagai embed terpisah (gallery sederhana)
    for img in images[1:]:
        embeds.append({
            "url": tweet_link,
            "color": color,
            "image": {"url": img},
        })

    return embeds


def send_to_discord(webhook_url, text, tweet_link, category, role_id, account, images=None):
    """Kirim satu tweet ke webhook Discord sesuai kategori."""
    images = images or []

    if not webhook_url:
        print(f"[SKIP] Webhook kategori '{category}' belum diatur. Tweet {tweet_link}")
        return False

    role_mention = f"<@&{role_id}>" if role_id else ""
    header = f"Info {category.upper()} baru! {role_mention}".strip()

    payload = {
        "content": header,
        "embeds": build_embeds(text, tweet_link, images, account),
        # Username & avatar bot (opsional, bisa diubah)
        "username": "Loker & Magang Bot",
        "allowed_mentions": {"parse": ["roles"]},
    }

    for attempt in range(1, 4):  # retry maksimal 3x
        try:
            resp = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
            if resp.status_code in (200, 204):
                print(f"[OK] Terkirim ke '{category}': {tweet_link}")
                return True
            if resp.status_code == 429:  # rate limit Discord
                retry_after = 2
                try:
                    retry_after = resp.json().get("retry_after", 2)
                except Exception:
                    pass
                print(f"[WAIT] Rate limited, tunggu {retry_after}s...")
                time.sleep(float(retry_after))
                continue
            print(f"[FAIL] Discord '{category}' HTTP {resp.status_code}: {resp.text[:150]}")
        except requests.RequestException as e:
            print(f"[ERR] Gagal kirim ({category}, attempt {attempt}): {e}")
        time.sleep(2)
    return False


# ==========================================================
# 7. LOGIKA ROUTING KATEGORI
# ==========================================================
def decide_categories(account, text_lower):
    """
    Tentukan kategori sebuah tweet.
    Mengembalikan set kategori: contoh {'loker'} / {'magang'} / {'loker','magang'}.
    """
    categories = set()

    if account in ACCOUNTS_LOKER or any(kw in text_lower for kw in LOKER_KEYWORDS):
        categories.add("loker")

    if account in ACCOUNTS_MAGANG or any(kw in text_lower for kw in MAGANG_KEYWORDS):
        categories.add("magang")

    return categories


WEBHOOK_BY_CATEGORY = {
    "loker": (lambda: WEBHOOK_LOKER, lambda: ROLE_ID_LOKER),
    "magang": (lambda: WEBHOOK_MAGANG, lambda: ROLE_ID_MAGANG),
}


# ==========================================================
# 8. FUNGSI UTAMA
# ==========================================================
def main():
    print(f"===== Mulai run: {now_utc_str()} =====")

    log = load_posted_log()
    all_accounts = sorted(set(ACCOUNTS_LOKER + ACCOUNTS_MAGANG))

    total_sent = 0

    for account in all_accounts:
        feed, used_source = get_feed_for_account(account)

        if not feed:
            print(f"[WARN] Gagal ambil feed @{account} dari semua sumber.")
            continue

        print(f"[INFO] @{account} <- {used_source} ({len(feed.entries)} tweet)")

        for entry in feed.entries[:MAX_TWEETS_PER_ACCOUNT]:
            tweet_link = getattr(entry, "link", "") or ""
            if not tweet_link:
                continue

            tweet_id = extract_tweet_id(tweet_link)
            if not tweet_id:
                continue

            # --- Anti-duplikat + routing ---
            text = strip_html(getattr(entry, "title", "")) or strip_html(
                getattr(entry, "description", "")
            )
            text_lower = text.lower()

            categories = decide_categories(account, text_lower)
            if not categories:
                continue

            # Hanya kirim ke kategori yang belum pernah dikirim (hindari dobel)
            pending = {c for c in categories if not already_sent(log, tweet_id, c)}
            if not pending:
                continue

            images = extract_images(entry)

            for category in sorted(pending):
                get_webhook, get_role = WEBHOOK_BY_CATEGORY[category]
                ok = send_to_discord(
                    webhook_url=get_webhook(),
                    text=text,
                    tweet_link=tweet_link,
                    category=category,
                    role_id=get_role(),
                    account=account,
                    images=images,
                )
                if ok:
                    mark_sent(log, tweet_id, category)
                    total_sent += 1
                    save_posted_log(log)  # simpan tiap sukses agar aman jika run terputus

            time.sleep(1)  # jeda sopan antar request

    save_posted_log(log)
    print(f"===== Selesai. Total terkirim: {total_sent} =====")


if __name__ == "__main__":
    main()