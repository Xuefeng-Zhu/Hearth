"""Generate office files and read lightweight previews from their bytes."""

import io
import json
import math
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table as WordTable
from openpyxl import Workbook, load_workbook
from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.oxml.xmlchemy import OxmlElement
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
from reportlab.platypus.doctemplate import LayoutError

from .gateway_tools import scrub
from .storage import HearthError

TOOL_FORMATS = {"document": "docx", "pdf": "pdf", "spreadsheet": "xlsx", "presentation": "pptx"}
MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
CJK = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef\U00020000-\U000323af]")
EAST_ASIAN_FONT = "Microsoft YaHei"
ILLEGAL_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
CELL_REF = re.compile(r"\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}(?::\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})?", re.I)
FUNCTIONS = {"SUM(", "MIN(", "MAX(", "AVERAGE(", "COUNT(", "ROUND(", "ABS("}

STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
CELL = {"type": ["string", "number", "boolean", "null"]}
ROWS = {"type": "array", "items": {"type": "array", "items": CELL}}


def objects(properties, required):
    return {"type": "array", "items": {"type": "object", "properties": properties,
                                       "required": required, "additionalProperties": False}}


TABLES = objects({"headers": STRINGS, "rows": ROWS}, ["headers", "rows"])
SECTIONS = objects({"heading": STRING, "paragraphs": STRINGS, "bullets": STRINGS, "tables": TABLES}, [])
SHEET_CELL = {**CELL, "description": "Use JSON numbers for quantities and amounts. Write formulas as strings "
                                    "beginning with =, such as =B2*C2 or =SUM(D2:D5)."}
SHEET_ROWS = {"type": "array", "items": {"type": "array", "items": SHEET_CELL}}
SHEETS = objects({"name": STRING, "headers": STRINGS, "rows": SHEET_ROWS}, ["name", "headers", "rows"])
SLIDES = {**objects({"title": STRING, "bullets": STRINGS, "notes": STRING}, ["title", "bullets"]),
          "description": "Content slides only. Hearth builds the opening title slide from the top-level title."}
SCHEMAS = {
    "docx": ("sections", SECTIONS),
    "pdf": ("sections", SECTIONS),
    "xlsx": ("sheets", SHEETS),
    "pptx": ("slides", SLIDES),
}


def text(value, *, empty=False, limit=8_000):
    if (not isinstance(value, str) or ILLEGAL_TEXT.search(value) or len(value) > limit
            or (not empty and not value.strip())):
        raise HearthError(f"Use valid text up to {limit:,} characters in the file.")
    return value


