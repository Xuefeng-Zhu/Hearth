"""Recognize file creation and editing requests before exposing file tools."""

import re

DEMO = "Plan Thanksgiving dinner"
TYPE_PATTERNS = {
    "pdf": r"pdf",
    "docx": r"docx|word\s+(?:doc(?:ument)?|file)|doc(?:ument)?",
    "xlsx": r"xlsx|excel(?:\s+(?:file|workbook|sheet))?|spreadsheets?|workbooks?|sheets?",
    "pptx": r"pptx?|powerpoint|presentations?|slide\s*decks?|decks?",
}
TYPES = "|".join(f"(?:{pattern})" for pattern in TYPE_PATTERNS.values())
FILE = rf"(?:{TYPES}|files?|artifacts?)"
TYPE = re.compile(rf"(?<![\w.-])(?:{TYPES})\b", re.I)
ASK = re.compile(
    rf"\b(?:create|make|generate|prepare|build|write|draft|produce|design|assemble|put together|export|"
    rf"save|download|convert|turn|send|give|need|want|attach|provide|deliver)\b[^\n]{{0,140}}?\b{FILE}\b"
    rf"|\b(?:as|into|in)\s+(?:an?\s+)?(?:{TYPES})\b"
    rf"|^\s*(?:please\s+|an?\s+)?(?:{TYPES})(?:\s|:|$)"
    r"|(?:做|制作|製作|生成|创建|建立|导出|匯出|保存|儲存|写|寫|输出|輸出|整理|[给給]我|需要).{0,35}"
    r"(?:PDF|DOCX|Word|文[档檔]|XLSX|Excel|表格|試算表|PPTX?|幻[灯燈]片|演示文稿|簡報)"
    r"|\b(?:as|into)\s+(?:a\s+)?Word\b",
    re.I,
)
EDIT = re.compile(
    r"^\s*(?:(?:please|(?:can|could|would|will) you)\s+)*"
    r"(?:add|insert|edit|update|revise|change|remove|delete|rename|replace|reorder|expand|append|fix|correct|"
    r"shorten|extend|make)\b|(?:添加|加一|新增|编辑|更新|修改|删除|替换|调整)",
    re.I,
)
REFERENCE = re.compile(
    rf"\b(?:{FILE}|slides?|columns?|rows?|version|it|that|this|previous|existing)\b"
    r"|文件|文档|表格|行|列|幻灯片|PPT|PDF|版本|刚才", re.I,
)
EDIT_TARGET = re.compile(
    rf"\b(?:the|this|that|my|our|existing|previous|current)\b[^\n]{{0,55}}\b{FILE}\b"
    r"|\b(?:add|insert|remove|rename|reorder|delete)\b[^\n]{0,80}\b(?:slides?|columns?|rows?)\b"
    r"|(?:这个|刚才|之前|现有).{0,25}(?:PDF|PPT|文件|文档|表格|幻灯片)", re.I,
)
INFORMATIONAL = re.compile(
    r"^\s*(?:how (?:to|(?:do|can|should) (?:i|we))\b|what (?:is|are)\b|explain\b|tell me (?:what|about|how)\b"
    r"|show me how\b|teach me how\b|give me instructions (?:for|on)\b"
    r"|(?:can|could|would) you explain\b|(?:如何|怎么)(?:做|制作|创建|生成|导出))", re.I,
)
NO_FILE = re.compile(
    r"\b(?:do not|don['’]t|no need to|without)\s+(?:create|make|generate|save|attach)\b"
    r"|\b(?:in (?:the |this )?chat only|no (?:files?|downloads?|attachments?))\b"
    r"|不要.{0,8}(?:生成|创建|制作|文件)", re.I,
)


def intent(prompt, has_recent_file=False):
    if NO_FILE.search(prompt) or INFORMATIONAL.search(prompt):
        return None
    if prompt.strip().casefold() == DEMO.casefold():
        return "create"
    if EDIT.search(prompt) and REFERENCE.search(prompt):
        if EDIT_TARGET.search(prompt) or (has_recent_file and not ASK.search(prompt)):
            return "update"
    if ASK.search(prompt):
        # Markdown or source-code requests sometimes describe themselves as files.
        if TYPE.search(prompt) or re.search(r"pdf|docx|word|文[档檔]|xlsx|excel|表格|試算表|ppt|幻[灯燈]片|演示文稿|簡報", prompt, re.I):
            return "create"
        if not re.search(r"\b(?:markdown|csv|json|txt|html|source code|python|script)\b|\.md\b", prompt, re.I):
            return "create"
    return None
