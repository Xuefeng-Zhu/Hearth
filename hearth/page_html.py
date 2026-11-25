"""Convert generated markup into a standalone document with no network resources."""

import base64
import re

from lxml import etree, html
from tinycss2 import parse_blocks_contents, parse_component_value_list, parse_stylesheet, serialize

from .gateway_tools import redact_text
from .page_policy import MAX_PAGE, POLICY
from .storage import HearthError

MAX_SOURCE = 96_000
ELEMENTS = set("""
a abbr address article aside b bdi bdo blockquote br button caption cite code col colgroup dd del
details dfn div dl dt em figcaption figure footer h1 h2 h3 h4 h5 h6 header hgroup hr i img ins kbd
li main mark nav ol p pre q rp rt ruby s samp section small span strong sub summary sup table tbody
td th thead tfoot time tr u ul var wbr
""".split())
DROP = set("""
applet audio canvas embed frame frameset iframe link math meta noscript object picture script
select style svg template textarea video
""".split())
ATTRS = set("""
abbr alt aria-current aria-describedby aria-expanded aria-hidden aria-label aria-labelledby
aria-live aria-pressed class colspan datetime dir height hidden id lang open reversed role
rowspan scope start style title value width
""".split())
GROUPS = {"media", "supports", "container", "layer", "keyframes", "-webkit-keyframes"}
URL_FUNCTIONS = {"url", "src", "image", "image-set", "-webkit-image-set", "expression", "attr"}
FRAGMENT = re.compile(r"#[^\s<>]*\Z")
LANG = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*\Z")
IMAGE_REF = re.compile(r"hearth-image:([a-f0-9]{32})\Z")
FENCE = re.compile(r"\A\s*```(?:html)?\s*\n(.*?)\n```\s*\Z", re.I | re.S)
FILLER = re.compile(r"\blorem\s+ipsum\b", re.I)


def safe_tokens(tokens):
    for token in tokens:
        if token.type in {"error", "url"}:
            return False
        if token.type == "function" and token.lower_name in URL_FUNCTIONS:
            return False
        nested = getattr(token, "arguments", getattr(token, "content", None))
        if nested is not None and not safe_tokens(nested):
            return False
    return True


def clean_css(nodes):
    kept = []
    for node in nodes:
        if node.type == "declaration" and node.lower_name not in {"behavior", "-moz-binding"}:
            if safe_tokens(node.value):
                kept.append(serialize([node]))
        elif node.type in {"at-rule", "qualified-rule"} and safe_tokens(node.prelude):
            if node.content is None or (node.type == "at-rule" and node.lower_at_keyword not in GROUPS):
                continue
            nested = clean_css(parse_blocks_contents(node.content, skip_comments=True, skip_whitespace=True))
            if nested:
                prefix = "@" + node.lower_at_keyword + " " if node.type == "at-rule" else ""
                kept.append(prefix + serialize(node.prelude) + "{" + nested + "}")
    return "".join(kept)


def serialize_document(document):
    return html.tostring(document, encoding="utf-8", doctype="<!doctype html>")


def document_from(source):
    if not isinstance(source, str) or len(source) > MAX_SOURCE:
        raise HearthError("Hearth received HTML that exceeds the page size limit.")
    if fence := FENCE.fullmatch(source):
        source = fence[1]
    if not re.search(r"<(?:html|body|main|header|section|article|h1)\b", source, re.I):
        raise HearthError("The model did not return an HTML page.")
    try:
        return html.document_fromstring(redact_text(source), parser=html.HTMLParser(encoding="utf-8"))
    except (etree.Error, ValueError, UnicodeError, RecursionError):
        raise HearthError("Hearth could not read the generated HTML.") from None


def sanitize(source, title, images=None):
    """Only the caller-provided attachment resolver can produce image bytes."""
    images = images or {}
    document = document_from(source)
    body = document.find("body")
    if body is None:
        raise HearthError("The generated page has no content.")
    for block in document.xpath("//comment() | //processing-instruction()"):
        block.drop_tree()
    styles = []
    for style in document.xpath("//style[@type='text/css' or not(@type)]"):
        parent = style.getparent()
        if parent is not None and parent.tag == "head":
            styles.append(clean_css(parse_stylesheet(style.text or "", skip_comments=True, skip_whitespace=True)))
    embedded = {}
    for element in list(body.iterdescendants()):
        tag = element.tag
        if any(parent.tag in DROP for parent in element.iterancestors()):
            continue
        if tag in DROP:
            element.drop_tree()
            continue
        if tag not in ELEMENTS:
            element.drop_tag()
            continue
        for name, value in list(element.attrib.items()):
            if name == "style":
                value = clean_css(parse_blocks_contents(parse_component_value_list(value),
                                      skip_comments=True, skip_whitespace=True))
                if value:
                    element.set(name, value)
                    continue
            elif name in ATTRS or (name == "href" and tag == "a" and FRAGMENT.fullmatch(value)):
                continue
            elif name == "src" and tag == "img":
                continue
            del element.attrib[name]
        if tag == "img":
            match = IMAGE_REF.fullmatch(element.get("src", ""))
            if not match or match[1] not in images:
                element.drop_tree()
                continue
            key = match[1]
            if key not in embedded:
                raw = images[key]()
                embedded[key] = "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
            element.set("src", embedded[key])
            element.set("data-hearth-image", key)
            element.set("alt", element.get("alt", ""))
        elif tag == "button":
            element.set("type", "button")
    visible = body.text_content().strip()
    if not visible or FILLER.search(visible):
        raise HearthError("The generated page needs real content from the chat.")

    language = document.get("lang", "")
    document.attrib.clear()
    document.set("lang", language if LANG.fullmatch(language) else "zh" if re.search(r"[\u3400-\u9fff]", title) else "en")
    head = document.find("head")
    if head is not None:
        document.remove(head)
    head = html.Element("head")
    document.insert(0, head)
    etree.SubElement(head, "meta", charset="utf-8")
    etree.SubElement(head, "meta", name="viewport", content="width=device-width, initial-scale=1")
    etree.SubElement(head, "meta", name="referrer", content="no-referrer")
    etree.SubElement(head, "meta", attrib={"http-equiv": "Content-Security-Policy", "content": POLICY})
    etree.SubElement(head, "title").text = title
    etree.SubElement(head, "style").text = (
        ":root{color-scheme:light dark}body{margin:0;overflow-wrap:anywhere}"
        "img{max-width:100%;height:auto}" + "".join(styles).replace("<", r"\3c ")
    )
    body_style = clean_css(parse_blocks_contents(parse_component_value_list(body.get("style", "")),
                                                 skip_comments=True, skip_whitespace=True))
    for name in set(body.attrib) - {"class", "id", "dir", "lang"}:
        del body.attrib[name]
    if body_style:
        body.set("style", body_style)
    raw = serialize_document(document)
    if len(raw) > MAX_PAGE:
        raise HearthError("The page is too large. Try using fewer images.")
    return raw


def editable(raw):
    """Send image references, rather than binary attachments, to the coding model."""
    document = html.document_fromstring(raw, parser=html.HTMLParser(encoding="utf-8"))
    for element in document.xpath("//img[@data-hearth-image]"):
        element.set("src", "hearth-image:" + element.attrib.pop("data-hearth-image"))
    return serialize_document(document).decode("utf-8")
