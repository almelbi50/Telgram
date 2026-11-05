"""نشر منشور واحد يومياً من phy-lab.com إلى قناة تيليجرام.

الترتيب:
  1. إذا نُشر منشور اليوم (بتوقيت الرياض) يتوقف السكربت دون فعل شيء.
  2. أقدم مقال حديث (ضمن new_window_days) لم يُنشر في القناة يُنشر بوسم «جديد».
  3. وإلا يُختار مقال من الأرشيف من القسم الأطول غياباً عن القناة.
لا يُنشر أي مقال مرتين؛ التعرف بالرقم الثابت للمقال في ووردبريس.

متغيرات البيئة:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID  (مطلوبة إلا في وضع التجربة)
  DRY_RUN=1     يجهز المنشور ويحفظه في preview/ دون إرسال ودون تعديل السجل
  FORCE=1       يتجاوز حارس «منشور واحد يومياً» (للتشغيل اليدوي فقط)
  POST_ID=123   ينشر مقالاً محدداً بدل الاختيار التلقائي
"""
from __future__ import annotations

import html
import io
import json
import os
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

import requests
from PIL import Image

import branding

ROOT = Path(__file__).resolve().parent
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
CATMAP = json.loads((ROOT / "config" / "categories.json").read_text(encoding="utf-8"))
HISTORY_FILE = ROOT / "history.json"
LEGACY_FILE = ROOT / "published_links.txt"
PREVIEW_DIR = ROOT / "preview"

SITE = SETTINGS["site_url"].rstrip("/")
SITE_HOST = urlsplit(SITE).hostname
TZ = ZoneInfo(SETTINGS["timezone"])
UA = "PHY-LAB-TelegramSync/2.0 (+https://github.com/almelbi50/Telgram)"
HTTP_TIMEOUT = (10, 60)

session = requests.Session()
session.headers["User-Agent"] = UA


# ───────────────────────────── السجل ─────────────────────────────

def normalize_url(url: str) -> str:
    """صيغة موحدة للمقارنة: بلا بروتوكول ولا شرطة أخيرة، مع فك ترميز الحروف العربية."""
    parts = urlsplit((url or "").strip())
    path = unquote(parts.path).rstrip("/").lower()
    query = f"?{parts.query}" if parts.query else ""
    return f"{(parts.hostname or '').lower()}{path}{query}"


def load_history() -> dict:
    if HISTORY_FILE.exists():
        hist = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    else:
        hist = {}
    hist.setdefault("last_post_date", None)
    hist.setdefault("posts", {})
    hist.setdefault("legacy_urls", [])
    # ترحيل السجل القديم مرة واحدة إن وُجد
    if LEGACY_FILE.exists():
        legacy = set(hist["legacy_urls"])
        for line in LEGACY_FILE.read_text(encoding="utf-8").splitlines():
            url = line.split(" || ")[0].strip()
            if url:
                legacy.add(normalize_url(url))
        hist["legacy_urls"] = sorted(legacy)
    return hist


def save_history(hist: dict) -> None:
    HISTORY_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    if LEGACY_FILE.exists():
        LEGACY_FILE.unlink()


def is_published(post: dict, hist: dict, legacy: set[str]) -> bool:
    return str(post["id"]) in hist["posts"] or normalize_url(post["link"]) in legacy


# ───────────────────────────── الموقع ─────────────────────────────

