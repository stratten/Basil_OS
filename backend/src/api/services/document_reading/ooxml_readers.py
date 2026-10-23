"""Text extraction for Word, Excel and PowerPoint packages using only the standard library."""

from __future__ import annotations

import io
import posixpath
import re
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

from .archive import ArchiveGuard, natural_key
from .models import DocumentReadError, ReadContext, STATUS_ERROR, TextAccumulator

SLIDE_NUMBER_FIELDS = frozenset({"slidenum", "slidenumber"})
_TRAILING_ZERO_FRACTION = re.compile(r"^(-?\d+)\.0+$")
_SHEET_MEMBER = re.compile(r"xl/worksheets/[^/]+\.xml")
_SLIDE_MEMBER = re.compile(r"ppt/slides/slide\d+\.xml")


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _relationship_id(element: ElementTree.Element) -> Optional[str]:
    for key, value in element.attrib.items():
        if key.endswith("}id"):
            return value
    return None


def _is_slide_number_field(tag: str, element: ElementTree.Element) -> bool:
    return tag == "fld" and (element.get("type") or "").lower() in SLIDE_NUMBER_FIELDS


class _ParagraphCollector:
    """Turns a stream of Word or DrawingML elements into plain lines, with table rows joined by ``|``."""

    def __init__(self) -> None:
        self.lines: List[str] = []
        self._buffer: List[str] = []
        self._cells: List[List[str]] = []
        self._rows: List[List[str]] = []
        self._fallback = 0
        self._skipped_fields = 0

    def start(self, tag: str, element: ElementTree.Element) -> None:
        if tag == "Fallback":
            self._fallback += 1
        elif _is_slide_number_field(tag, element):
            self._skipped_fields += 1
        elif self._fallback or self._skipped_fields:
            return
        elif tag == "tr":
            self._rows.append([])
        elif tag == "tc":
            self._cells.append([])

    def end(self, tag: str, element: ElementTree.Element) -> None:
        if tag == "Fallback":
            self._fallback = max(0, self._fallback - 1)
        elif _is_slide_number_field(tag, element):
            self._skipped_fields = max(0, self._skipped_fields - 1)
        elif self._fallback or self._skipped_fields:
            return
        elif tag == "t":
            self._buffer.append(element.text or "")
        elif tag == "tab":
            self._buffer.append("\t")
        elif tag in ("br", "cr"):
            self._buffer.append("\n")
        elif tag == "p":
            self._finish_paragraph()
            element.clear()
        elif tag == "tc":
            self._finish_cell()
        elif tag == "tr":
            self._finish_row()

    def _emit(self, text: str) -> None:
        if self._cells:
            self._cells[-1].append(text)
        else:
            self.lines.append(text)

    def _finish_paragraph(self) -> None:
        text = "".join(self._buffer).strip()
        self._buffer = []
        if text:
            self._emit(text)

    def _finish_cell(self) -> None:
        if not self._cells:
            return
        cell = " ".join(part for part in self._cells.pop() if part)
        if self._rows:
            self._rows[-1].append(cell)
        elif cell:
            self.lines.append(cell)

    def _finish_row(self) -> None:
        if not self._rows:
            return
        row = " | ".join(cell for cell in self._rows.pop() if cell)
        if row:
            self._emit(row)


def paragraph_lines(xml: bytes) -> Tuple[List[str], Optional[str]]:
    """Lines of text from a Word or DrawingML part, plus a parse error message when the XML was cut off."""
    collector = _ParagraphCollector()
    error: Optional[str] = None
    try:
        for event, element in ElementTree.iterparse(io.BytesIO(xml), events=("start", "end")):
            tag = _local(element.tag)
            if event == "start":
                collector.start(tag, element)
            else:
                collector.end(tag, element)
    except ElementTree.ParseError as parse_error:
        error = str(parse_error)
    return collector.lines, error


def _add_all(accumulator: TextAccumulator, lines: List[str]) -> bool:
    for line in lines:
        if not accumulator.add_line(line):
            return False
    return True


