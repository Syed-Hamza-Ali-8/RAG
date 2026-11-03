"""Document loaders: file → title + heading-scoped sections of plain text."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import docx
from pypdf import PdfReader

from gateway.errors import DocumentLoadError, UnsupportedDocumentType


@dataclass(frozen=True)
class Section:
    heading_path: tuple[str, ...]
    text: str


@dataclass
class LoadedDocument:
    title: str
    mime_type: str
    sections: list[Section] = field(default_factory=list)


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _title_from_filename(path: Path) -> str:
    return path.stem.replace("-", " ").replace("_", " ").strip().title()


def _sections_from_headings(lines: list[tuple[int | None, str]]) -> tuple[str | None, list[Section]]:
    """lines: (heading_level or None, text). Returns (first H1, sections)."""
    title: str | None = None
    stack: list[tuple[int, str]] = []
    sections: list[Section] = []
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            sections.append(Section(tuple(h for _, h in stack), text))
        buf.clear()

    for level, text in lines:
        if level is None:
            buf.append(text)
            continue
        flush()
        if level == 1 and title is None:
            title = text
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text))
    flush()
    return title, sections


def load_markdown(path: Path) -> LoadedDocument:
    lines: list[tuple[int | None, str]] = []
    in_fence = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else _MD_HEADING.match(raw)
        lines.append((len(m.group(1)), m.group(2)) if m else (None, raw))
    title, sections = _sections_from_headings(lines)
    return LoadedDocument(title or _title_from_filename(path), "text/markdown", sections)


def load_text(path: Path) -> LoadedDocument:
    text = path.read_text(encoding="utf-8").strip()
    sections = [Section((), text)] if text else []
    return LoadedDocument(_title_from_filename(path), "text/plain", sections)


def load_docx(path: Path) -> LoadedDocument:
    document = docx.Document(str(path))
    lines: list[tuple[int | None, str]] = []
    for para in document.paragraphs:
        style = para.style.name if para.style is not None and para.style.name else ""
        text = para.text.strip()
        if not text:
            lines.append((None, ""))
        elif style == "Title":
            lines.append((1, text))
        elif m := re.fullmatch(r"Heading (\d)", style):
            lines.append((int(m.group(1)), text))
        else:
            lines.append((None, text))
    title, sections = _sections_from_headings(lines)
    core_title = document.core_properties.title
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return LoadedDocument(title or core_title or _title_from_filename(path), mime, sections)


def load_pdf(path: Path) -> LoadedDocument:
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(p for p in pages if p)
    if not text:
        raise DocumentLoadError(f"{path}: no extractable text (scanned PDF?)")
    meta_title = reader.metadata.title if reader.metadata else None
    return LoadedDocument(meta_title or _title_from_filename(path), "application/pdf", [Section((), text)])


_LOADERS = {
    ".md": load_markdown,
    ".markdown": load_markdown,
    ".txt": load_text,
    ".docx": load_docx,
    ".pdf": load_pdf,
}


def load_document(path: Path) -> LoadedDocument:
    loader = _LOADERS.get(path.suffix.lower())
    if loader is None:
        raise UnsupportedDocumentType(f"{path}: no loader for '{path.suffix}'")
    try:
        doc = loader(path)
    except (UnsupportedDocumentType, DocumentLoadError):
        raise
    except Exception as exc:
        raise DocumentLoadError(f"{path}: {exc}") from exc
    if not doc.sections:
        raise DocumentLoadError(f"{path}: document has no text")
    return doc
