import os
import json
import requests
from apify_client import ApifyClient

# ==========================================
# 1. KONFIGURASI DAN KEYWORDS
# ==========================================
ACCOUNTS_LOKER = ["lokerdotid", "lokerjogjax", "jogjalowker", "disiniloker", "magnecareer", "twitlowongan", "sobatmagang_id"]
ACCOUNTS_MAGANG = ["sobatmagang_id", "disiniloker", "magnecareer"]

LOKER_KEYWORDS = ["#infoloker", "#loker", "info loker", "#lowker", "#lowongan", "loker jogja", "#lokerpam"]
MAGANG_KEYWORDS = ["#infomagang", "#magangid", "#magangyuk", "#magang", "#magangpam"]

MAX_POSTS_PER_ACCOUNT = 5
MAX_LOG_SIZE = 500
LOG_FILE = "posted_tweets.json"

# ==========================================
# 2. KONFIGURASI ENVIRONMENT VARIABLES
# ==========================================
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
WEBHOOK_LOKER = os.getenv("DISCORD_WEBHOOK_LOKER")
WEBHOOK_MAGANG = os.getenv("DISCORD_WEBHOOK_MAGANG")
ROLE_ID_LOKER = os.getenv("ROLE_ID_LOKER", "")
ROLE_ID_MAGANG = os.getenv("ROLE_ID_MAGANG", "")

# Warna Embed Discord (Desimal)
COLOR_LOKER = 3447003   # Biru
COLOR_MAGANG = 5763719  # Hijau

# ==========================================
# 3. FUNGSI PENDUKUNG
# ==========================================
def load_posted_ids():
    """Membaca data tweet yang sudah diposting dari JSON lokal."""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as file:
                return json.load(file)
        except json.JSONDecodeError:
            return []
    return []

def save_posted_ids(posted_ids):
    """Menyimpan ID tweet terbaru, membatasi ukuran maksimal."""
    with open(LOG_FILE, "w") as file:
        json.dump(posted_ids[-MAX_LOG_SIZE:], file, indent=4)

def send_to_discord(webhook_url, role_id, title, description, url, color, author_name):
    """Mengirim data ke Discord menggunakan Webhook."""
    if not webhook_url:
        return False
        
    content = f"<@&{role_id}>" if role_id else ""
    
    # Potong deskripsi jika terlalu panjang (Batas Embed Discord 4096 karakter)
    description = description[:4090] + "..." if len(description) > 4090 else description

    payload = {
        "content": content,
        "embeds": [
            {
                "title": title,
                "description": description,
                "url": url,
                "color": color,
                "author": {"name": author_name},
                "footer": {"text": "Automated by GitHub Actions & Apify"}
            }
        ]
    }
    
    try:
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error mengirim ke Discord: {e}")
        return False

def check_category(text, username):
    """Mengecek kategori Loker dan/atau Magang (Case-Insensitive)."""
    text_lower = text.lower()
    user_lower = username.lower()
    
    is_loker = user_lower in [u.lower() for u in ACCOUNTS_LOKER] or any(k.lower() in text_lower for k in LOKER_KEYWORDS)
    is_magang = user_lower in [u.lower() for u in ACCOUNTS_MAGANG] or any(k.lower() in text_lower for k in MAGANG_KEYWORDS)
    
    return is_loker, is_magang

# ==========================================
# 4. FUNGSI UTAMA
# ==========================================
def main():
    print("Memulai proses otomatisasi...")
    if not APIFY_API_TOKEN:
        raise ValueError("APIFY_API_TOKEN tidak ditemukan di Environment Variables!")

    client = ApifyClient(APIFY_API_TOKEN)
    posted_ids = load_posted_ids()
    newly_posted = 0

    # Menggunakan Actor "apidojo/tweet-scraper" (Sangat stabil untuk Twitter)
    all_accounts = list(set(ACCOUNTS_LOKER + ACCOUNTS_MAGANG))
    
    run_input = {
        "twitterHandles": all_accounts,
        "maxItems": len(all_accounts) * 10, # Ambil ekstra untuk memastikan kita dapat 5 terbaru
        "sort": "Latest"
    }

    print(f"Menjalankan Apify Scraper untuk {len(all_accounts)} akun...")
    run = client.actor("apidojo/tweet-scraper").call(run_input=run_input)
    
    dataset_items = client.dataset(run["defaultDatasetId"]).iterate_items()

    # Mengelompokkan dan membatasi postingan (Maksimal 5 per akun)
    tweets_by_account = {}
    for item in dataset_items:
        # Menangani format JSON Apify (apidojo)
        tweet_id = item.get("id")
        text = item.get("text", "")
        author_info = item.get("author", {})
        username = author_info.get("userName", "")
        
        if not tweet_id or not username:
            continue
            
        if username not in tweets_by_account:
            tweets_by_account[username] = []
            
        if len(tweets_by_account[username]) < MAX_POSTS_PER_ACCOUNT:
            tweets_by_account[username].append(item)

    # Proses pengiriman ke Discord
    for username, tweets in tweets_by_account.items():
        for t in tweets:
            tweet_id = t.get("id")
            
            # 1. Cek Duplikasi
            if tweet_id in posted_ids:
                continue

            text = t.get("text", "")
            url = t.get("url", f"https://twitter.com/{username}/status/{tweet_id}")
            author_name = t.get("author", {}).get("name", username)

            # 2. Cek Kategori / Routing
            is_loker, is_magang = check_category(text, username)
            sent = False

            # 3. Kirim ke Channel Loker
            if is_loker and WEBHOOK_LOKER:
                success = send_to_discord(
                    WEBHOOK_LOKER, ROLE_ID_LOKER, 
                    f"💼 Lowongan Kerja Baru dari @{username}", 
                    text, url, COLOR_LOKER, author_name
                )
                if success: sent = True

            # 4. Kirim ke Channel Magang
            if is_magang and WEBHOOK_MAGANG:
                success = send_to_discord(
                    WEBHOOK_MAGANG, ROLE_ID_MAGANG, 
                    f"🎓 Info Magang Baru dari @{username}", 
                    text, url, COLOR_MAGANG, author_name
                )
                if success: sent = True

            # 5. Catat Log jika berhasil terkirim ke salah satu/kedua channel
            if sent:
                posted_ids.append(tweet_id)
                newly_posted += 1
                print(f"Berhasil mengirim tweet {tweet_id} dari @{username}")

    # Simpan kembali ID tweet untuk run berikutnya
    save_posted_ids(posted_ids)
    print(f"Proses selesai. {newly_posted} postingan baru terkirim ke Discord.")

if __name__ == "__main__":
    main()