def fetch_posts() -> list[dict]:
    posts, page = [], 1
    fields = "id,date_gmt,link,title,excerpt,categories,featured_media,_links,_embedded"
    while True:
        r = session.get(f"{SITE}/wp-json/wp/v2/posts",
                        params={"per_page": 100, "page": page,
                                "_embed": "wp:featuredmedia", "_fields": fields},
                        timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        batch = r.json()
        posts.extend(batch)
        if not batch or page >= int(r.headers.get("X-WP-TotalPages", page)):
            break
        page += 1
    if not posts:
        raise RuntimeError("واجهة ووردبريس أعادت قائمة مقالات فارغة")
    for p in posts:
        p["published_at"] = datetime.fromisoformat(p["date_gmt"]).replace(tzinfo=timezone.utc)
    return posts


def featured_image_url(post: dict) -> str | None:
    media = (post.get("_embedded") or {}).get("wp:featuredmedia") or []
    if not media or not isinstance(media[0], dict) or "source_url" not in media[0]:
        return None
    sizes = (media[0].get("media_details") or {}).get("sizes") or {}
    # أكبر مقاس لا يتجاوز 2048 بكسل؛ يكفي لتيليجرام ويختصر التحميل
    best = None
    for s in sizes.values():
        w = s.get("width", 0)
        if w <= 2048 and (best is None or w > best.get("width", 0)):
            best = s
    return (best or media[0])["source_url"]


# ───────────────────────────── التصنيف ─────────────────────────────

def classify(post: dict) -> dict:
    cats = CATMAP["categories"]
    ids = set(post.get("categories") or [])
    chosen = next((c for c in CATMAP["priority"] if c in ids and str(c) in cats), None)
    if chosen is None:
        chosen = next((c for c in sorted(ids) if str(c) in cats), None)
    if chosen is None:
        sec_key = CATMAP["default_section"]
        sec = CATMAP["sections"][sec_key]
        return {"section_key": sec_key, "section": sec["name"], "label": sec["name"],
                "color": sec["color"], "tags": [sec["tag"]], "simulation": False}
    entry = cats[str(chosen)]
    sec = CATMAP["sections"][entry["section"]]
    tags = [sec["tag"]]
    if entry["tag"] != sec["tag"]:
        tags.append(entry["tag"])
    simulation = any(cats.get(str(c), {}).get("simulation") for c in ids)
    return {"section_key": entry["section"], "section": sec["name"], "label": entry["label"],
            "color": sec["color"], "tags": tags, "simulation": simulation}


# ───────────────────────────── الملخص ─────────────────────────────

AR = "؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿"
AR_LETTER = "ؠ-يٮ-ۓۺ-ۿݐ-ݿ"   # حروف فقط، بلا علامات ترقيم


def _is_arabic_sentence(s: str) -> bool:
    letters = re.findall(f"[A-Za-z{AR}]", s)
    if not letters:
        return False
    ar = sum(1 for ch in letters if re.match(f"[{AR}]", ch))
    return ar / len(letters) >= 0.5


def clean_title(post: dict) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", post["title"]["rendered"]))).strip()


def make_summary(excerpt_html: str, title: str, limit: int) -> str:
    text = re.sub(r"<[^>]+>", " ", excerpt_html or "")
    text = html.unescape(text)
    text = re.sub(r"\[\s*(?:…|\.\.\.)\s*\]", " ", text)
    # كلمات ملتصقة عند حذف الوسوم: «لميليكانMillikan»، «t.تحسب»
    text = re.sub(f"([{AR_LETTER}])([A-Za-z])", r"\1 \2", text)
    text = re.sub(f"([A-Za-z0-9])([{AR_LETTER}])", r"\1 \2", text)
    text = re.sub(f"([.!؟?:،])([{AR_LETTER}A-Za-z])", r"\1 \2", text)
    text = re.sub(r"\s+", " ", text).strip()

    # حذف العنوان إن تكرر في أول الملخص، ثم العنوان الإنجليزي الذي يليه عادة
    if title and text.startswith(title):
        text = text[len(title):].lstrip(" :—-–|")
    text = re.sub(f"^[A-Za-z][A-Za-z0-9 ,'’()\\-–:&/]{{2,90}}?(?=\\s[{AR}])", "", text).strip()

    # الإبقاء على الجمل العربية فقط (ملخص بعض المقالات ثنائي اللغة)
    kept = []
    for s in re.split(r"(?<=[.!؟?])\s+", text):
        if _is_arabic_sentence(s):
            kept.append(s)
        elif kept:
            break
    if kept:
        text = " ".join(kept)
    text = text.rstrip(" …").strip()

    if len(text) > limit:
        cut = text[:limit]
        end = max(cut.rfind(". "), cut.rfind("؟ "))
        if end >= limit * 0.6:
            text = cut[:end + 1]
        else:
            text = cut.rsplit(" ", 1)[0].rstrip("،,;:-– ") + "…"
    return text


# ───────────────────────────── الاختيار ─────────────────────────────

def choose(posts: list[dict], hist: dict, now: datetime) -> tuple[dict, str] | None:
    legacy = set(hist["legacy_urls"])
    pending = [p for p in posts if not is_published(p, hist, legacy)]
    if not pending:
        return None

    window = now - timedelta(days=SETTINGS["new_window_days"])
    fresh = sorted((p for p in pending if p["published_at"] >= window),
                   key=lambda p: p["published_at"])
    if fresh:
        return fresh[0], "new"

    # آخر ظهور لكل قسم في القناة؛ القسم الذي لم يظهر بعد يأخذ الأولوية
    last_seen: dict[str, str] = {}
    for rec in hist["posts"].values():
        key = rec.get("section")
        if key and rec.get("date", "") > last_seen.get(key, ""):
            last_seen[key] = rec["date"]

    by_section: dict[str, list[dict]] = {}
    for p in pending:
        by_section.setdefault(classify(p)["section_key"], []).append(p)
    section = min(by_section, key=lambda k: (last_seen.get(k, ""), k))
    return random.choice(by_section[section]), "archive"


# ───────────────────────────── تيليجرام ─────────────────────────────

def build_caption(post: dict, info: dict, kind: str) -> str:
    e = html.escape
    title = clean_title(post)
    summary = make_summary(post["excerpt"]["rendered"], title, SETTINGS["summary_max_chars"])
    where = info["section"] if info["label"] == info["section"] \
        else f"{info['section']} › {info['label']}"

    def render(summ: str) -> str:
        parts = [f"{e(SETTINGS['labels'][kind])}  |  {e(where)}", f"<b>{e(title)}</b>"]
        if summ:
            parts.append(e(summ))
        parts.append("  ".join(f"#{t}" for t in info["tags"]))
        parts.append(f'<a href="{e(SITE)}">{e(SETTINGS["site_name"])} · {e(SITE_HOST)}</a>')
        return "\n\n".join(parts)

    caption = render(summary)
    while len(caption) > 1024 and summary:        # حد تيليجرام لتعليق الصورة
        summary = summary[:-40].rsplit(" ", 1)[0] + "…" if len(summary) > 40 else ""
        caption = render(summary)
    return caption


def build_image(post: dict, info: dict) -> bytes:
    url = featured_image_url(post)
    if url:
        try:
            r = session.get(url, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            img = branding.prepare_photo(Image.open(io.BytesIO(r.content)))
            name = urlsplit(url).path.rsplit("/", 1)[-1].lower()
            if not re.search(SETTINGS["branded_cover_pattern"], name):
                img = branding.add_strip(img, info["section"], info["label"],
                                         info["color"], SITE_HOST)
            return branding.to_jpeg(img)
        except Exception as exc:                  # صورة تالفة أو غير متاحة: نكمل بالبطاقة
            print(f"تعذر استخدام الصورة البارزة ({exc}); ستُستخدم بطاقة بديلة.")
    return branding.to_jpeg(branding.make_card(clean_title(post), info["section"],
                                               info["label"], info["color"], SITE_HOST))


def telegram(method: str, data: dict, files: dict | None = None) -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    r = session.post(f"https://api.telegram.org/bot{token}/{method}",
                     data=data, files=files, timeout=HTTP_TIMEOUT)
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} فشل ({r.status_code}): "
                           f"{body.get('description', r.text[:300])}")
    return body["result"]


