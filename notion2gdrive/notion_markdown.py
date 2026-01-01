from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence


def rich_text_to_md(rich_text: Sequence[Dict[str, Any]] | None) -> str:
    if not rich_text:
        return ""
    parts: List[str] = []
    for rt in rich_text:
        text = (rt.get("plain_text") or "").replace("\r\n", "\n")
        href = rt.get("href")
        annotations = rt.get("annotations") or {}
        if annotations.get("code"):
            text = f"`{text}`"
        if annotations.get("bold"):
            text = f"**{text}**"
        if annotations.get("italic"):
            text = f"*{text}*"
        if annotations.get("strikethrough"):
            text = f"~~{text}~~"
        if annotations.get("underline"):
            text = f"<u>{text}</u>"
        if href:
            text = f"[{text}]({href})"
        parts.append(text)
    return "".join(parts)

def rich_text_to_plain(rich_text: Sequence[Dict[str, Any]] | None) -> str:
    if not rich_text:
        return ""
    return "".join([(rt.get("plain_text") or "").replace("\r\n", "\n") for rt in rich_text])


def _indent(depth: int) -> str:
    return "  " * max(depth, 0)


def _safe_code_language(language: str | None) -> str:
    if not language:
        return ""
    lang = language.strip().lower()
    if re.fullmatch(r"[a-z0-9_+-]+", lang):
        return lang
    return ""


def block_to_md(block: Dict[str, Any], *, depth: int = 0) -> List[str]:
    block_type = block.get("type")
    out: List[str] = []
    prefix = _indent(depth)

    if block_type in ("paragraph", "heading_1", "heading_2", "heading_3", "quote", "callout"):
        data = block.get(block_type) or {}
        text = rich_text_to_md(data.get("rich_text"))
        if block_type == "paragraph":
            out.append(prefix + (text or ""))
        elif block_type == "heading_1":
            out.append(prefix + "# " + (text or ""))
        elif block_type == "heading_2":
            out.append(prefix + "## " + (text or ""))
        elif block_type == "heading_3":
            out.append(prefix + "### " + (text or ""))
        elif block_type == "quote":
            out.append(prefix + "> " + (text or ""))
        elif block_type == "callout":
            icon = data.get("icon") or {}
            icon_text = ""
            if icon.get("type") == "emoji":
                icon_text = icon.get("emoji") + " "
            out.append(prefix + "> " + icon_text + (text or ""))
        return out

    if block_type in ("bulleted_list_item", "numbered_list_item", "to_do", "toggle"):
        data = block.get(block_type) or {}
        text = rich_text_to_md(data.get("rich_text"))
        if block_type == "bulleted_list_item":
            out.append(prefix + "- " + (text or ""))
        elif block_type == "numbered_list_item":
            out.append(prefix + "1. " + (text or ""))
        elif block_type == "to_do":
            checked = bool(data.get("checked"))
            out.append(prefix + f"- [{'x' if checked else ' '}] " + (text or ""))
        elif block_type == "toggle":
            out.append(prefix + "- " + (text or ""))
        return out

    if block_type == "code":
        data = block.get("code") or {}
        code_text = rich_text_to_plain(data.get("rich_text"))
        lang = _safe_code_language(data.get("language"))
        out.append(prefix + f"```{lang}".rstrip())
        out.extend([(prefix + line) if line else prefix for line in code_text.split("\n")])
        out.append(prefix + "```")
        return out

    if block_type == "divider":
        out.append(prefix + "---")
        return out

    if block_type in ("image", "file", "pdf", "video", "audio"):
        data = block.get(block_type) or {}
        caption = rich_text_to_md(data.get("caption"))
        file_obj = data.get("file") or data.get("external") or {}
        url = file_obj.get("url") or ""
        label = caption or block_type
        if url:
            out.append(prefix + f"[{label}]({url})")
        else:
            out.append(prefix + f"[{label}]()")
        return out

    if block_type == "bookmark":
        data = block.get("bookmark") or {}
        url = data.get("url") or ""
        caption = rich_text_to_md(data.get("caption"))
        label = caption or url or "bookmark"
        out.append(prefix + f"[{label}]({url})" if url else prefix + label)
        return out

    if block_type == "equation":
        data = block.get("equation") or {}
        expr = data.get("expression") or ""
        out.append(prefix + f"$$\n{expr}\n$$")
        return out

    if block_type == "child_page":
        data = block.get("child_page") or {}
        title = data.get("title") or "child page"
        out.append(prefix + f"- {title}")
        return out

    if block_type == "child_database":
        data = block.get("child_database") or {}
        title = data.get("title") or "child database"
        out.append(prefix + f"- {title}")
        return out

    # Fallback: keep something for unknown types
    out.append(prefix + f"- (unsupported block: {block_type})")
    return out
