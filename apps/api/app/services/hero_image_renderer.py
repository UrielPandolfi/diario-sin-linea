from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1200
HEIGHT = 630
MAX_HEADLINE_LINES = 5
MAX_FONT_SIZE = 56
MIN_FONT_SIZE = 28
LINE_SPACING = 1.18

BACKGROUND = "#111315"
BORDER = "#2A2E33"
TEXT_PRIMARY = "#ECE8DF"
TEXT_SECONDARY = "#A0A6AC"
ACCENT_PETROL = "#4E6B66"
ACCENT_OCHRE = "#A8844F"

FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "OpenSans-SemiBold.ttf"
BRAND = "SIN LÍNEA"


def load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


def line_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return max(1, int((ascent + descent) * LINE_SPACING))


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    draw = ImageDraw.Draw(Image.new("RGB", (max_width, 64), BACKGROUND))
    words = (text or "").replace("\n", " ").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        if draw.textlength(word, font=font) <= max_width:
            current = word
            continue
        chunk = ""
        for char in word:
            next_chunk = chunk + char
            if chunk and draw.textlength(next_chunk, font=font) > max_width:
                lines.append(chunk)
                chunk = char
            else:
                chunk = next_chunk
        current = chunk
    if current:
        lines.append(current)
    return lines or [""]


def ellipsize(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    draw = ImageDraw.Draw(Image.new("RGB", (max_width, 64), BACKGROUND))
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    trimmed = text
    while trimmed and draw.textlength(trimmed + ellipsis, font=font) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


def fit_headline(
    text: str,
    *,
    max_width: int,
    max_height: int,
    max_lines: int = MAX_HEADLINE_LINES,
) -> tuple[list[str], ImageFont.FreeTypeFont]:
    headline = (text or "").strip() or " "
    chosen_lines = [headline]
    chosen_font = load_font(MIN_FONT_SIZE)
    for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -2):
        font = load_font(size)
        lines = wrap_text(headline, font, max_width)
        height = line_height(font) * len(lines)
        if len(lines) <= max_lines and height <= max_height:
            return lines, font
        chosen_lines = lines
        chosen_font = font
    if len(chosen_lines) > max_lines:
        overflow = " ".join(chosen_lines[max_lines - 1 :])
        chosen_lines = chosen_lines[: max_lines - 1] + [ellipsize(overflow, chosen_font, max_width)]
    while line_height(chosen_font) * len(chosen_lines) > max_height and len(chosen_lines) > 1:
        chosen_lines = chosen_lines[:-1]
        chosen_lines[-1] = ellipsize(chosen_lines[-1], chosen_font, max_width)
    if chosen_lines:
        chosen_lines[-1] = ellipsize(chosen_lines[-1], chosen_font, max_width)
    return chosen_lines, chosen_font


class TemplateHeroRenderer:
    def render(self, *, headline: str, locality: str | None) -> bytes:
        image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 8, HEIGHT), fill=ACCENT_PETROL)
        draw.rectangle((8, 0, WIDTH, 1), fill=BORDER)

        pad_x = 72
        pad_top = 56
        content_left = pad_x
        content_width = WIDTH - pad_x - 64
        y = pad_top

        place = (locality or "").strip()
        if place:
            kicker_font = load_font(18)
            kicker = ellipsize(place.upper(), kicker_font, content_width)
            draw.text((content_left, y), kicker, font=kicker_font, fill=ACCENT_OCHRE)
            y += line_height(kicker_font) + 18

        brand_font = load_font(16)
        brand_y = HEIGHT - 56
        headline_bottom = brand_y - 36
        lines, headline_font = fit_headline(
            headline,
            max_width=content_width,
            max_height=max(headline_bottom - y, line_height(load_font(MIN_FONT_SIZE))),
        )
        for line in lines:
            if y + line_height(headline_font) > headline_bottom:
                break
            draw.text((content_left, y), line, font=headline_font, fill=TEXT_PRIMARY)
            y += line_height(headline_font)

        draw.text((content_left, brand_y), BRAND, font=brand_font, fill=TEXT_SECONDARY)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True, compress_level=9)
        return buffer.getvalue()
