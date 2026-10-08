"""Pull plain text out of .docx / .pdf / .txt uploads, entirely in memory."""

from __future__ import annotations

import io
import re
import time
import zipfile

MAX_DOCX_UNCOMPRESSED = 60 * 1024 * 1024  # zip-bomb guard
MAX_PDF_PAGES = 300
MAX_PDF_SECONDS = 20.0
MAX_CHARS = 400_000


class ExtractError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _unsupported(msg: str = "Upload a .docx, .pdf or .txt file.") -> ExtractError:
    return ExtractError(415, "unsupported_file", msg)


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_CHARS]


def _txt(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _docx(data: bytes) -> str:
    if not data.startswith(b"PK"):
        raise _unsupported("That .docx file isn't a valid Word document.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if sum(i.file_size for i in zf.infolist()) > MAX_DOCX_UNCOMPRESSED:
                raise ExtractError(413, "file_too_large", "That document is too large to read.")
            if "word/document.xml" not in zf.namelist():
                raise _unsupported("That .docx file isn't a valid Word document.")
    except zipfile.BadZipFile as exc:
        raise _unsupported("That .docx file isn't a valid Word document.") from exc

    import docx  # python-docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise _unsupported("That .docx file couldn't be opened.") from exc
    parts: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            t = Paragraph(child, doc).text.strip()
            if t:
                parts.append(t)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append("\t".join(cells))
    return "\n\n".join(parts)


def _pdf(data: bytes) -> str:
    if b"%PDF" not in data[:1024]:
        raise _unsupported("That .pdf file isn't a valid PDF.")
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ExtractError(422, "no_text_found", "That PDF is password-protected.") from exc
        pages = []
        t0 = time.monotonic()
        total = 0
        for i, page in enumerate(reader.pages):
            if i >= MAX_PDF_PAGES or time.monotonic() - t0 > MAX_PDF_SECONDS or total > MAX_CHARS:
                break
            t = page.extract_text() or ""
            total += len(t)
            pages.append(t)
    except ExtractError:
        raise
    except Exception as exc:
        raise _unsupported("That PDF couldn't be read.") from exc
    return "\n\n".join(p.strip() for p in pages if p.strip())


def extract_text(filename: str, data: bytes, max_bytes: int) -> str:
    if len(data) > max_bytes:
        raise ExtractError(413, "file_too_large", "Files can be at most 10 MB.")
    ext = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if ext == "txt":
        text = _txt(data)
    elif ext == "docx":
        text = _docx(data)
    elif ext == "pdf":
        text = _pdf(data)
    else:
        raise _unsupported()
    text = _tidy(text)
    if not re.search(r"\w", text):
        raise ExtractError(422, "no_text_found", "No text was found in that file. Scanned PDFs need OCR first.")
    return text
