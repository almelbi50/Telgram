import os
import requests
import feedparser
import re
import html
import random
from datetime import datetime

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
FEED_URL = "https://phy-lab.com/feed"
HISTORY_FILE = "published_links.txt"

def normalize_url(url):
    if not url:
        return ""
    url = url.strip().lower()
    if url.endswith('/'):
        url = url[:-1]
    return url

def load_published_history():
    """تحميل سجل الروابط المنشورة"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return []

def get_archive_count_today(history_lines):
    """حساب كم مقال أرشيفي تم نشره هذا اليوم"""
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    count = 0
    for line in history_lines:
        if "|| archive ||" in line and today_str in line:
            count += 1
    return count

def save_to_history(link, is_archive=False):
    """حفظ الرابط مع تدوين تاريخ ونوع النشر للحسابات الذكية"""
    normalized = normalize_url(link)
    date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    type_str = "archive" if is_archive else "new"
    
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{normalized} || {type_str} || {date_str}\n")

def clean_html(raw_html):
    decoded_html = html.unescape(raw_html)
    clean_text = re.sub(r'<[^>]+>', '', decoded_html)
    clean_text = clean_text.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace('`', '\\`')
    return clean_text.strip()[:150] + "..."

def publish_to_telegram(title, link, summary, is_archive=False):
    clean_summary = clean_html(summary)
    clean_title = html.unescape(title)
    
    header = "🎯 *مقال علمي جديد في منصة معامل الفيزياء!*" if not is_archive else "📚 *من أرشيف معامل الفيزياء المتميزة*"
    
    message = (
        f"{header}\n\n"
        f"📝 *{clean_title}*\n\n"
        f"📖 {clean_summary}\n\n"
        f"👇 تفضلوا بزيارة المختبر الرقمي للمعاينة والتجربة:"
    )
    
    reply_markup = {
        "inline_keyboard": [
            [{"text": "عرض المحاكاة وقراءة المقال كاملاً 🌐", "url": link}]
        ]
    }
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": reply_markup,
        "disable_web_page_preview": False
    }
    
    try:
        response = requests.post(url, json=payload)
        return response.status_code == 200
    except Exception as e:
        print(f"حدث خطأ أثناء الاتصال بتليجرام: {e}")
        return False

def main():
    feed = feedparser.parse(FEED_URL)
    if not feed.entries:
        print("خلاصة الموقع فارغة حالياً.")
        return

    history_lines = load_published_history()
    # استخراج الروابط فقط للمقارنة البرمجية الكلاسيكية
    published_urls = set(normalize_url(line.split(" || ")[0]) for line in history_lines if line)
    
    # 1. فحص المقال الأحدث بالموقع (النشر الفوري للمقالات الجديدة مهما كان عددها)
    latest_entry = feed.entries[0]
    normalized_latest_link = normalize_url(latest_entry.link)
    
    if normalized_latest_link not in published_urls:
        print(f"تم رصد مقال جديد تماماً ينشر فوراً: {latest_entry.title}")
        success = publish_to_telegram(latest_entry.title, latest_entry.link, latest_entry.summary, is_archive=False)
        if success:
            save_to_history(latest_entry.link, is_archive=False)
            print("تم نشر المقال الجديد بنجاح فوري.")
        return

    # 2. خطة الأرشيف (بشرط ألا يتجاوز مقالين يومياً)
    archive_sent_today = get_archive_count_today(history_lines)
    print(f"عدد مقالات الأرشيف المرسلة اليوم حتى الآن: {archive_sent_today}/2")
    
    if archive_sent_today < 2:
        print("مسموح بنشر مقال أرشيفي. فحص خلاصة الأرشيف...")
        unpublications = [entry for entry in feed.entries if normalize_url(entry.link) not in published_urls]
        
        if unpublications:
            archive_entry = random.choice(unpublications)
            print(f"جاري سحب مقال من الأرشيف: {archive_entry.title}")
            
            success = publish_to_telegram(archive_entry.title, archive_entry.link, archive_entry.summary, is_archive=True)
            if success:
                save_to_history(archive_entry.link, is_archive=True)
                print("تم نشر المقال الأرشيفي بنجاح وتحديث عداد اليوم.")
        else:
            print("كل مقالات الأرشيف المتوفرة حالياً بالخلاصة تم نشرها بالكامل مسبقاً.")
    else:
        print("تم الوصول للحد الأقصى لنشر الأرشيف اليوم (مقالين). سيتم الفحص فقط للمقالات الجديدة الفورية.")

if __name__ == "__main__":
    main()
