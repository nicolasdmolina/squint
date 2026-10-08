"""File extraction: hostile .docx / .pdf uploads stay cheap and never turn into a 500."""

import io
import sys
import time
import zipfile
import zlib

import pytest
from fastapi.testclient import TestClient

from conftest import FakeBackend, FakeTokenizer
from squint import extract
from squint.app import create_app
from squint.extract import ExtractError, extract_text

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MAX = 10 * 1024 * 1024


def make_docx(body: str | bytes) -> bytes:
    """A minimal .docx: content types, package rels and word/document.xml around `body`."""
    if isinstance(body, str):
        body = body.encode()
    xml = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="' + W_NS.encode()
           + b'" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"><w:body>'
           + body + b"</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="word/document.xml" Type="http://schemas.openxmlformats.org/'
                   'officeDocument/2006/relationships/officeDocument"/></Relationships>')
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def para(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def gridspan_bomb(span: int = 2_000_000_000) -> bytes:
    """The reviewer's file: python-docx expands a gridSpan of 2e9 into billions of cells."""
    import docx
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    d = docx.Document()
    d.add_paragraph("hello world essay text")
    t = d.add_table(rows=1, cols=1)
    cell = t.rows[0].cells[0]
    cell.text = "cell"
    tc = cell._tc
    gs = OxmlElement("w:gridSpan")
    gs.set(qn("w:val"), str(span))
    tc.get_or_add_tcPr().append(gs)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def vmerge_chain(depth: int = 1500) -> bytes:
    """A table whose cells are vertically merged `depth` rows deep (python-docx recursed per row)."""
    rows = "".join(
        '<w:tr><w:tc><w:tcPr><w:vMerge{}/></w:tcPr><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:tc></w:tr>'.format(
            ' w:val="restart"' if i == 0 else "", "top" if i == 0 else "")
        for i in range(depth))
    return make_docx(para("hello world essay text") + "<w:tbl>" + rows + "</w:tbl>")


def make_pdf(streams: list[bytes]) -> bytes:
    """One page per content stream (Flate-compressed), Helvetica as F1."""
    n = len(streams)
    font = 3 + 2 * n
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % (3 + 2 * i) for i in range(n)), n)]
    for i, content in enumerate(streams):
        comp = zlib.compress(content, 9)
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 %d 0 R >> >> "
                    b"/Contents %d 0 R >>" % (font, 4 + 2 * i))
        objs.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(comp) + comp + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def text_page(text: str) -> bytes:
    return f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()


def content_bomb(reps: int = 1_000_000) -> bytes:
    """The reviewer's page: a 22 MB content stream (54 KB file) that took pypdf 42 s and ~1 GB."""
    return b"BT /F1 12 Tf " + b"1 0 0 1 0 0 Tm (a) Tj " * reps + b"ET"


@pytest.fixture
def client(settings):
    app = create_app(settings, backend_factory=FakeBackend, tokenizer=FakeTokenizer(), password=None)
    with TestClient(app) as c:
        yield c


def upload(c, name, data):
    return c.post("/api/extract", files={"file": (name, data, "application/octet-stream")})


# ------------------------------------------------------------------------------------- .docx


def test_docx_gridspan_bomb_is_cheap(client):
    data = gridspan_bomb()
    assert len(data) < 64 * 1024
    t0 = time.monotonic()
    r = upload(client, "bomb.docx", data)
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "hello world essay text\n\ncell"
    assert time.monotonic() - t0 < 5


def test_docx_deep_vmerge_chain_is_not_a_500(client):
    t0 = time.monotonic()
    r = upload(client, "merged.docx", vmerge_chain(1500))
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "hello world essay text\n\ntop"
    assert time.monotonic() - t0 < 5


def test_docx_text_structure():
    body = (
        '<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'
        "<w:r><w:t>Name</w:t></w:r><w:r><w:tab/><w:t>Value</w:t><w:br/><w:t>next line</w:t></w:r>"
        "<w:del><w:r><w:delText>deleted</w:delText></w:r></w:del><w:ins><w:r><w:t> inserted</w:t></w:r></w:ins></w:p>"
        "<w:tbl><w:tr><w:tc>" + para("a1") + para("a1 second") + "</w:tc><w:tc>" + para("") + "</w:tc>"
        "<w:tc><w:tbl><w:tr><w:tc>" + para("inner") + "</w:tc></w:tr></w:tbl>" + para("b1") + "</w:tc></w:tr></w:tbl>"
        # a text box appears twice (mc:Choice and mc:Fallback); it is read once
        "<w:p><w:r><mc:AlternateContent><mc:Choice><w:txbxContent>" + para("boxed") + "</w:txbxContent></mc:Choice>"
        "<mc:Fallback><w:txbxContent>" + para("boxed") + "</w:txbxContent></mc:Fallback></mc:AlternateContent></w:r>"
        "<w:r><w:t>anchor</w:t></w:r></w:p>"
    )
    text = extract._docx_text(make_docx(body), extract._limits())
    assert text == ("Name\tValue\nnext line inserted\n\n"
                    "a1\na1 second\tinner\nb1\n\n"
                    "boxed\n\nanchor")


