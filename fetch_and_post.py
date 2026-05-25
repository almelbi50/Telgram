import os
import requests
import feedparser
import re

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
FEED_URL = "https://phy-lab.com/feed"
GUID_FILE = "last_guid.txt"

def get_last_guid():
    if os.path.exists(GUID_FILE):
        with open(GUID_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None

def update_last_guid(guid):
    with open(GUID_FILE, "w", encoding="utf-8") as f:
        f.write(guid)

def clean_html(raw_html):
    """تنظيف النص من وسوم HTML وتنسيق الرموز الخاصة لتجنب مشاكل التلجرام"""
    clean_text = re.sub(r'<[^>]+>', '', raw_html)
    # تنظيف الرموز التي قد تكسر تنسيق الماركداون في التلجرام
    clean_text = clean_text.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace('`', '\\`')
    return clean_text.strip()[:150] + "..."

def publish_to_telegram(title, link, summary):
    clean_summary = clean_html(summary)
    
    # صياغة النص بتنسيق تليجرام مدعوم
    message = (
        f"🎯 *مقال علمي جديد في منصة معامل الفيزياء!*\n\n"
        f"📝 *{title}*\n\n"
        f"📖 {clean_summary}\n\n"
        f"👇 تفضلوا بزيارة المختبر الرقمي للمعاينة والتجربة:"
    )
    
    # إضافة زر شفاف مدمج تحت المنشور للانتقال للموقع
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
        "disable_web_page_preview": False  # يتيح ظهور الصورة البارزة للمقال تلقائياً
    }
    
    response = requests.post(url, json=payload)
    return response.status_code == 200

def main():
    feed = feedparser.parse(FEED_URL)
    if not feed.entries:
        print("الخلاصة فارغة حالياً.")
        return

    latest_entry = feed.entries[0]
    latest_guid = latest_entry.id if hasattr(latest_entry, 'id') else latest_entry.link
    last_processed_guid = get_last_guid()
    
    if latest_guid != last_processed_guid:
        print(f"تم العثور على تحديث جديد: {latest_entry.title}")
        title = latest_entry.title
        link = latest_entry.link
        summary = latest_entry.summary if hasattr(latest_entry, 'summary') else ""
        
        success = publish_to_telegram(title, link, summary)
        if success:
            print("تم النشر بنجاح على التلجرام.")
            update_last_guid(latest_guid)
        else:
            print("فشل إرسال المنشور، يرجى التحقق من الصلاحيات أو التوكن.")
    else:
        print("لا توجد مقالات جديدة لنشرها.")

if __name__ == "__main__":
    main()