def publish(post: dict, info: dict, caption: str, image: bytes) -> int:
    button = SETTINGS["labels"]["simulation_button" if info["simulation"] else "read_button"]
    markup = json.dumps({"inline_keyboard": [[{"text": button, "url": post["link"]}]]},
                        ensure_ascii=False)
    base = {"chat_id": os.environ["TELEGRAM_CHANNEL_ID"], "parse_mode": "HTML",
            "reply_markup": markup}
    try:
        res = telegram("sendPhoto", {**base, "caption": caption},
                       files={"photo": ("post.jpg", image, "image/jpeg")})
    except RuntimeError as exc:
        print(f"{exc}\nإعادة المحاولة كرسالة نصية مع معاينة الرابط.")
        res = telegram("sendMessage", {**base, "text": caption,
                                       "link_preview_options": json.dumps(
                                           {"url": post["link"], "prefer_large_media": True})})
    return res["message_id"]


# ───────────────────────────── التشغيل ─────────────────────────────

def main() -> int:
    branding.require_raqm()
    dry = os.getenv("DRY_RUN") == "1"
    force = os.getenv("FORCE") == "1"
    now = datetime.now(timezone.utc)
    today = now.astimezone(TZ).date().isoformat()

    hist = load_history()
    if hist["last_post_date"] == today and not force and not dry:
        print(f"نُشر منشور اليوم ({today}) مسبقاً؛ لا شيء لفعله.")
        return 0

    posts = fetch_posts()
    print(f"عدد مقالات الموقع: {len(posts)}")

    if os.getenv("POST_ID"):
        post = next((p for p in posts if str(p["id"]) == os.environ["POST_ID"]), None)
        if not post:
            raise RuntimeError(f"المقال {os.environ['POST_ID']} غير موجود")
        recent = post["published_at"] >= now - timedelta(days=SETTINGS["new_window_days"])
        kind = "new" if recent else "archive"
    else:
        picked = choose(posts, hist, now)
        if not picked:
            print("كل مقالات الموقع نُشرت في القناة؛ لا يوجد جديد ولا أرشيف متبقٍ.")
            return 0
        post, kind = picked

    info = classify(post)
    caption = build_caption(post, info, kind)
    image = build_image(post, info)
    print(f"المختار: [{kind}] {post['id']} — {clean_title(post)} — "
          f"{info['section']} › {info['label']}")

    if dry:
        PREVIEW_DIR.mkdir(exist_ok=True)
        (PREVIEW_DIR / f"{post['id']}.jpg").write_bytes(image)
        (PREVIEW_DIR / f"{post['id']}.html").write_text(caption, encoding="utf-8")
        print("وضع التجربة: حُفظت المعاينة في preview/ ولم يُرسل شيء.")
        return 0

    msg_id = publish(post, info, caption, image)
    hist["posts"][str(post["id"])] = {
        "date": now.astimezone(TZ).isoformat(timespec="seconds"),
        "type": kind,
        "section": info["section_key"],
        "message_id": msg_id,
        "url": post["link"],
    }
    hist["last_post_date"] = today
    save_history(hist)
    print(f"نُشر بنجاح (message_id={msg_id}).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"فشل التشغيل: {exc}", file=sys.stderr)
        sys.exit(1)
