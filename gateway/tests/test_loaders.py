from pathlib import Path

import docx
import pytest
from fpdf import FPDF

from gateway.errors import DocumentLoadError, UnsupportedDocumentType
from gateway.ingest.loaders import load_document


def test_markdown_heading_paths(tmp_path: Path) -> None:
    p = tmp_path / "leave.md"
    p.write_text(
        "# Leave Policy\n\nIntro.\n\n## Annual\n\nTwenty days.\n\n### Carryover\n\nFive days.\n\n"
        "## Sick\n\nTen days.\n\n```\n# not a heading\n```\n",
        encoding="utf-8",
    )
    doc = load_document(p)
    assert doc.title == "Leave Policy"
    assert doc.mime_type == "text/markdown"
    paths = [s.heading_path for s in doc.sections]
    assert paths == [
        ("Leave Policy",),
        ("Leave Policy", "Annual"),
        ("Leave Policy", "Annual", "Carryover"),
        ("Leave Policy", "Sick"),
    ]
    assert "# not a heading" in doc.sections[-1].text


def test_text_title_from_filename(tmp_path: Path) -> None:
    p = tmp_path / "code-of-conduct.txt"
    p.write_text("Be kind.", encoding="utf-8")
    doc = load_document(p)
    assert doc.title == "Code Of Conduct"
    assert doc.sections[0].text == "Be kind."


def test_docx_headings(tmp_path: Path) -> None:
    d = docx.Document()
    d.add_heading("Vendor Agreement", level=1)
    d.add_paragraph("Preamble text.")
    d.add_heading("Fees", level=2)
    d.add_paragraph("EUR 100 per month.")
    p = tmp_path / "vendor.docx"
    d.save(str(p))
    doc = load_document(p)
    assert doc.title == "Vendor Agreement"
    assert [s.heading_path for s in doc.sections] == [("Vendor Agreement",), ("Vendor Agreement", "Fees")]
    assert doc.sections[1].text == "EUR 100 per month."


def test_pdf_text(tmp_path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.set_title("Budget Memo")
    pdf.multi_cell(0, 10, "The travel budget is USD 450,000.")
    p = tmp_path / "memo.pdf"
    pdf.output(str(p))
    doc = load_document(p)
    assert doc.title == "Budget Memo"
    assert "USD 450,000" in doc.sections[0].text


def test_unsupported_extension(tmp_path: Path) -> None:
    p = tmp_path / "sheet.xlsx"
    p.write_bytes(b"x")
    with pytest.raises(UnsupportedDocumentType):
        load_document(p)


def test_empty_document_raises(tmp_path: Path) -> None:
    p = tmp_path / "empty.md"
    p.write_text("   \n", encoding="utf-8")
    with pytest.raises(DocumentLoadError):
        load_document(p)


def test_corrupt_docx_raises_typed_error(tmp_path: Path) -> None:
    p = tmp_path / "broken.docx"
    p.write_bytes(b"not a zip")
    with pytest.raises(DocumentLoadError):
        load_document(p)