def array(value, limit, label, *, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= limit:
        raise HearthError(f"Supply {minimum}–{limit} {label} in the file.")
    return value


def object_fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() <= set(required) | set(optional):
        raise HearthError("Supply structured file content matching the tool’s fields.")


def table_data(table, *, sheet=False):
    keys = ("name", "headers", "rows") if sheet else ("headers", "rows")
    object_fields(table, keys)
    headers = [text(value, limit=240) for value in array(table["headers"], 50 if sheet else 12, "columns", minimum=1)]
    for row in array(table["rows"], 5_000 if sheet else 500, "rows"):
        if not isinstance(row, list) or len(row) > len(headers):
            raise HearthError("Each row must fit its header columns.")
        for cell in row:
            if isinstance(cell, str):
                text(cell, empty=True, limit=4_000)
            elif cell is not None and type(cell) not in (bool, int, float):
                raise HearthError("Use text, numbers, booleans, or null as cell values.")
            elif type(cell) in (int, float) and (abs(cell) >= 1e308 or not math.isfinite(cell)):
                raise HearthError("Use finite numbers as cell values.")


def prepare(fmt, value):
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > 256 * 1024:
            raise HearthError("Structured file content must be at most 256 KiB.")
        value = scrub(value)
    except (ValueError, TypeError, RecursionError):
        raise HearthError("Supply valid JSON file content.") from None
    field, _ = SCHEMAS[fmt]
    object_fields(value, ("title", field), ("subtitle", "title_notes") if fmt == "pptx" else ())
    text(value["title"], limit=160)
    if fmt in ("docx", "pdf"):
        for section in array(value["sections"], 80, "sections", minimum=1):
            object_fields(section, (), ("heading", "paragraphs", "bullets", "tables"))
            if "heading" in section:
                text(section["heading"], limit=240)
            for key in ("paragraphs", "bullets"):
                for entry in array(section.get(key, []), 150, key):
                    text(entry)
            for table in array(section.get("tables", []), 20, "tables"):
                table_data(table)
    elif fmt == "xlsx":
        names = set()
        for sheet in array(value["sheets"], 32, "sheets", minimum=1):
            table_data(sheet, sheet=True)
            name = text(sheet["name"], limit=31)
            if re.search(r"[\[\]:*?/\\]", name) or name.startswith("'") or name.endswith("'") or name.casefold() in names:
                raise HearthError("Choose unique Excel sheet names without reserved characters.")
            names.add(name.casefold())
    else:
        text(value.get("subtitle", ""), empty=True, limit=240)
        text(value.get("title_notes", ""), empty=True)
        slides = array(value["slides"], 100, "content slides")
        for slide in slides:
            object_fields(slide, ("title", "bullets"), ("notes",))
            text(slide["title"], limit=160)
            for bullet in array(slide["bullets"], 14, "bullets per slide"):
                text(bullet, limit=240)
            text(slide.get("notes", ""), empty=True)
        if slides and slides[0]["title"].strip() == value["title"].strip() and not slides[0]["bullets"]:
            if slides[0].get("notes"):
                value.setdefault("title_notes", slides[0]["notes"])
            value["slides"] = slides[1:]
    return value


def label(cell):
    return "" if cell is None else str(cell)


def tables_rows(table):
    width = len(table["headers"])
    return [table["headers"], *(row + [None] * (width - len(row)) for row in table["rows"])]


def word(output, value):
    doc = Document()
    doc.core_properties.title = value["title"]
    for style_name in ("Normal", "Title", "Heading 1", "List Bullet"):
        props = doc.styles[style_name].element.get_or_add_rPr()
        props.get_or_add_rFonts().set(qn("w:eastAsia"), EAST_ASIAN_FONT)
    doc.add_heading(value["title"], 0)
    for section in value["sections"]:
        if heading := section.get("heading"):
            doc.add_heading(heading, 1)
        for paragraph in section.get("paragraphs", []):
            doc.add_paragraph(paragraph)
        for bullet in section.get("bullets", []):
            doc.add_paragraph(bullet, style="List Bullet")
        for data in section.get("tables", []):
            table = doc.add_table(rows=0, cols=len(data["headers"]), style="Light Shading Accent 1")
            for row in tables_rows(data):
                for cell, entry in zip(table.add_row().cells, row):
                    cell.text = label(entry)
    doc.save(output)


@lru_cache(maxsize=1)
def pdf_cjk_font():
    path = Path(os.environ.get("HEARTH_CJK_FONT", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"))
    if not path.is_file():
        raise HearthError("The Chinese PDF font is missing. Install it with scripts/install-office-font.sh.")
    font = TTFont("HearthCJK", str(path))
    pdfmetrics.registerFont(font)
    return font.fontName


def pdf(output, value):
    doc = SimpleDocTemplate(output, title=value["title"], topMargin=48, bottomMargin=48,
                            leftMargin=52, rightMargin=52)
    has_cjk = CJK.search(json.dumps(value, ensure_ascii=False))
    regular = pdf_cjk_font() if has_cjk else "Helvetica"
    strong = regular if has_cjk else "Helvetica-Bold"
    body = ParagraphStyle("Body", fontName=regular, fontSize=11, leading=17, spaceAfter=8,
                          alignment=TA_LEFT, textColor=colors.HexColor("#292331"),
                          wordWrap="CJK" if has_cjk else None)
    title = ParagraphStyle("Title", parent=body, fontName=strong, fontSize=25, leading=32, spaceAfter=18,
                           keepWithNext=True)
    heading = ParagraphStyle("Heading", parent=body, fontName=strong, fontSize=15, leading=20,
                             spaceBefore=9, keepWithNext=True, textColor=colors.HexColor("#513861"))
    bullet = ParagraphStyle("Bullet", parent=body, leftIndent=16, firstLineIndent=-12)
    cell_style = ParagraphStyle("Cell", parent=body, fontSize=9, leading=13, spaceAfter=0)
    header_style = ParagraphStyle("Header", parent=cell_style, textColor=colors.white, fontName=strong)

    def paragraph(content, style):
        return Paragraph(escape(content).replace("\n", "<br/>"), style)

    story = [paragraph(value["title"], title)]
    for section in value["sections"]:
        if name := section.get("heading"):
            story.append(paragraph(name, heading))
        story.extend(paragraph(entry, body) for entry in section.get("paragraphs", []))
        story.extend(paragraph(f"•  {entry}", bullet) for entry in section.get("bullets", []))
        for table in section.get("tables", []):
            rows = [[paragraph(label(cell), header_style if i == 0 else cell_style) for cell in row]
                    for i, row in enumerate(tables_rows(table))]
            grid = LongTable(rows, colWidths=[doc.width / len(table["headers"])] * len(table["headers"]),
                             repeatRows=1, splitInRow=1)
            grid.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#513861")),
                                      ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                      ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                                       [colors.HexColor("#F4EFF6"), colors.white])]))
            story.extend((grid, Spacer(1, 10)))
    doc.build(story)