def read_docx(data: bytes, context: ReadContext) -> None:
    context.method = "docx"
    with ArchiveGuard(data, context.limits) as guard:
        xml = guard.read("word/document.xml")
        if xml is None:
            raise DocumentReadError(STATUS_ERROR, "The Word document has no main document part.")
    lines, error = paragraph_lines(xml)
    if error and not lines:
        raise DocumentReadError(STATUS_ERROR, "The Word document could not be parsed.")
    context.units = 1
    _add_all(context.accumulator, lines)


def _relationships(guard: ArchiveGuard, rels_path: str, base_directory: str) -> Dict[str, Tuple[str, str]]:
    """Map relationship id to ``(resolved member path, relationship type)`` for internal targets."""
    data = guard.read(rels_path)
    found: Dict[str, Tuple[str, str]] = {}
    if data is None:
        return found
    try:
        for _event, element in ElementTree.iterparse(io.BytesIO(data), events=("end",)):
            if _local(element.tag) != "Relationship":
                continue
            identifier = element.get("Id")
            target = element.get("Target") or ""
            if element.get("TargetMode") == "External" or not identifier or not target:
                continue
            resolved = target[1:] if target.startswith("/") else posixpath.normpath(posixpath.join(base_directory, target))
            found[identifier] = (resolved, element.get("Type") or "")
    except ElementTree.ParseError:
        pass
    return found


def _ordered_targets(guard: ArchiveGuard, part: str, element_name: str, relationships: Dict[str, Tuple[str, str]]) -> List[Tuple[str, str]]:
    """``(label, member)`` for each ``element_name`` in ``part`` whose relationship resolves to an existing member."""
    data = guard.read(part)
    ordered: List[Tuple[str, str]] = []
    if data is None:
        return ordered
    try:
        for _event, element in ElementTree.iterparse(io.BytesIO(data), events=("end",)):
            if _local(element.tag) != element_name:
                continue
            target = relationships.get(_relationship_id(element) or "")
            if target is not None and guard.has(target[0]):
                ordered.append((element.get("name") or "", target[0]))
    except ElementTree.ParseError:
        return []
    return ordered


def _shared_strings(guard: ArchiveGuard) -> List[str]:
    data = guard.read("xl/sharedStrings.xml")
    strings: List[str] = []
    if data is None:
        return strings
    buffer: List[str] = []
    phonetic = 0
    try:
        for event, element in ElementTree.iterparse(io.BytesIO(data), events=("start", "end")):
            tag = _local(element.tag)
            if event == "start":
                if tag == "rPh":
                    phonetic += 1
                continue
            if tag == "rPh":
                phonetic = max(0, phonetic - 1)
            elif tag == "t" and not phonetic:
                buffer.append(element.text or "")
            elif tag == "si":
                strings.append("".join(buffer))
                buffer = []
                element.clear()
    except ElementTree.ParseError:
        pass
    return strings


def _cell_text(kind: Optional[str], value: Optional[str], inline: List[str], shared: List[str]) -> str:
    if kind == "inlineStr":
        return "".join(inline).strip()
    if value is None:
        return ""
    value = value.strip()
    if kind == "s":
        try:
            return shared[int(value)].strip()
        except (ValueError, IndexError):
            return ""
    if kind == "e":
        return ""
    if kind == "b":
        return "TRUE" if value == "1" else "FALSE"
    trimmed = _TRAILING_ZERO_FRACTION.match(value)
    return trimmed.group(1) if trimmed else value


