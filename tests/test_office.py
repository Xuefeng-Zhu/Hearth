import unittest
from io import BytesIO

from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from hearth import file_intent, office, router
from hearth.storage import HearthError


def render(fmt, value):
    return office.generate(fmt, office.prepare(fmt, value))


DOCUMENT = {"title": "感恩节计划", "sections": [
    {"heading": "晚餐菜单", "paragraphs": ["全家一起准备晚餐。"], "bullets": ["南瓜派"],
     "tables": [{"headers": ["菜名", "数量"], "rows": [["火鸡", 1]]}]},
]}


class OfficeTest(unittest.TestCase):
    def test_docx_round_trip_and_preview(self):
        raw = render("docx", DOCUMENT)
        doc = Document(BytesIO(raw))
        self.assertEqual([item.text for item in doc.paragraphs],
                         ["感恩节计划", "晚餐菜单", "全家一起准备晚餐。", "南瓜派"])
        self.assertEqual(doc.tables[0].cell(1, 0).text, "火鸡")
        self.assertEqual([item["type"] for item in office.preview("docx", raw)["blocks"]],
                         ["heading", "heading", "paragraph", "bullet", "table"])

    def test_pdf_embeds_chinese_glyphs_and_has_one_page(self):
        raw = render("pdf", DOCUMENT)
        self.assertTrue(raw.startswith(b"%PDF"))
        pdf = PdfReader(BytesIO(raw))
        self.assertEqual(len(pdf.pages), 1)
        self.assertIn("晚餐菜单", pdf.pages[0].extract_text())
        self.assertIn("南瓜派", pdf.pages[0].extract_text())
        fonts = (font.get_object() for font in pdf.pages[0]["/Resources"]["/Font"].values())
        self.assertTrue(any("/FontFile2" in font.get("/FontDescriptor", {}).get_object()
                            for font in fonts if "/FontDescriptor" in font))

    def test_xlsx_sheets_numeric_values_formulas_chinese_and_preview_cap(self):
        value = {"title": "采购单", "sheets": [
            {"name": "食材", "headers": ["名称", "数量", "单价", "合计"],
             "rows": [["苹果", 3, 1.75, "=B2*C2"], ["文字", 1, 1, '=HYPERLINK("https://example.invalid")'],
                      ["总额", None, None, "=SUM(D2:D3)"]] + [["茶", 1, 2, "=B2*C2"]] * 200},
            {"name": "餐具", "headers": ["名称", "备齐"], "rows": [["餐盘", True]]},
        ]}
        raw = render("xlsx", value)
        book = load_workbook(BytesIO(raw))
        self.assertEqual(book.sheetnames, ["食材", "餐具"])
        sheet = book["食材"]
        self.assertEqual(sheet["A2"].value, "苹果")
        self.assertEqual((sheet["B2"].value, sheet["C2"].value), (3, 1.75))
        self.assertEqual((sheet["D2"].data_type, sheet["D2"].value), ("f", "=B2*C2"))
        self.assertEqual(sheet["D3"].data_type, "s")
        self.assertEqual(sheet["D4"].data_type, "f")
        self.assertIs(book["餐具"]["B2"].value, True)
        self.assertEqual(sheet.freeze_panes, "A2")
        preview = office.preview("xlsx", raw)
        self.assertEqual(preview["sheet"], "食材")
        self.assertEqual(len(preview["rows"]), 200)
        self.assertTrue(preview["truncated"])
        self.assertEqual(preview["rows"][1], ["苹果", 3, 1.75, "=B2*C2"])

    def test_pptx_title_slide_content_slide_speaker_notes_and_chinese(self):
        raw = render("pptx", {"title": "感恩节晚餐", "subtitle": "全家一起",
                              "slides": [{"title": "甜点", "bullets": ["南瓜派", "苹果塔"], "notes": "提醒过敏原。"}]})
        slides = Presentation(BytesIO(raw)).slides
        self.assertEqual(len(slides), 2)
        self.assertEqual(slides[0].shapes.title.text, "感恩节晚餐")
        self.assertEqual(slides[1].shapes.title.text, "甜点")
        self.assertEqual(slides[1].placeholders[1].text, "南瓜派\n苹果塔")
        self.assertEqual(slides[1].notes_slide.notes_text_frame.text, "提醒过敏原。")
        outline = office.preview("pptx", raw)["slides"]
        self.assertEqual(outline[1], {"title": "甜点", "bullets": ["南瓜派", "苹果塔"]})

    def test_rejects_invalid_and_oversized_structured_content(self):
        for content in (
            {"title": "Bad", "sections": [{"paragraphs": ["Bad\0"]}]},
            {"title": "Bad", "sections": [{"paragraphs": ["字" * 100_000]}]},
            {"title": "Bad", "sections": [{"tables": [{"headers": ["One"], "rows": [[1, 2]]}]}]},
        ):
            with self.subTest(content=content["title"]), self.assertRaises(HearthError):
                render("docx", content)

    def test_file_intent_in_english_and_chinese(self):
        creates = ("make me a shopping list spreadsheet", "PDF of the Thanksgiving plan", "做一个PPT",
                   "please write a Word document about it", "Create a file I can download", "Plan Thanksgiving dinner")
        updates = ("add a slide about desserts", "add a column for cost", "please update the PDF",
                   "请修改刚才的表格")
        non_files = ("Give me a shopping list", "Plan Thanksgiving dinner in chat only", "Save this as JSON",
                     "What is a PDF?", "Show me how to make a PDF", "Write a Markdown file", "Summarize the attached PDF")
        for prompt in creates:
            self.assertEqual(file_intent.intent(prompt), "create", prompt)
            self.assertEqual(router.classify(prompt), "tool", prompt)
        for prompt in updates:
            self.assertEqual(file_intent.intent(prompt), "update", prompt)
        for prompt in non_files:
            self.assertIsNone(file_intent.intent(prompt), prompt)
        self.assertEqual(file_intent.intent("make it shorter", True), "update")
        self.assertIsNone(file_intent.intent("make it shorter"))
