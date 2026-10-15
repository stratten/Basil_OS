"""Builders for small, valid document files used by the document reading tests."""

import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union
from xml.sax.saxutils import escape

SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MARKUP_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'

Cell = Union[None, bool, int, float, str, Tuple[str, str]]


def write_zip(path: Path, members: Dict[str, Union[str, bytes]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return path


def pdf_bytes(pages: Sequence[str]) -> bytes:
    objects: List[bytes] = []
    kids = " ".join(f"{4 + 2 * index} 0 R" for index in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, text in enumerate(pages):
        content_number = 5 + 2 * index
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_number} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> >>".encode()
        )
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    output = bytearray(b"%PDF-1.4\n")
    offsets: List[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(output)


def make_pdf(path: Path, pages: Sequence[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_bytes(pages))
    return path


def _column(index: int) -> str:
    return chr(ord("A") + index)


def make_xlsx(path: Path, sheets: Sequence[Tuple[str, Sequence[Sequence[Cell]]]], phonetic_string: Optional[Tuple[str, str]] = None) -> Path:
    shared: List[str] = []
    members: Dict[str, Union[str, bytes]] = {}
    sheet_entries: List[str] = []
    relationship_entries: List[str] = []

    def shared_index(text: str) -> int:
        if text not in shared:
            shared.append(text)
        return shared.index(text)

    for sheet_number, (name, rows) in enumerate(sheets, start=1):
        row_xml: List[str] = []
        for row_number, row in enumerate(rows, start=1):
            cells: List[str] = []
            for column_number, cell in enumerate(row):
                reference = f"{_column(column_number)}{row_number}"
                if cell is None:
                    continue
                if isinstance(cell, bool):
                    cells.append(f'<c r="{reference}" t="b"><v>{int(cell)}</v></c>')
                elif isinstance(cell, (int, float)):
                    cells.append(f'<c r="{reference}"><v>{cell}</v></c>')
                elif isinstance(cell, tuple) and cell[0] == "inline":
                    cells.append(f'<c r="{reference}" t="inlineStr"><is><t>{escape(cell[1])}</t></is></c>')
                elif isinstance(cell, tuple) and cell[0] == "error":
                    cells.append(f'<c r="{reference}" t="e"><v>{escape(cell[1])}</v></c>')
                else:
                    cells.append(f'<c r="{reference}" t="s"><v>{shared_index(str(cell))}</v></c>')
            row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')
        members[f"xl/worksheets/sheet{sheet_number}.xml"] = (
            f'{XML_DECLARATION}<worksheet xmlns="{SHEET_NS}"><sheetData>{"".join(row_xml)}</sheetData></worksheet>'
        )
        sheet_entries.append(f'<sheet name="{escape(name)}" sheetId="{sheet_number}" r:id="rId{sheet_number}"/>')
        relationship_entries.append(
            f'<Relationship Id="rId{sheet_number}" Type="{REL_NS}/worksheet" Target="worksheets/sheet{sheet_number}.xml"/>'
        )
    members["xl/workbook.xml"] = (
        f'{XML_DECLARATION}<workbook xmlns="{SHEET_NS}" xmlns:r="{REL_NS}"><sheets>{"".join(sheet_entries)}</sheets></workbook>'
    )
    members["xl/_rels/workbook.xml.rels"] = (
        f'{XML_DECLARATION}<Relationships xmlns="{PKG_REL_NS}">{"".join(relationship_entries)}</Relationships>'
    )
    items = "".join(f"<si><t>{escape(text)}</t></si>" for text in shared)
    if phonetic_string is not None:
        base, reading = phonetic_string
        items += f'<si><t>{escape(base)}</t><rPh sb="0" eb="1"><t>{escape(reading)}</t></rPh></si>'
    members["xl/sharedStrings.xml"] = f'{XML_DECLARATION}<sst xmlns="{SHEET_NS}">{items}</sst>'
    return write_zip(path, members)


def _drawing_paragraph(text: str) -> str:
    return f"<a:p><a:r><a:t>{escape(text)}</a:t></a:r></a:p>"


def _slide_number_paragraph() -> str:
    return '<a:p><a:fld id="{1}" type="slidenum"><a:t>7</a:t></a:fld></a:p>'


def _drawing_part(root: str, lines: Sequence[str]) -> str:
    body = "".join(_drawing_paragraph(line) for line in lines) + _slide_number_paragraph()
    return (
        f'{XML_DECLARATION}<p:{root} xmlns:a="{DRAWING_NS}" xmlns:p="{PRESENTATION_NS}" xmlns:r="{REL_NS}">'
        f"<p:cSld><p:spTree><p:sp><p:txBody>{body}</p:txBody></p:sp></p:spTree></p:cSld></p:{root}>"
    )


def make_pptx(
    path: Path,
    slides: Sequence[Tuple[Sequence[str], Optional[Sequence[str]]]],
    presentation_order: Optional[Sequence[int]] = None,
) -> Path:
    members: Dict[str, Union[str, bytes]] = {}
    relationship_entries: List[str] = []
    for number, (lines, notes) in enumerate(slides, start=1):
        members[f"ppt/slides/slide{number}.xml"] = _drawing_part("sld", lines)
        relationship_entries.append(
            f'<Relationship Id="rId{number}" Type="{REL_NS}/slide" Target="slides/slide{number}.xml"/>'
        )
        if notes is not None:
            members[f"ppt/notesSlides/notesSlide{number}.xml"] = _drawing_part("notes", notes)
            members[f"ppt/slides/_rels/slide{number}.xml.rels"] = (
                f'{XML_DECLARATION}<Relationships xmlns="{PKG_REL_NS}">'
                f'<Relationship Id="rId1" Type="{REL_NS}/notesSlide" Target="../notesSlides/notesSlide{number}.xml"/>'
                "</Relationships>"
            )
    order = list(presentation_order) if presentation_order is not None else list(range(len(slides)))
    identifiers = "".join(f'<p:sldId id="{256 + index}" r:id="rId{index + 1}"/>' for index in order)
    members["ppt/presentation.xml"] = (
        f'{XML_DECLARATION}<p:presentation xmlns:p="{PRESENTATION_NS}" xmlns:r="{REL_NS}">'
        f"<p:sldIdLst>{identifiers}</p:sldIdLst></p:presentation>"
    )
    members["ppt/_rels/presentation.xml.rels"] = (
        f'{XML_DECLARATION}<Relationships xmlns="{PKG_REL_NS}">{"".join(relationship_entries)}</Relationships>'
    )
    return write_zip(path, members)


def make_docx_package(path: Path, document_xml: str) -> Path:
    return write_zip(path, {"word/document.xml": document_xml})


def word_document(body: str, extra_namespaces: str = "") -> str:
    return f'{XML_DECLARATION}<w:document xmlns:w="{WORD_NS}" xmlns:mc="{MARKUP_NS}" {extra_namespaces}><w:body>{body}</w:body></w:document>'


def make_iwork(path: Path, preview_pages: Optional[Sequence[str]]) -> Path:
    members: Dict[str, Union[str, bytes]] = {"Index/Document.iwa": b"\x00\x01\x02"}
    if preview_pages is not None:
        members["QuickLook/Preview.pdf"] = pdf_bytes(preview_pages)
    return write_zip(path, members)
