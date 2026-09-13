import json
import os
import requests
from apify_client import ApifyClient

# ==========================================
# KONFIGURASI APIFY & DISCORD
# ==========================================
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "").strip()

DISCORD_WEBHOOK_LOKER = os.getenv("DISCORD_WEBHOOK_LOKER", "").strip()
DISCORD_WEBHOOK_MAGANG = os.getenv("DISCORD_WEBHOOK_MAGANG", "").strip()
ROLE_ID_LOKER = os.getenv("ROLE_ID_LOKER", "").strip()
ROLE_ID_MAGANG = os.getenv("ROLE_ID_MAGANG", "").strip()

# Atur jumlah postingan terakhir/terbaru yang ingin diambil per akun:
MAX_POSTS_PER_ACCOUNT = 5

ACCOUNTS_LOKER = ["lokerdotid", "lokerjogjax", "jogjalowker", "disiniloker", "magnecareer", "twitlowongan", "sobatmagang_id"]
ACCOUNTS_MAGANG = ["sobatmagang_id", "disiniloker", "magnecareer"]

LOKER_KEYWORDS = [kw.lower() for kw in ["#InfoLoker", "#Loker", "INFO LOKER", "#lowker", "#lowongan", "Loker Jogja", "#LokerPam", "#Lowongan"]]
MAGANG_KEYWORDS = [kw.lower() for kw in ["#infoMagang", "#magangID", "#magangYuk", "#magang", "#MagangPam"]]

LOG_FILE = "posted_tweets.json"

def load_posted_tweets():
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_posted_tweet(tweet_id, posted_list):
    if tweet_id not in posted_list:
        posted_list.append(tweet_id)
        # Batasi log agar tidak membengkak (simpan 1000 ID terakhir)
        if len(posted_list) > 1000:
            posted_list = posted_list[-1000:]
        with open(LOG_FILE, "w") as f:
            json.dump(posted_list, f)

def send_to_discord(webhook_url, text, link, category, role_id):
    role_mention = f"<@&{role_id}>"
    embed = {
        "title": f"📢 Lowongan Kategori: {category.upper()}",
        "description": text[:4000],
        "url": link,
        "color": 3447003 if category == "loker" else 15158332
    }
    payload = {
        "content": f"Info baru buat teman-teman! {role_mention}",
        "embeds": [embed]
    }
    response = requests.post(webhook_url, json=payload)
    if response.status_code in [200, 204]:
        print(f"✅ Berhasil mengirim postingan ke channel {category}")
    else:
        print(f"❌ Gagal mengirim ke Discord ({category}). Status: {response.status_code}, Respon: {response.text}")

def main():
    client = ApifyClient(APIFY_API_TOKEN)
    posted_tweets = load_posted_tweets()
    
    all_accounts = list(set(ACCOUNTS_LOKER + ACCOUNTS_MAGANG))
    print(f"🔍 Menjalankan Apify Scraper untuk {len(all_accounts)} akun...")

    # Memperhitungkan batas maxItems agar setiap akun mendapat jatah data yang cukup
    calculated_max_items = len(all_accounts) * (MAX_POSTS_PER_ACCOUNT + 5)

    run_input = {
        "twitterHandles": all_accounts,
        "maxItems": calculated_max_items,
        "sort": "Latest"
    }

    try:
        run = client.actor("apidojo/tweet-scraper").call(run_input=run_input)
        dataset_id = run["defaultDatasetId"]
        items = client.dataset(dataset_id).iterate_items()
    except Exception as e:
        print(f"⚠️ Gagal menjalankan Apify actor: {e}")
        return

    # Inisialisasi pengelompokan akun dengan lowercase agar tidak miss match
    account_posts = {acc.lower(): [] for acc in all_accounts}
    
    for item in items:
        # Menangani berbagai struktur penarikan username dari Apify
        author_obj = item.get("author", {})
        author_username = (
            author_obj.get("userName") or 
            author_obj.get("username") or 
            item.get("twitterHandle") or 
            ""
        ).lower().replace("@", "")

        if author_username in account_posts:
            account_posts[author_username].append(item)

    # Proses postingan per masing-masing akun dengan batas MAX_POSTS_PER_ACCOUNT
    for account, posts in account_posts.items():
        limited_posts = posts[:MAX_POSTS_PER_ACCOUNT]
        print(f"✨ Memproses {len(limited_posts)} postingan terbaru dari @{account}")
        
        for item in limited_posts:
            tweet_id = str(item.get("id") or item.get("tweetId") or "")
            if not tweet_id or tweet_id in posted_tweets:
                continue

            text = (item.get("text") or item.get("full_text") or "").lower()
            original_text = item.get("text") or item.get("full_text") or ""
            
            tweet_url = item.get("url") or f"https://twitter.com/{account}/status/{tweet_id}"

            is_loker = account in [acc.lower() for acc in ACCOUNTS_LOKER] or any(kw in text for kw in LOKER_KEYWORDS)
            is_magang = account in [acc.lower() for acc in ACCOUNTS_MAGANG] or any(kw in text for kw in MAGANG_KEYWORDS)

            sent = False
            if is_loker:
                send_to_discord(DISCORD_WEBHOOK_LOKER, original_text, tweet_url, "loker", ROLE_ID_LOKER)
                sent = True

            if is_magang:
                send_to_discord(DISCORD_WEBHOOK_MAGANG, original_text, tweet_url, "magang", ROLE_ID_MAGANG)
                sent = True

            if sent:
                save_posted_tweet(tweet_id, posted_tweets)

    print("🎉 Selesai memproses dataset Apify.")

if __name__ == "__main__":
    main()
