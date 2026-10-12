import feedparser
import requests
import json
import os

# ==========================================
# 1. KONFIGURASI DISCORD & ROLE MENTION (VIA ENVIRONMENT VARIABLES)
# ==========================================
DISCORD_WEBHOOK_LOKER = os.getenv("DISCORD_WEBHOOK_LOKER")
DISCORD_WEBHOOK_MAGANG = os.getenv("DISCORD_WEBHOOK_MAGANG")

ROLE_ID_LOKER = os.getenv("ROLE_ID_LOKER", "")
ROLE_ID_MAGANG = os.getenv("ROLE_ID_MAGANG", "")

# ==========================================
# 2. KONFIGURASI AKUN & KEYWORDS
# ==========================================
ACCOUNTS_LOKER = ["lokerdotid", "lokerjogjax", "jogjalowker", "disiniloker", "magnecareer", "twitlowongan", "sobatmagang_id"]
ACCOUNTS_MAGANG = ["sobatmagang_id", "disiniloker", "magnecareer"]

LOKER_KEYWORDS = [kw.lower() for kw in ["#InfoLoker", "#Loker", "INFO LOKER", "#lowker", "#lowongan", "Loker Jogja", "#LokerPam", "#Lowongan"]]
MAGANG_KEYWORDS = [kw.lower() for kw in ["#infoMagang", "#magangID", "#magangYuk", "#magang", "#MagangPam"]]

LOG_FILE = "posted_tweets.json"

# ==========================================
# 3. PENCEGAHAN DUPLIKASI (LOG DATABASE)
# ==========================================
def load_posted_tweets():
    """Membaca daftar ID tweet yang sudah pernah dikirim."""
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_posted_tweet(tweet_id, posted_list):
    """Menyimpan ID tweet baru ke file JSON log."""
    if tweet_id not in posted_list:
        posted_list.append(tweet_id)
        with open(LOG_FILE, "w") as f:
            json.dump(posted_list, f)

# ==========================================
# 4. INTEGRASI DISCORD WEBHOOK + MENTION ROLE
# ==========================================
def send_to_discord(webhook_url, text, link, category, role_id):
    """Mengirim pesan embed ke channel Discord disertai mention role."""
    if not webhook_url:
        print(f"⚠️ Webhook URL untuk kategori {category} belum diatur di Environment Variables.")
        return

    role_mention = f"<@&{role_id}>" if role_id else ""
    
    embed = {
        "title": f"📢 Lowongan Kategori: {category.upper()}",
        "description": text,
        "url": link,
        "color": 3447003 if category == "loker" else 15158332  # Biru (Loker), Merah (Magang)
    }
    
    payload = {
        "content": f"Info baru buat teman-teman! {role_mention}".strip(),
        "embeds": [embed]
    }
    
    response = requests.post(webhook_url, json=payload)
    if response.status_code in [200, 204]:
        print(f"✅ Berhasil mengirim postingan ke channel {category}")
    else:
        print(f"❌ Gagal mengirim ke Discord ({category}). Status: {response.status_code}")

# ==========================================
# 5. FUNGSI UTAMA (SCRAPING & ROUTING)
# ==========================================
def main():
    posted_tweets = load_posted_tweets()
    all_accounts = list(set(ACCOUNTS_LOKER + ACCOUNTS_MAGANG))
    
    for account in all_accounts:
        # Menggunakan Xcancel RSS Feed sebagai sumber alternatif
        rss_url = f"https://xcancel.com/{account}/rss"
        feed = feedparser.parse(rss_url)
        
        for entry in feed.entries:
            tweet_link = entry.link
            
            try:
                tweet_id = tweet_link.split('/')[-1].replace('#m', '')
            except Exception:
                continue
            
            # Cek duplikasi di log lokal
            if not tweet_id or tweet_id in posted_tweets:
                continue
                
            text = entry.title.lower()
            original_text = entry.title
            
            # Mekanisme Routing Kategori
            is_loker = account in ACCOUNTS_LOKER or any(kw in text for kw in LOKER_KEYWORDS)
            is_magang = account in ACCOUNTS_MAGANG or any(kw in text for kw in MAGANG_KEYWORDS)
            
            sent = False
            
            if is_loker:
                send_to_discord(DISCORD_WEBHOOK_LOKER, original_text, tweet_link, "loker", ROLE_ID_LOKER)
                sent = True
                
            if is_magang:
                send_to_discord(DISCORD_WEBHOOK_MAGANG, original_text, tweet_link, "magang", ROLE_ID_MAGANG)
                sent = True
                
            # Catat ID jika berhasil terkirim ke channel terkait
            if sent:
                save_posted_tweet(tweet_id, posted_tweets)

if __name__ == "__main__":
    main()