def _read_sheet(xml: bytes, sheet_name: str, shared: List[str], context: ReadContext, rows_seen: int) -> int:
    """Append one sheet as ``## Sheet: name`` then ``R<row>: a | b`` lines; returns the running row count."""
    accumulator = context.accumulator
    wrote_header = False
    cells: List[str] = []
    kind: Optional[str] = None
    value: Optional[str] = None
    inline: List[str] = []
    in_inline = False
    try:
        for event, element in ElementTree.iterparse(io.BytesIO(xml), events=("start", "end")):
            tag = _local(element.tag)
            if event == "start":
                if tag == "row":
                    cells = []
                elif tag == "c":
                    kind, value, inline = element.get("t"), None, []
                elif tag == "is":
                    in_inline = True
                continue
            if tag == "v":
                value = element.text
            elif tag == "is":
                in_inline = False
            elif tag == "t" and in_inline:
                inline.append(element.text or "")
            elif tag == "c":
                text = _cell_text(kind, value, inline, shared)
                if text:
                    cells.append(text)
                element.clear()
            elif tag == "row":
                if cells:
                    if rows_seen >= context.limits.max_rows:
                        accumulator.truncated = True
                        break
                    if not wrote_header:
                        if not accumulator.add_line(f"## Sheet: {sheet_name}"):
                            break
                        wrote_header = True
                    rows_seen += 1
                    label = element.get("r") or str(rows_seen)
                    if not accumulator.add_line(f"R{label}: " + " | ".join(cells)):
                        break
                    if rows_seen % 200 == 0 and context.out_of_time():
                        break
                element.clear()
    except ElementTree.ParseError:
        pass
    return rows_seen


def read_xlsx(data: bytes, context: ReadContext) -> None:
    context.method = "xlsx"
    with ArchiveGuard(data, context.limits) as guard:
        if not guard.has("xl/workbook.xml"):
            raise DocumentReadError(STATUS_ERROR, "The workbook has no workbook part.")
        relationships = _relationships(guard, "xl/_rels/workbook.xml.rels", "xl")
        sheets = _ordered_targets(guard, "xl/workbook.xml", "sheet", relationships)
        if not sheets:
            fallback = sorted((name for name in guard.names() if _SHEET_MEMBER.fullmatch(name)), key=natural_key)
            sheets = [(f"Sheet {index + 1}", member) for index, member in enumerate(fallback)]
        sheets = [(name or f"Sheet {index + 1}", member) for index, (name, member) in enumerate(sheets)]
        shared = _shared_strings(guard)
        rows_seen = 0
        if len(sheets) > context.limits.max_sheets:
            context.accumulator.truncated = True
        for name, member in sheets[: context.limits.max_sheets]:
            if context.done() or context.out_of_time():
                break
            xml = guard.read(member)
            if xml is None:
                continue
            rows_seen = _read_sheet(xml, name, shared, context, rows_seen)
            context.units += 1


def _slide_members(guard: ArchiveGuard) -> List[str]:
    relationships = _relationships(guard, "ppt/_rels/presentation.xml.rels", "ppt")
    ordered = [member for _label, member in _ordered_targets(guard, "ppt/presentation.xml", "sldId", relationships)]
    if ordered:
        return ordered
    return sorted((name for name in guard.names() if _SLIDE_MEMBER.fullmatch(name)), key=natural_key)


def _notes_lines(guard: ArchiveGuard, slide_member: str) -> List[str]:
    directory, base = posixpath.split(slide_member)
    relationships = _relationships(guard, f"{directory}/_rels/{base}.rels", directory)
    for target, kind in relationships.values():
        if kind.endswith("/notesSlide") and guard.has(target):
            data = guard.read(target)
            return paragraph_lines(data)[0] if data is not None else []
    return []


def read_pptx(data: bytes, context: ReadContext) -> None:
    context.method = "pptx"
    accumulator = context.accumulator
    with ArchiveGuard(data, context.limits) as guard:
        for index, member in enumerate(_slide_members(guard)):
            if index >= context.limits.max_slides:
                accumulator.truncated = True
                break
            if context.done() or context.out_of_time():
                break
            xml = guard.read(member)
            if xml is None:
                continue
            lines, _error = paragraph_lines(xml)
            notes = _notes_lines(guard, member)
            context.units = index + 1
            if not lines and not notes:
                continue
            if not accumulator.add_line(f"## Slide {index + 1}") or not _add_all(accumulator, lines):
                break
            if notes and (not accumulator.add_line("Notes:") or not _add_all(accumulator, notes)):
                break
