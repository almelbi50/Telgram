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

def load_published_history():
    """تحميل سجل الروابط التي تم نشرها سابقاً لمنع التكرار"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_to_history(link):
    """إضافة الرابط الجديد إلى سجل التاريخ"""
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")

def clean_html(raw_html):
    """تنظيف النصوص وفك ترميز رموز HTML وإعدادها للتلقرام"""
    decoded_html = html.unescape(raw_html)
    clean_text = re.sub(r'<[^>]+>', '', decoded_html)
    clean_text = clean_text.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace('`', '\\`')
    return clean_text.strip()[:150] + "..."

def publish_to_telegram(title, link, summary, is_archive=False):
    clean_summary = clean_html(summary)
    clean_title = html.unescape(title)
    
    # تخصيص عنوان المنشور بناءً على نوعه (جديد أم من الأرشيف)
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
    
    response = requests.post(url, json=payload)
    return response.status_code == 200

def main():
    feed = feedparser.parse(FEED_URL)
    if not feed.entries:
        print("خلاصة الموقع فارغة حالياً.")
        return

    published_history = load_published_history()
    
    # 1. التحقق أولاً من وجود مقال جديد تماماً نُشر الآن على الموقع
    latest_entry = feed.entries[0]
    if latest_entry.link not in published_history:
        print(f"تم رصد مقال جديد تماماً: {latest_entry.title}")
        success = publish_to_telegram(latest_entry.title, latest_entry.link, latest_entry.summary, is_archive=False)
        if success:
            save_to_history(latest_entry.link)
            print("تم نشر المقال الجديد بنجاح.")
        return

    # 2. إذا لم يكن هناك مقال جديد، فالبوت يبحث عن المقالات القديمة غير المنشورة في السجل
    print("لا توجد مقالات حصرية جديدة. فحص الأرشيف المتاح في الخلاصة...")
    unpublications = [entry for entry in feed.entries if entry.link not in published_history]
    
    if unpublications:
        # اختيار مقال عشوائي من المقالات السابقة المتاحة في الخلاصة والتي لم تنشر بالقناة
        archive_entry = random.choice(unpublications)
        print(f"جاري إعادة نشر مقال من الأرشيف: {archive_entry.title}")
        
        success = publish_to_telegram(archive_entry.title, archive_entry.link, archive_entry.summary, is_archive=True)
        if success:
            save_to_history(archive_entry.link)
            print("تم نشر المقال الأرشيفي بنجاح وتحديث السجل.")
    else:
        print("كل المقالات المتاحة حالياً في الخلاصة تم نشرها مسبقاً في القناة.")

if __name__ == "__main__":
    main()
