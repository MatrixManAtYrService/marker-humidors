from __future__ import annotations

import re
from pathlib import Path

import pytest

from humidor.config import DEFAULT_CARD_MESSAGE, Config, ConfigError, check_label, load_config, slug
from humidor.qrcard import MODULE_PX, make_card, render, write_sheet


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Chucho", "chucho"),
        ("chucho", "chucho"),
        ("Big Blue (2)", "big-blue-2"),
        ("Chuchó", "chucho"),
        ("  Dr. Ruiz's box ", "dr-ruiz-s-box"),
        ("!!!", ""),
    ],
)
def test_slug(name, expected):
    assert slug(name) == expected


def test_labels_are_normalised_and_checked():
    assert check_label("  Big   Blue ") == "Big Blue"
    assert check_label("Chuchó") == "Chuchó"
    with pytest.raises(ConfigError):
        check_label("<script>")


def test_card_message_flows_into_paragraphs():
    paragraphs = Config(Path("."), "").message_for("Chucho")
    assert paragraphs[0] == "This is a marker humidor. Its name is Chucho."
    assert paragraphs[1].startswith("Seal markers inside") and paragraphs[1].endswith("markers are submerged.")
    assert paragraphs[2].startswith("The humidor will not restore dry markers")
    assert len(paragraphs) == 3


def test_card_message_comes_from_humidor_toml(tmp_path):
    (tmp_path / "humidor.toml").write_text('card_message = """\nHi from {name}.\n"""\n')
    assert load_config(tmp_path).message_for("Big Blue") == ["Hi from Big Blue."]
    assert load_config(Path(__file__).parent.parent).card_message.strip() == DEFAULT_CARD_MESSAGE.strip()


def test_sheet_stacks_the_message_under_the_qr_card():
    card = make_card("https://example.test/s/marker-humidor-chucho/", "humidor name: Chucho", "scan to leave feedback")
    qr_only = render(card, [])
    sheet = render(card, Config(Path("."), "").message_for("Chucho"))
    assert qr_only.width == sheet.width == card.size * MODULE_PX
    assert qr_only.height == round(card.height * MODULE_PX) < sheet.height
    # The QR card is identical whether or not a message is attached, apart from the cut lines.
    top = sheet.crop((4, 4, sheet.width - 4, qr_only.height - 4))
    assert top.tobytes() == qr_only.crop((4, 4, qr_only.width - 4, qr_only.height - 4)).tobytes()


def test_sheet_prints_105mm_wide_on_one_letter_or_a4_page(tmp_path):
    from PIL import Image

    paths = write_sheet("https://example.test/", "a", "b", ["c"], tmp_path, "x")
    png = Image.open(paths["image"])
    assert abs(png.width / png.info["dpi"][0] * 25.4 - 105) < 0.5

    pdf = Path(paths["print"]).read_bytes()
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") <= 1
    width_pt, height_pt = (float(v) for v in re.search(rb"/MediaBox \[ ?0 0 ([\d.]+) ([\d.]+)", pdf).groups())
    assert width_pt <= 595.3 and height_pt <= 792  # fits A4 width and Letter height, so neither printer rescales


def test_long_urls_wrap_inside_the_card():
    from PIL import ImageFont

    from humidor.qrcard import _wrap

    font = ImageFont.load_default(size=40)
    url = "https://www.ifixit.com/Guide/How+to+Restore++An+Expo+Marker/146008"
    lines = _wrap(f"or visit {url}", font, 500)
    assert all(font.getlength(line) <= 500 for line in lines)
    assert "".join(lines).replace(" ", "") == f"orvisit{url}"
    assert any(line.endswith("/") for line in lines)  # prefers breaking after a slash