def test_docx_stops_at_the_xml_and_char_caps(monkeypatch):
    doc = make_docx("".join(para(f"paragraph number {i}") for i in range(20_000)))  # ~1.2 MB of XML
    monkeypatch.setattr(extract, "MAX_DOCX_XML_BYTES", 300_000)
    text = extract_text("long.docx", doc, MAX)  # in the child, with the patched limits
    assert text.startswith("paragraph number 0\n\nparagraph number 1\n\n")
    assert 1000 < text.count("paragraph number") < 10_000
    monkeypatch.setattr(extract, "MAX_DOCX_XML_BYTES", 50 * 1024 * 1024)
    monkeypatch.setattr(extract, "MAX_CHARS", 1000)
    assert len(extract_text("long.docx", doc, MAX)) <= 1000


@pytest.mark.parametrize("data", [
    make_docx(para("fine"))[:-40],  # truncated zip
    make_docx("<w:p><w:r><w:t>unclosed</w:r></w:p>"),  # broken XML
    make_docx("<w:sdt>" * 5000 + "</w:sdt>" * 5000),  # nesting deeper than libxml2 allows
    b"PK\x03\x04" + b"\x00" * 100,
])
def test_malformed_docx_is_415(client, data):
    r = upload(client, "bad.docx", data)
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_file", r.text


def test_docx_without_document_part_is_415(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/other.xml", "<x/>")
    r = upload(client, "empty.docx", buf.getvalue())
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_file"


# -------------------------------------------------------------------------------------- .pdf


def test_pdf_content_stream_bomb_is_cheap(client):
    data = make_pdf([content_bomb()])
    assert len(data) < 64 * 1024
    t0 = time.monotonic()
    r = upload(client, "bomb.pdf", data)
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_text_found", r.text
    assert "too complex" in r.json()["error"]["message"]
    assert time.monotonic() - t0 < 5


def test_pdf_bomb_page_is_skipped_and_the_rest_is_read(client):
    r = upload(client, "mixed.pdf", make_pdf([text_page("Readable first page"), content_bomb(300_000),
                                              text_page("Readable last page")]))
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Readable first page\n\nReadable last page"


def test_extraction_is_killed_after_the_time_limit(monkeypatch):
    monkeypatch.setattr(extract, "EXTRACT_TIMEOUT_S", 0.5)
    monkeypatch.setattr(extract, "_child_argv", lambda kind, lim: [sys.executable, "-c", "import time; time.sleep(30)"])
    t0 = time.monotonic()
    with pytest.raises(ExtractError) as exc:
        extract_text("slow.pdf", make_pdf([text_page("hi")]), MAX)
    assert exc.value.status == 422 and exc.value.code == "no_text_found"
    assert "too long" in exc.value.message
    assert time.monotonic() - t0 < 5


def test_extraction_stops_at_the_memory_limit(monkeypatch):
    monkeypatch.setattr(extract, "MAX_CHILD_RSS", 1)  # any child is over this at once
    with pytest.raises(ExtractError) as exc:
        extract_text("big.pdf", make_pdf([text_page("hi")]), MAX)
    assert exc.value.status == 422 and "too complex" in exc.value.message


@pytest.mark.parametrize("code", ["import sys; sys.exit(3)", "print('not json')", "import os; os.abort()"])
def test_a_crashing_child_is_415(monkeypatch, code):
    monkeypatch.setattr(extract, "_child_argv", lambda kind, lim: [sys.executable, "-c", code])
    with pytest.raises(ExtractError) as exc:
        extract_text("x.docx", make_docx(para("hi")), MAX)
    assert exc.value.status == 415 and exc.value.code == "unsupported_file"


# -------------------------------------------------------------------------------------- .txt


def test_tidy_is_linear_on_long_whitespace_runs(client):
    t0 = time.monotonic()
    assert extract._tidy(" " * 5_000_000 + "x \t\n\n\n\ny") == "x\n\ny"
    assert time.monotonic() - t0 < 2
    t0 = time.monotonic()
    r = upload(client, "spaces.txt", b"word " + b" " * 3_000_000 + b"x\nend")
    assert r.status_code == 200 and r.json()["text"] == "word"  # the rest is past MAX_CHARS
    assert time.monotonic() - t0 < 2


def test_tidy_replaces_lone_surrogates():
    assert extract._tidy("a😀b \ud83d c") == "a\U0001F600b � c"
