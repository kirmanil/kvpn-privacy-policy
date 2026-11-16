import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_FILE = ROOT / "index.html"
SOURCES = (
    ("agreement", "Документ 01", "Polzovatelskoe-soglashenie-Kvpn-11-16"),
    ("terms", "Документ 02", "Polzovatelskoe-soglashenie-08-21-87"),
    ("privacy", "Документ 03", "Politika-konfidencialnosti-07-20-93"),
)
ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "em", "h3", "h4", "hr", "i",
    "img", "li", "ol", "p", "pre", "s", "strong", "u", "ul",
}
VOID_TAGS = {"br", "hr", "img"}


def safe_url(value, *, image=False):
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    if image and parsed.netloc.lower() not in {"telegra.ph", "cdn4.telesco.pe"}:
        return None
    return value


def render_node(node):
    if isinstance(node, str):
        return html.escape(node, quote=False)
    if not isinstance(node, dict):
        raise ValueError("Unexpected Telegraph content node")

    tag = node.get("tag")
    if not isinstance(tag, str):
        raise ValueError("Telegraph content node has no tag")

    children = node.get("children", [])
    if not isinstance(children, list):
        raise ValueError(f"Invalid children for Telegraph tag: {tag}")
    rendered_children = "".join(render_node(child) for child in children)
    if tag not in ALLOWED_TAGS:
        return rendered_children

    attrs = node.get("attrs", {})
    if not isinstance(attrs, dict):
        attrs = {}
    safe_attrs = ""
    if tag == "a":
        href = safe_url(str(attrs.get("href", "")))
        if href:
            safe_attrs = (
                f' href="{html.escape(href, quote=True)}"'
                ' target="_blank" rel="noopener noreferrer"'
            )
    elif tag == "img":
        src = safe_url(str(attrs.get("src", "")), image=True)
        if not src:
            return ""
        safe_attrs = f' src="{html.escape(src, quote=True)}"'
        alt = attrs.get("alt")
        if isinstance(alt, str):
            safe_attrs += f' alt="{html.escape(alt, quote=True)}"'
    if tag in VOID_TAGS:
        return f"<{tag}{safe_attrs}>"
    return f"<{tag}{safe_attrs}>{rendered_children}</{tag}>"


def fetch_page(path):
    url = "https://api.telegra.ph/getPage?" + urllib.parse.urlencode(
        {"path": path, "return_content": "true"}
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Kvpn-document-sync/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not fetch Telegraph page {path}: {error}") from error

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError(f"Telegraph API returned an unsuccessful response for {path}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"Telegraph API returned no page data for {path}")

    title = result.get("title")
    content = result.get("content")
    if not isinstance(title, str) or not title.strip():
        raise RuntimeError(f"Telegraph page {path} has no title")
    if not isinstance(content, list) or not content:
        raise RuntimeError(f"Telegraph page {path} has no document content")
    return title.strip(), "".join(render_node(node) for node in content)


def build_article(label, title, source_path, content):
    source_url = f"https://telegra.ph/{source_path}"
    return (
        f'<div class="eyebrow">{label} · Оригинал в Telegraph</div>\n'
        f"<h2>{html.escape(title)}</h2>\n"
        '<div class="meta">Текст синхронизируется с оригиналом в Telegraph.</div>\n'
        f'<div class="telegraph-content">{content}</div>\n'
        '<div class="actions"><a class="btn" target="_blank" '
        f'rel="noopener noreferrer" href="{source_url}">Открыть оригинал</a></div>'
    )


def replace_document(source, doc_id, article):
    start = f"<!-- TELEGRAPH:{doc_id}:START -->"
    end = f"<!-- TELEGRAPH:{doc_id}:END -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    replacement = f"{start}\n{article}\n{end}"
    updated, count = pattern.subn(lambda _: replacement, source)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one Telegraph marker pair for {doc_id}, found {count}"
        )
    return updated


def main():
    source = INDEX_FILE.read_text(encoding="utf-8-sig")
    updates = []
    for doc_id, label, path in SOURCES:
        title, content = fetch_page(path)
        updates.append((doc_id, build_article(label, title, path, content)))

    updated = source
    for doc_id, article in updates:
        updated = replace_document(updated, doc_id, article)
    INDEX_FILE.write_text(updated, encoding="utf-8")
    print(f"Synchronized {len(updates)} documents from Telegraph.")


if __name__ == "__main__":
    main()
