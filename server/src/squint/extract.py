"""Pull plain text out of .docx / .pdf / .txt uploads, entirely in memory.

.docx and .pdf files are parsed in a short-lived child process (`python -m squint.extract`)
that reads the file from stdin and writes JSON to stdout. The parent kills it after
EXTRACT_TIMEOUT_S, and the child exits on its own once its peak memory passes MAX_CHILD_RSS,
so a hostile file costs one process for a bounded time. Nothing is written to disk.

.docx text comes from streaming word/document.xml (w:t / w:tab / w:br inside w:p, table rows
joined by tabs), never from python-docx table objects: spans and merges are not expanded.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

log = logging.getLogger("squint.extract")

MAX_CHARS = 400_000
MAX_DOCX_XML_BYTES = 50 * 1024 * 1024  # decompressed word/document.xml read at most
MAX_PDF_PAGES = 300
MAX_PDF_PAGE_CONTENT = 4 * 1024 * 1024  # decoded content-stream bytes; bigger pages are skipped
PDF_SOFT_SECONDS = 15.0  # no new pages after this; the text so far is returned
EXTRACT_TIMEOUT_S = 20.0  # hard wall-clock limit: the child is killed
MAX_CHILD_RSS = 512 * 1024 * 1024  # peak resident memory of the child
EXIT_TOO_BIG = 75

_SRC_DIR = str(Path(__file__).resolve().parents[1])
_W_NS = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",  # strict OOXML
}
_RUN_TEXT = {"t": None, "tab": "\t", "br": "\n", "cr": "\n", "noBreakHyphen": "-"}
_W_TAGS = {f"{{{ns}}}{name}": name for ns in _W_NS for name in ("p", "tbl", "tr", "tc", *_RUN_TEXT)}
_W_RUN = {f"{{{ns}}}r" for ns in _W_NS}
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


class ExtractError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _unsupported(msg: str = "Upload a .docx, .pdf or .txt file.") -> ExtractError:
    return ExtractError(415, "unsupported_file", msg)


def _too_complex(what: str = "file") -> ExtractError:
    return ExtractError(422, "no_text_found",
                        f"That {what} is too complex to read here. Copy the text and paste it instead.")


def _tidy(text: str) -> str:
    # lone surrogates (from odd PDF encodings) cannot be sent as UTF-8; pairs are joined
    text = text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    # line by line, not re.sub(r"[ \t]+\n"), which is quadratic on long runs of spaces
    text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_CHARS].rstrip()


def _txt(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


# ------------------------------------------------------------------------------------ .docx


class _DocxText:
    """Text from start/end events of word/document.xml, without keeping the tree."""

    def __init__(self, max_chars: int):
        self.blocks: list[str] = []  # body-level paragraphs and table rows
        self.paras: list[list[str]] = []  # open paragraphs (text boxes nest them)
        self.tables: list[dict] = []  # open tables: current row cells and cell lines
        self.fallback = 0  # depth inside mc:Fallback, a duplicate of mc:Choice
        self.chars = 0
        self.max_chars = max_chars

    @property
    def full(self) -> bool:
        return self.chars >= self.max_chars

    def _sink(self, tables: list[dict]) -> list[str]:
        if tables and tables[-1]["cell"] is not None:
            return tables[-1]["cell"]
        return self.blocks

    def feed(self, events) -> None:
        for event, el in events:
            tag = el.tag
            if tag == _MC_FALLBACK:
                self.fallback += 1 if event == "start" else -1
            elif not self.fallback and tag in _W_TAGS:
                if event == "start":
                    self._start(_W_TAGS[tag])
                else:
                    self._end(_W_TAGS[tag], el)
            if event == "end":
                el.clear(keep_tail=False)
                while el.getprevious() is not None:
                    del el.getparent()[0]
            if self.full:
                return

    def _start(self, name: str) -> None:
        if name == "p":
            self.paras.append([])
        elif name == "tbl":
            self.tables.append({"row": None, "cell": None})
        elif name == "tr" and self.tables:
            self.tables[-1]["row"] = []
        elif name == "tc" and self.tables:
            self.tables[-1]["cell"] = []

    def _end(self, name: str, el) -> None:
        if name in _RUN_TEXT:
            parent = el.getparent()
            if self.paras and parent is not None and parent.tag in _W_RUN:
                piece = (el.text or "") if name == "t" else _RUN_TEXT[name]
                self.paras[-1].append(piece)
                self.chars += len(piece)
        elif name == "p" and self.paras:
            text = "".join(self.paras.pop()).strip()
            if text:
                self._sink(self.tables).append(text)
        elif name == "tc" and self.tables:
            t = self.tables[-1]
            cell = "\n".join(t["cell"] or []).strip()
            if cell and t["row"] is not None:
                t["row"].append(cell)
            t["cell"] = None
        elif name == "tr" and self.tables:
            t = self.tables[-1]
            if t["row"]:
                self._sink(self.tables[:-1]).append("\t".join(t["row"]))
            t["row"] = None
        elif name == "tbl" and self.tables:
            self.tables.pop()

    def text(self) -> str:
        parts = list(self.blocks)
        for p in self.paras:  # stopped early: keep the paragraph in progress
            if "".join(p).strip():
                parts.append("".join(p).strip())
        return "\n\n".join(parts)


def _docx_text(data: bytes, lim: dict) -> str:
    bad = "That .docx file isn't a valid Word document."
    if not data.startswith(b"PK"):
        raise _unsupported(bad)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        info = zf.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, EOFError) as exc:
        raise _unsupported(bad) from exc

    from lxml import etree

    parser = etree.XMLPullParser(
        events=("start", "end"), resolve_entities=False, no_network=True, load_dtd=False,
        huge_tree=False, remove_comments=True, remove_pis=True,
    )
    walker = _DocxText(lim["max_chars"])
    read = 0
    try:
        with zf.open(info) as fh:
            while not walker.full:
                chunk = fh.read(256 * 1024)
                if not chunk:
                    parser.close()
                    walker.feed(parser.read_events())
                    break
                read += len(chunk)
                if read > lim["max_xml"]:
                    break  # keep what was read so far
                parser.feed(chunk)
                walker.feed(parser.read_events())
    except Exception as exc:  # bad zip member, bad XML, too deep, encrypted ...
        raise _unsupported("That .docx file couldn't be read.") from exc
    return walker.text()


# ------------------------------------------------------------------------------------- .pdf


def _page_content_bytes(page) -> int:
    contents = page.get("/Contents")
    if contents is None:
        return 0
    contents = contents.get_object()
    streams = contents if isinstance(contents, list) else [contents]
    return sum(len(s.get_object().get_data()) for s in streams)


def _pdf_text(data: bytes, lim: dict) -> str:
    if b"%PDF" not in data[:1024]:
        raise _unsupported("That .pdf file isn't a valid PDF.")
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    from pypdf import PdfReader

    pages: list[str] = []
    skipped = 0
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ExtractError(422, "no_text_found", "That PDF is password-protected.") from exc
        t0 = time.monotonic()
        total = 0
        for i, page in enumerate(reader.pages):
            if i >= lim["max_pages"] or time.monotonic() - t0 > lim["soft_s"] or total > lim["max_chars"]:
                break
            try:
                if _page_content_bytes(page) > lim["max_page_content"]:
                    skipped += 1
                    continue
                t = page.extract_text() or ""
            except Exception:  # one broken page should not lose the rest
                skipped += 1
                continue
            total += len(t)
            pages.append(t)
    except ExtractError:
        raise
    except Exception as exc:
        raise _unsupported("That PDF couldn't be read.") from exc
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if skipped and not re.search(r"\w", text):
        raise _too_complex("PDF")
    return text


# ------------------------------------------------------------------------------ child process

_PARSERS = {"docx": _docx_text, "pdf": _pdf_text}


def _limits() -> dict:
    return {
        "max_chars": MAX_CHARS,
        "max_xml": MAX_DOCX_XML_BYTES,
        "max_pages": MAX_PDF_PAGES,
        "max_page_content": MAX_PDF_PAGE_CONTENT,
        "soft_s": PDF_SOFT_SECONDS,
        "max_rss": MAX_CHILD_RSS,
    }


def _child_argv(kind: str, lim: dict) -> list[str]:
    return [sys.executable, "-m", "squint.extract", kind, json.dumps(lim)]


def _peak_rss() -> int:
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # bytes on macOS, KiB on Linux


def _memory_watchdog(limit: int) -> None:
    while True:
        if _peak_rss() > limit:
            os._exit(EXIT_TOO_BIG)
        time.sleep(0.05)


def _child_main(argv: list[str]) -> None:
    kind, lim = argv[0], json.loads(argv[1])
    threading.Thread(target=_memory_watchdog, args=(lim["max_rss"],), daemon=True).start()
    data = sys.stdin.buffer.read()
    try:
        text = _PARSERS[kind](data, lim)
        out = {"ok": True, "text": text[: 2 * lim["max_chars"]]}
    except ExtractError as exc:
        out = {"ok": False, "status": exc.status, "code": exc.code, "message": exc.message}
    except Exception:  # RecursionError, MemoryError, parser bugs: the file is the problem
        out = {"ok": False, "status": 415, "code": "unsupported_file", "message": "That file couldn't be read."}
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


def _extract_isolated(kind: str, data: bytes) -> str:
    lim = _limits()
    try:
        proc = subprocess.run(
            _child_argv(kind, lim), input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=EXTRACT_TIMEOUT_S, cwd=_SRC_DIR,
        )
    except subprocess.TimeoutExpired as exc:  # run() has already killed the child
        log.warning("%s extraction killed after %.0f s", kind, EXTRACT_TIMEOUT_S)
        raise ExtractError(422, "no_text_found",
                           "That file took too long to read. Copy the text and paste it instead.") from exc
    if proc.returncode == EXIT_TOO_BIG:
        log.warning("%s extraction stopped at the %d MB memory limit", kind, MAX_CHILD_RSS >> 20)
        raise _too_complex()
    try:
        out = json.loads(proc.stdout)
        if proc.returncode != 0 or not isinstance(out, dict):
            raise ValueError(f"exit {proc.returncode}")
        if out.get("ok"):
            return str(out["text"])
        status, code, message = int(out["status"]), str(out["code"]), str(out["message"])
    except Exception as exc:
        log.warning("%s extraction child failed: %s", kind, exc)
        raise _unsupported(f"That .{kind} file couldn't be read.") from exc
    raise ExtractError(status, code, message)


def extract_text(filename: str, data: bytes, max_bytes: int) -> str:
    if len(data) > max_bytes:
        raise ExtractError(413, "file_too_large", "Files can be at most 10 MB.")
    ext = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if ext == "txt":
        text = _txt(data)
    elif ext in _PARSERS:
        text = _extract_isolated(ext, data)
    else:
        raise _unsupported()
    text = _tidy(text)
    if not re.search(r"\w", text):
        raise ExtractError(422, "no_text_found", "No text was found in that file. Scanned PDFs need OCR first.")
    return text


if __name__ == "__main__":
    _child_main(sys.argv[1:])
