"""هوية منشورات القناة: شريط الهوية أسفل الصورة، وبطاقة بديلة للمقالات بلا صورة بارزة.

يعتمد على تشكيل النص العربي عبر libraqm في Pillow؛ بدونها تظهر الحروف العربية مفككة،
لذلك يتوقف السكربت برسالة واضحة إذا لم تتوفر بدل أن ينشر صورة مشوهة.
"""
from __future__ import annotations

import io
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

ASSETS = Path(__file__).resolve().parent / "assets"
FONT_DIR = ASSETS / "fonts"
LOGO_PATH = ASSETS / "logo.png"

INK = (24, 39, 64)          # نص داكن على الشريط الأبيض
MUTED = (110, 122, 140)     # نص ثانوي
STRIP_BG = (255, 255, 255)

CARD_W, CARD_H = 1200, 630
TELEGRAM_MAX_SIDE = 2560    # يكفي لجودة العرض ويُبقي الملف بعيداً عن حد 10MB


def require_raqm() -> None:
    if not features.check("raqm"):
        raise RuntimeError(
            "Pillow بلا دعم libraqm: لا يمكن تشكيل النص العربي. "
            "ثبّت libraqm0 و libfribidi0 (apt) ثم أعد تثبيت Pillow."
        )


@lru_cache(maxsize=None)
def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / f"ToshA-{weight}.ttf"), size,
                              layout_engine=ImageFont.Layout.RAQM)


@lru_cache(maxsize=1)
def _logo() -> Image.Image:
    return Image.open(LOGO_PATH).convert("RGBA")


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return draw.textlength(text, font=font, direction="rtl", language="ar")


def _fit(draw, text: str, weight: str, size: int, max_w: float, min_size: int):
    """أكبر حجم خط (لا يتجاوز size) يجعل السطر ضمن max_w؛ وإلا يقص النص بعلامة حذف."""
    while size > min_size and _text_w(draw, text, _font(weight, size)) > max_w:
        size -= 1
    font = _font(weight, size)
    if _text_w(draw, text, font) <= max_w:
        return text, font
    words = text.split()
    while len(words) > 1 and _text_w(draw, " ".join(words) + "…", font) > max_w:
        words.pop()
    return " ".join(words) + "…", font


def _wrap(draw, text: str, font, max_w: float, max_lines: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if _text_w(draw, trial, font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while _text_w(draw, last + "…", font) > max_w and " " in last:
            last = last.rsplit(" ", 1)[0]
        lines[-1] = last + "…"
    return lines


def add_strip(img: Image.Image, section: str, label: str, color: str,
              site_host: str) -> Image.Image:
    """يضيف شريط هوية أبيض أسفل الصورة: الشعار يميناً، ثم القسم، واسم الموقع يساراً.

    ارتفاع الشريط وأحجام الخطوط تتناسب مع عرض الصورة، فيبقى الشكل ثابتاً لأي مقاس.
    """
    img = img.convert("RGB")
    W, H = img.size
    strip_h = max(64, round(W * 0.075))
    accent_h = max(3, round(strip_h * 0.06))
    out = Image.new("RGB", (W, H + strip_h), STRIP_BG)
    out.paste(img, (0, 0))
    d = ImageDraw.Draw(out)
    d.rectangle([0, H, W, H + accent_h], fill=_hex(color))

    pad = round(strip_h * 0.32)
    inner_top = H + accent_h
    inner_h = strip_h - accent_h
    cy = inner_top + inner_h / 2

    logo = _logo()
    lh = round(inner_h * 0.62)
    lw = round(logo.width * lh / logo.height)
    logo_r = logo.resize((lw, lh), Image.LANCZOS)
    lx = W - pad - lw
    out.paste(logo_r, (lx, round(cy - lh / 2)), logo_r)

    sep_x = lx - round(pad * 0.8)
    d.line([sep_x, cy - inner_h * 0.28, sep_x, cy + inner_h * 0.28],
           fill=(214, 220, 230), width=max(1, round(strip_h * 0.02)))

    host_font = _font("Regular", round(inner_h * 0.24))
    host_w = d.textlength(site_host, font=host_font)
    d.text((pad, cy), site_host, font=host_font, fill=MUTED, anchor="lm")

    text_right = sep_x - round(pad * 0.8)
    max_w = text_right - (pad + host_w + pad)
    line = section if not label or label == section else f"{section}  ›  {label}"
    line, font = _fit(d, line, "Medium", round(inner_h * 0.30), max_w,
                      round(inner_h * 0.20))
    d.text((text_right, cy), line, font=font, fill=_hex(color), anchor="rm",
           direction="rtl", language="ar")
    return out


def make_card(title: str, section: str, label: str, color: str,
              site_host: str) -> Image.Image:
    """بطاقة بديلة للمقال الذي لا يملك صورة بارزة: لون القسم وعنوان المقال ونمط موجي محسوب."""
    body_h = CARD_H - round(CARD_W * 0.075)
    base = _hex(color)
    img = Image.new("RGB", (CARD_W, body_h), base)
    d = ImageDraw.Draw(img, "RGBA")

    # تدرج خطي خفيف من أعلى اليمين
    for y in range(body_h):
        k = y / body_h
        shade = tuple(max(0, int(c * (1.08 - 0.30 * k))) for c in base)
        d.line([(0, y), (CARD_W, y)], fill=shade)

    # نمط تداخل موجتين (مجموع جيبين بطولين موجيين مختلفين) على يسار البطاقة
    for j in range(7):
        pts = []
        for x in range(0, CARD_W // 2 + 1, 4):
            phase = x / CARD_W * 2 * math.pi
            y = (body_h * (0.22 + 0.09 * j)
                 + 18 * math.sin(5.0 * phase + 0.6 * j)
                 + 10 * math.sin(8.3 * phase - 0.4 * j))
            pts.append((x, y))
        d.line(pts, fill=(255, 255, 255, 34), width=2)

    margin = 72
    max_w = CARD_W * 0.62
    right = CARD_W - margin

    lab = label if label and label != section else section
    lab, lab_font = _fit(d, lab, "Medium", 30, max_w, 22)
    d.text((right, margin + 10), lab, font=lab_font, fill=(255, 255, 255, 200),
           anchor="ra", direction="rtl", language="ar")

    for size in (68, 60, 52, 46):
        tf = _font("Bold", size)
        lines = _wrap(d, title, tf, max_w, 3)
        if len(lines) <= 3 and not lines[-1].endswith("…"):
            break
    lh = round(tf.size * 1.45)
    y0 = body_h / 2 - (len(lines) * lh) / 2 + 30
    for i, ln in enumerate(lines):
        d.text((right, y0 + i * lh), ln, font=tf, fill=(255, 255, 255),
               anchor="ra", direction="rtl", language="ar")

    return add_strip(img, section, label, color, site_host)


def prepare_photo(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    if max(img.size) > TELEGRAM_MAX_SIDE:
        img.thumbnail((TELEGRAM_MAX_SIDE, TELEGRAM_MAX_SIDE), Image.LANCZOS)
    return img


def to_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, optimize=True, progressive=True)
    return buf.getvalue()