def simple_formula(value):
    if not value.startswith("=") or len(value) > 250:
        return False
    try:
        tokens = Tokenizer(value).items
    except TokenizerError:
        return False
    for token in tokens:
        if token.type == "OPERAND":
            if token.subtype == "NUMBER" or (token.subtype == "RANGE" and CELL_REF.fullmatch(token.value)):
                continue
            return False
        if token.type == "FUNC" and (token.subtype == "CLOSE" or token.value.upper() in FUNCTIONS):
            continue
        if token.type in ("PAREN", "WHITE-SPACE") or token.value in ("+", "-", "*", "/", "^", "%", ",", "="):
            continue
        return False
    return bool(tokens)


def spreadsheet(output, value):
    book = Workbook()
    book.properties.title = value["title"]
    book.remove(book.active)
    for data in value["sheets"]:
        sheet = book.create_sheet(data["name"])
        sheet.freeze_panes = "A2"
        widths = [0] * len(data["headers"])
        for i, row in enumerate(tables_rows(data), 1):
            for j, entry in enumerate(row, 1):
                cell = sheet.cell(i, j, entry)
                if cell.data_type in ("f", "e") and (i == 1 or not simple_formula(entry)):
                    cell.data_type = "s"
                if i == 1:
                    cell.fill = PatternFill("solid", fgColor="513861")
                    cell.font = Font(name=EAST_ASIAN_FONT, color="FFFFFF", bold=True)
                    cell.alignment = Alignment(wrap_text=True)
                elif isinstance(entry, str) and CJK.search(entry):
                    cell.font = Font(name=EAST_ASIAN_FONT)
                width = sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in label(entry))
                widths[j - 1] = max(widths[j - 1], width)
        sheet.auto_filter.ref = sheet.dimensions
        for j, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(j)].width = max(12, min(48, width + 3))
    book.save(output)


def presentation(output, value):
    deck = Presentation()
    deck.core_properties.title = value["title"]
    slide = deck.slides.add_slide(deck.slide_layouts[0])
    slide.shapes.title.text = value["title"]
    slide.placeholders[1].text = value.get("subtitle", "")
    if value.get("title_notes"):
        slide.notes_slide.notes_text_frame.text = value["title_notes"]
    for data in value["slides"]:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = data["title"]
        frame = slide.placeholders[1].text_frame
        frame.word_wrap = True
        frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        for i, entry in enumerate(data["bullets"]):
            paragraph = frame.add_paragraph() if i else frame.paragraphs[0]
            paragraph.text = entry
        if data.get("notes"):
            slide.notes_slide.notes_text_frame.text = data["notes"]
    for slide in deck.slides:
        frames = [shape.text_frame for shape in slide.shapes if shape.has_text_frame]
        if slide.has_notes_slide:
            frames.append(slide.notes_slide.notes_text_frame)
        for frame in frames:
            for paragraph in frame.paragraphs:
                for run in paragraph.runs:
                    if CJK.search(run.text):
                        east_asian = OxmlElement("a:ea")
                        east_asian.set("typeface", EAST_ASIAN_FONT)
                        run._r.get_or_add_rPr().append(east_asian)
    deck.save(output)


