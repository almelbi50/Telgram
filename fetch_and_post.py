import os
import requests
import feedparser
import re
import html
import random

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
FEED_URL = "https://phy-lab.com/feed"
HISTORY_FILE = "published_links.txt"

def normalize_url(url):
    """تنظيف الرابط وإزالة الفروق الطفيفة مثل العلامة المائلة في النهاية"""
    if not url:
        return ""
    url = url.strip().lower()
    if url.endswith('/'):
        url = url[:-1]
    return url

def load_published_history():
    """تحميل سجل الروابط المنشورة وتنظيفها تماماً"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(normalize_url(line) for line in f if line.strip())
    return set()

def save_to_history(link):
    """حفظ الرابط بعد تنظيفه في السجل لمنع التكرار"""
    normalized = normalize_url(link)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(normalized + "\n")

def clean_html(raw_html):
    """فك ترميز الرموز الخاصة وإزالة وسوم الـ HTML"""
    decoded_html = html.unescape(raw_html)
    clean_text = re.sub(r'<[^>]+>', '', decoded_html)
    # حماية رموز الماركداون الخاصة بالتليجرام
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

    published_history = load_published_history()
    
    # 1. التحقق من المقال الأحدث تماماً بالموقع
    latest_entry = feed.entries[0]
    normalized_latest_link = normalize_url(latest_entry.link)
    
    if normalized_latest_link not in published_history:
        print(f"تم رصد مقال جديد تماماً: {latest_entry.title}")
        success = publish_to_telegram(latest_entry.title, latest_entry.link, latest_entry.summary, is_archive=False)
        if success:
            save_to_history(latest_entry.link)
            print("تم نشر المقال الجديد بنجاح.")
        return

    # 2. إذا كان المقال الأحدث منشراً بالفعل، يبحث في الأرشيف المتاح بالخلاصة
    print("المقال الأحدث مسجل مسبقاً. فحص بقية مقالات الأرشيف في الخلاصة...")
    unpublications = [entry for entry in feed.entries if normalize_url(entry.link) not in published_history]
    
    if unpublications:
        archive_entry = random.choice(unpublications)
        print(f"جاري سحب مقال من الأرشيف: {archive_entry.title}")
        
        success = publish_to_telegram(archive_entry.title, archive_entry.link, archive_entry.summary, is_archive=True)
        if success:
            save_to_history(archive_entry.link)
            print("تم نشر المقال الأرشيفي بنجاح وتحديث سجل الأمان.")
    else:
        print("كل المقالات المتوفرة حالياً في الخلاصة تم نشرها بالكامل من قبل.")

if __name__ == "__main__":
    main()
