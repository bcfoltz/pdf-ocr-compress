"""Shared pytest fixtures."""

import os

import pikepdf
import pytest

# Source-of-truth text rendered into image_paragraph_pdf. The fixture and
# the round-trip OCR fidelity test both reference this so we compare
# OCR output token count against what was actually rendered, not against
# whatever pdfminer can pull from the image-only input (which is zero).
PARAGRAPH_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "Pack my box with five dozen liquor jugs. "
    "How vexingly quick daft zebras jump. "
    "Sphinx of black quartz judge my vow. "
    "Two driven jocks help fax my big quiz. "
    "Five quacking zephyrs jolt my wax bed."
)


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory):
    """A tiny 1-page blank PDF, generated once per session."""
    path = tmp_path_factory.mktemp("fixtures") / "sample.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))  # US Letter
    pdf.save(path)
    return path


@pytest.fixture(scope="session")
def text_pdf(tmp_path_factory):
    """A 1-page PDF with a /Font resource and a 'Hello World' text content stream.

    Mimics ScanSnap-style scanner output: already has a text layer so OCR is
    redundant. Used to verify needs_ocr returns False on text-bearing PDFs.
    """
    path = tmp_path_factory.mktemp("fixtures") / "text.pdf"
    pdf = pikepdf.new()
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica,
        )
    )
    pdf.add_blank_page(page_size=(612, 792))
    pdf.pages[0].Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    pdf.pages[0].Contents = pdf.make_stream(
        b"BT /F1 24 Tf 100 700 Td (Hello World) Tj ET"
    )
    pdf.save(path)
    return path


@pytest.fixture(scope="session")
def image_only_pdf(tmp_path_factory):
    """A 1-page PDF whose only content is a rendered raster of 'Hello World'.

    No /Font resource on the page, so needs_ocr() returns True and the
    auto-routing pipeline takes the OCR branch. Tesseract should be able
    to recognize the rendered text. Built via Pillow's PDF export, which
    embeds the image as an XObject without any font references.
    """
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw, ImageFont

    path = tmp_path_factory.mktemp("fixtures") / "image_only.pdf"
    img = Image.new("L", (1600, 400), color=255)  # white background
    # PIL's default bitmap font is too small for reliable Tesseract reads;
    # load_default(size=N) (Pillow >= 10) gives a large enough rendering.
    font = ImageFont.load_default(size=80)
    ImageDraw.Draw(img).text((40, 100), "Hello World Test", fill=0, font=font)
    img.save(path, "PDF", resolution=200.0)
    return path


@pytest.fixture(scope="session")
def text_paragraph_pdf(tmp_path_factory):
    """A 1-page text PDF carrying ~45 tokens of pangram-style text.

    Hand-built with pikepdf: a /Font resource and a content stream that
    positions multiple lines via Td deltas. Used by item-6 round-trip
    tests where pdfminer-extracts on input vs output are compared at
    ±10% token-count fidelity.
    """
    path = tmp_path_factory.mktemp("fixtures") / "paragraph.pdf"
    pdf = pikepdf.new()
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica,
        )
    )
    pdf.add_blank_page(page_size=(612, 792))
    pdf.pages[0].Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))

    # Build a content stream that emits each sentence on its own line.
    # First Td (relative to BT origin) sets the absolute start position;
    # subsequent Td calls move down 18 user units per line.
    lines = [s.strip() for s in PARAGRAPH_TEXT.split(".") if s.strip()]
    parts = ["BT", "/F1 14 Tf", "72 720 Td"]
    for i, line in enumerate(lines):
        if i > 0:
            parts.append("0 -18 Td")
        parts.append(f"({line}) Tj")
    parts.append("ET")
    pdf.pages[0].Contents = pdf.make_stream(" ".join(parts).encode("ascii"))
    pdf.save(path)
    return path


@pytest.fixture(scope="session")
def image_paragraph_pdf(tmp_path_factory):
    """A 1-page image-only PDF rendering PARAGRAPH_TEXT.

    No /Font on the page, so needs_ocr() returns True. Used by the
    item-6 OCR round-trip test where the OCR'd output's token count
    is compared to PARAGRAPH_TEXT's at ±10% fidelity. Renders the
    paragraph at 64px on a 1700x900 canvas — large enough that
    Tesseract recognizes every word reliably.
    """
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw, ImageFont

    path = tmp_path_factory.mktemp("fixtures") / "image_paragraph.pdf"
    img = Image.new("L", (1700, 900), color=255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=64)
    # Wrap PARAGRAPH_TEXT into one sentence per rendered line.
    y = 40
    for sentence in [s.strip() for s in PARAGRAPH_TEXT.split(".") if s.strip()]:
        draw.text((40, y), sentence, fill=0, font=font)
        y += 130
    img.save(path, "PDF", resolution=200.0)
    return path


@pytest.fixture(scope="session")
def incompressible_pdf(tmp_path_factory):
    """A PDF that Ghostscript pdfwrite inflates under every preset.

    The page carries a 64x64 RGB image of high-entropy random pixels.
    Random bytes have no compression headroom (Flate adds ~5 bytes of
    overhead on top of the raw data), so any re-encoding step plus the
    structural overhead pdfwrite emits per-page produces output > input.
    Used to exercise the oversize-fallback chain's terminal branch:
    archival -> grew -> retry smallest -> still grew -> passthrough.
    """
    path = tmp_path_factory.mktemp("fixtures") / "incompressible.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(72, 72))  # 1" x 1" page
    raw_pixels = os.urandom(64 * 64 * 3)  # 64x64 RGB
    image = pdf.make_stream(
        raw_pixels,
        Type=pikepdf.Name.XObject,
        Subtype=pikepdf.Name.Image,
        Width=64,
        Height=64,
        ColorSpace=pikepdf.Name.DeviceRGB,
        BitsPerComponent=8,
    )
    page = pdf.pages[0]
    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=image))
    # cm matrix scales the 1x1 unit image up to fill the 72x72 page.
    page.Contents = pdf.make_stream(b"q 72 0 0 72 0 0 cm /Im0 Do Q")
    pdf.save(path)
    return path
