"""The printable sheet for a humidor: two cards stacked in one PNG, sharing an edge.

    +---------------------------+
    |   humidor name: Chucho    |
    |        [QR code]          |    QR card
    |  scan to leave feedback   |
    +---------------------------+    <- cut here
    | This is a marker humidor. |
    | Its name is Chucho. ...   |    message card (card_message in humidor.toml)
    +---------------------------+

Thin dashed lines mark where to cut. Two files are written:

    <stem>.pdf   for printing: one page that fits Letter and A4, with the sheet
                 105 mm wide in the top-left corner. Print at 100% / actual size.
    <stem>.png   the same sheet as an image, for screens. Most browsers and
                 viewers ignore its print size, so printing it can come out huge.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import segno

QUIET = 4  # modules of white border around the code, per the QR spec
MODULE_PX = 30  # PNG pixels per module (about 330 dpi at PRINT_WIDTH_MM)
PRINT_WIDTH_MM = 105
CUT_DASH = (12, 10)  # cut lines: dash and gap lengths, in PNG pixels
# The PDF page: the narrower of A4 and the shorter of Letter, so it prints on either unscaled.
PAGE_MM = (210, 279)
PAGE_MARGIN_MM = 12


@dataclass
class Card:
    top: str
    bottom: str
    modules: list[list[bool]]

    @property
    def size(self) -> int:
        """Width of the square code area (with quiet zone), in modules."""
        return len(self.modules) + 2 * QUIET

    # Layout, in modules: a text band above and below the code.
    @property
    def top_band(self) -> float:
        return 4.0

    @property
    def bottom_band(self) -> float:
        return 3.5

    @property
    def height(self) -> float:
        return self.top_band + self.size + self.bottom_band

    @property
    def font(self) -> float:
        # Fit the longer line in ~90% of the width (sans-serif averages ~0.55 em per character).
        longest = max(len(self.top), len(self.bottom))
        return min(2.2, 0.9 * self.size / (0.55 * longest))

    def dark(self) -> list[tuple[int, int]]:
        return [(x, y) for y, row in enumerate(self.modules) for x, on in enumerate(row) if on]


def make_card(url: str, top: str, bottom: str) -> Card:
    qr = segno.make(url, error="m")
    return Card(top, bottom, [[bool(v) for v in row] for row in qr.matrix])


def _split_long(word: str, font: Any, width: float) -> list[str]:
    """Break a word too wide for a line (e.g. a URL) into pieces that fit,
    preferring to break just after a '/'."""
    pieces: list[str] = []
    while font.getlength(word) > width:
        fit = max(n for n in range(1, len(word) + 1) if font.getlength(word[:n]) <= width or n == 1)
        slash = word.rfind("/", 0, fit)
        cut = slash + 1 if slash > 0 else fit
        pieces.append(word[:cut])
        word = word[cut:]
    return [*pieces, word]


def _wrap(text: str, font: Any, width: float) -> list[str]:
    """Break text into lines no wider than width. An empty text stays one empty line."""
    lines: list[str] = []
    current = ""
    words = [piece for word in text.split() for piece in _split_long(word, font, width)]
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    lines.append(current)
    return lines


def render(card: Card, message: list[str]) -> Any:
    """The sheet as a Pillow image: the QR card, then the message card below it.
    message is a list of paragraphs; with none, the sheet is just the QR card."""
    from PIL import Image, ImageDraw, ImageFont

    px = MODULE_PX
    width = card.size * px
    qr_height = round(card.height * px)
    font = ImageFont.load_default(size=card.font * px)

    margin = QUIET * px
    line_h = card.font * px * 1.4
    gap = line_h * 0.6  # between paragraphs
    paragraphs = [_wrap(text, font, width - 2 * margin) for text in message]
    lines = sum(len(p) for p in paragraphs)
    message_height = round(2 * margin + lines * line_h + (len(paragraphs) - 1) * gap) if paragraphs else 0

    img = Image.new("L", (width, qr_height + message_height), 255)
    draw = ImageDraw.Draw(img)

    oy = card.top_band + QUIET
    for x, y in card.dark():
        x0, y0 = (QUIET + x) * px, round((oy + y) * px)
        draw.rectangle([x0, y0, x0 + px - 1, y0 + px - 1], fill=0)
    centre = width / 2
    draw.text((centre, (card.top_band - 0.6) * px), card.top, font=font, fill=0, anchor="ms")
    draw.text(
        (centre, (card.top_band + card.size + card.bottom_band - 1.4) * px), card.bottom, font=font, fill=0, anchor="ms"
    )

    y = qr_height + margin
    for paragraph in paragraphs:
        for line in paragraph:
            draw.text((margin, y), line, font=font, fill=0)
            y += line_h
        y += gap

    # Cut lines: around the sheet, and along the edge the two cards share.
    right, bottom = width - 1, img.height - 1
    for start, end in [
        ((0, 0), (right, 0)),
        ((right, 0), (right, bottom)),
        ((0, bottom), (right, bottom)),
        ((0, 0), (0, bottom)),
    ]:
        _dashed(draw, start, end)
    if paragraphs:
        _dashed(draw, (0, qr_height), (right, qr_height))
    return img


def _dashed(draw: Any, start: tuple[int, int], end: tuple[int, int]) -> None:
    """A dashed black line along one axis (the sheet only needs horizontal and vertical ones)."""
    dash, gap = CUT_DASH
    (x0, y0), (x1, y1) = start, end
    length = max(abs(x1 - x0), abs(y1 - y0))
    for d in range(0, length + 1, dash + gap):
        e = min(d + dash, length)
        if y0 == y1:
            draw.line([(x0 + d, y0), (x0 + e, y0)], fill=0, width=2)
        else:
            draw.line([(x0, y0 + d), (x0, y0 + e)], fill=0, width=2)


def page(sheet: Any, dpi: float) -> Any:
    """A PAGE_MM page with the sheet at actual size in its top-left corner."""
    from PIL import Image

    def to_px(mm: float) -> int:
        return round(mm / 25.4 * dpi)

    canvas = Image.new("L", (to_px(PAGE_MM[0]), to_px(PAGE_MM[1])), 255)
    canvas.paste(sheet, (to_px(PAGE_MARGIN_MM), to_px(PAGE_MARGIN_MM)))
    # Pure black and white, so the PDF stores it losslessly (CCITT) rather than as a blurry JPEG.
    return canvas.convert("1", dither=Image.Dither.NONE)


def write_sheet(url: str, top: str, bottom: str, message: list[str], out_dir: Path, stem: str) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    img = render(make_card(url, top, bottom), message)
    dpi = img.width / (PRINT_WIDTH_MM / 25.4)
    png, pdf = out_dir / f"{stem}.png", out_dir / f"{stem}.pdf"
    img.save(png, dpi=(dpi, dpi))
    page(img, dpi).save(pdf, resolution=dpi)
    return {"print": str(pdf), "image": str(png)}
