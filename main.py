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
        if len(posted_list) > 500:
            posted_list = posted_list[-500:]
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

    # Konfigurasi input untuk Actor Apify (Menggunakan apidojo/tweet-scraper)
    run_input = {
        "twitterHandles": all_accounts,
        "maxItems": 40,  # Dibatasi 40 item total agar hemat kuota/kredit $5
        "sort": "Latest"
    }

    try:
        run = client.actor("apidojo/tweet-scraper").call(run_input=run_input)
        dataset_id = run["defaultDatasetId"]
        items = client.dataset(dataset_id).iterate_items()
    except Exception as e:
        print(f"⚠️ Gagal menjalankan Apify actor: {e}")
        return

    for item in items:
        tweet_id = str(item.get("id", ""))
        if not tweet_id or tweet_id in posted_tweets:
            continue

        text = (item.get("text") or item.get("full_text", "")).lower()
        original_text = item.get("text") or item.get("full_text", "")
        
        author_username = item.get("author", {}).get("userName", "").lower()
        tweet_url = item.get("url", f"https://twitter.com/{author_username}/status/{tweet_id}")

        is_loker = author_username in ACCOUNTS_LOKER or any(kw in text for kw in LOKER_KEYWORDS)
        is_magang = author_username in ACCOUNTS_MAGANG or any(kw in text for kw in MAGANG_KEYWORDS)

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