GENERATORS = {"docx": word, "pdf": pdf, "xlsx": spreadsheet, "pptx": presentation}


def generate(fmt, value):
    output = io.BytesIO()
    try:
        GENERATORS[fmt](output, value)
    except LayoutError:
        raise HearthError("The PDF layout is too large. Shorten the longest table cells or headings.") from None
    return output.getvalue()


def bounded_archive(source):
    # Imported office files are ZIP containers. Bound decompression before parsing.
    archive = ZipFile(source)
    members = archive.infolist()
    if len(members) > 1_000 or sum(entry.file_size for entry in members) > 64 * 1024 * 1024:
        archive.close()
        raise HearthError("This file is too large to preview in Hearth.")
    return archive


def text_lines(fmt, path):
    with bounded_archive(path):
        pass
    if fmt == "xlsx":
        with path.open("rb") as stream:
            workbook = load_workbook(stream, read_only=True, keep_links=False, data_only=True)
            try:
                for sheet in workbook.worksheets:
                    yield f"Sheet: {sheet.title}"
                    if (sheet.max_row or 0) > 5000 or (sheet.max_column or 0) > 256:
                        yield "Sheet text truncated to 5000 rows and 256 columns."
                    for row in sheet.iter_rows(max_row=min(sheet.max_row or 5000, 5000),
                                               max_col=min(sheet.max_column or 256, 256), values_only=True):
                        if any(value is not None for value in row):
                            yield "\t".join("" if value is None else str(value) for value in row).rstrip()
            finally:
                workbook.close()
    elif fmt == "docx":
        for block in Document(str(path)).iter_inner_content():
            if isinstance(block, WordTable):
                for row in block.rows:
                    yield "\t".join(cell.text for cell in row.cells)
            else:
                yield block.text
    elif fmt == "pptx":
        for number, slide in enumerate(Presentation(str(path)).slides, 1):
            yield f"Slide {number}"
            for shape in slide.shapes:
                if shape.has_text_frame:
                    yield shape.text
                elif shape.has_table:
                    for row in shape.table.rows:
                        yield "\t".join(cell.text for cell in row.cells)


def preview(fmt, raw):
    stream = io.BytesIO(raw) if isinstance(raw, bytes) else raw
    with bounded_archive(stream):
        pass
    if fmt == "xlsx":
        workbook = load_workbook(stream, read_only=True, keep_links=False)
        try:
            sheet = workbook.worksheets[0]
            columns = min(sheet.max_column or 50, 50)
            rows = [[cell if type(cell) in (bool, int, float) else label(cell)[:4_000] for cell in row]
                    for row in sheet.iter_rows(max_row=min(sheet.max_row or 200, 200),
                                               max_col=columns, values_only=True)]
            return {"sheet": sheet.title, "rows": rows, "truncated": (sheet.max_row or 0) > 200
                    or (sheet.max_column or 0) > columns}
        finally:
            workbook.close()
    if fmt == "pptx":
        slides = []
        for slide in list(Presentation(stream).slides)[:101]:
            title = slide.shapes.title
            lines = [paragraph.text[:4_000] for shape in slide.shapes if shape.has_text_frame
                     and (title is None or shape.shape_id != title.shape_id)
                     for paragraph in shape.text_frame.paragraphs if paragraph.text.strip()]
            slides.append({"title": title.text[:240] if title is not None else "", "bullets": lines[:30]})
        return {"slides": slides}
    blocks = []
    for block in Document(stream).iter_inner_content():
        if len(blocks) >= 600:
            break
        if isinstance(block, WordTable):
            blocks.append({"type": "table", "rows": [[cell.text[:4_000] for cell in row.cells[:50]]
                                                     for row in list(block.rows)[:200]]})
        elif block.text:
            style = block.style.name
            kind = "heading" if style == "Title" or style.startswith("Heading") else (
                "bullet" if style.startswith("List Bullet") else "paragraph")
            blocks.append({"type": kind, "text": block.text[:8_000]})
    return {"blocks": blocks}
