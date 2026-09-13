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
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as file:
                return json.load(file)
        except json.JSONDecodeError:
            return []
    return []

def save_posted_ids(posted_ids):
    with open(LOG_FILE, "w") as file:
        json.dump(posted_ids[-MAX_LOG_SIZE:], file, indent=4)

def send_to_discord(webhook_url, role_id, title, description, url, color, author_name):
    if not webhook_url:
        return False
        
    content = f"<@&{role_id}>" if role_id else ""
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

    all_accounts = list(set(ACCOUNTS_LOKER + ACCOUNTS_MAGANG))
    
    # Menggunakan searchTerms dengan format from:username agar terhindar dari noResults: true
    search_queries = [f"from:{account}" for account in all_accounts]

    run_input = {
        "searchTerms": search_queries,
        "maxItems": len(all_accounts) * 10,
        "sort": "Latest"
    }

    print(f"Menjalankan Apify Scraper untuk {len(all_accounts)} akun...")
    run = client.actor("apidojo/tweet-scraper").call(run_input=run_input)
    
    dataset_items = client.dataset(run["defaultDatasetId"]).iterate_items()

    tweets_by_account = {}
    for item in dataset_items:
        # Lewati log error kosong dari Apify
        if item.get("noResults"):
            continue
            
        tweet_id = item.get("id")
        text = item.get("text", "")
        author_info = item.get("author", {})
        username = author_info.get("userName", "") or item.get("username", "")
        
        if not tweet_id or not username:
            continue
            
        username_lower = username.lower()
        if username_lower not in tweets_by_account:
            tweets_by_account[username_lower] = []
            
        if len(tweets_by_account[username_lower]) < MAX_POSTS_PER_ACCOUNT:
            tweets_by_account[username_lower].append(item)

    for username_lower, tweets in tweets_by_account.items():
        for t in tweets:
            tweet_id = t.get("id")
            
            if tweet_id in posted_ids:
                continue

            text = t.get("text", "")
            author_info = t.get("author", {})
            username = author_info.get("userName", username_lower)
            url = t.get("url", f"https://twitter.com/{username}/status/{tweet_id}")
            author_name = author_info.get("name", username)

            is_loker, is_magang = check_category(text, username)
            sent = False

            if is_loker and WEBHOOK_LOKER:
                success = send_to_discord(
                    WEBHOOK_LOKER, ROLE_ID_LOKER, 
                    f"💼 Lowongan Kerja Baru dari @{username}", 
                    text, url, COLOR_LOKER, author_name
                )
                if success: sent = True

            if is_magang and WEBHOOK_MAGANG:
                success = send_to_discord(
                    WEBHOOK_MAGANG, ROLE_ID_MAGANG, 
                    f"🎓 Info Magang Baru dari @{username}", 
                    text, url, COLOR_MAGANG, author_name
                )
                if success: sent = True

            if sent:
                posted_ids.append(tweet_id)
                newly_posted += 1
                print(f"Berhasil mengirim tweet {tweet_id} dari @{username}")

    save_posted_ids(posted_ids)
    print(f"Proses selesai. {newly_posted} postingan baru terkirim ke Discord.")

if __name__ == "__main__":
    main()
