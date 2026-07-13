"""Add UTF-8 BOM and fix dataProvider quoting in NavContents .content files."""
from __future__ import annotations

import re
from pathlib import Path

NAV = Path(
    r"c:\Users\BR\codex_ws\p005_mVPrint\_Prj\UIKitAS6"
    r"\Logical\mappView\Visualization\Pages\NavContents"
)

FAILING = {
    "content_C03_S02.content",
    "content_C04_S01.content",
    "content_C04_S02.content",
    "content_C04_S03.content",
    "content_C04_S04.content",
    "content_C04_S05.content",
    "content_C04_S06.content",
    "content_C05_S02.content",
    "content_C05_S03.content",
    "content_C06_S01.content",
    "content_C06_S04.content",
    "content_C06_S05.content",
    "content_C06_S06.content",
    "content_C06_S07.content",
    "content_C06_S08.content",
    "content_C06_S09.content",
    "content_C07_S01.content",
    "content_C07_S02.content",
    "content_C07_S03.content",
    "content_C07_S05.content",
    "content_C07_S06.content",
    "content_C07_S07.content",
    "content_C07_S08.content",
    "content_C07_S09.content",
}

TYPES_NS = ' xmlns:types="http://www.br-automation.com/iat2015/widgetTypes/v2"'


def fix_dataprovider(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        attr = match.group(0)
        if "&quot;value&quot;" in attr:
            return attr
        return attr.replace("'", "&quot;")

    return re.sub(r'dataProvider="[^"]*"', repl, text)


def ensure_types_ns(text: str) -> str:
    if "xmlns:types=" in text:
        return text
    needle = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    if needle in text:
        return text.replace(needle, needle + TYPES_NS, 1)
    return text


def add_bom(raw: bytes) -> bytes:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw
    return b"\xef\xbb\xbf" + raw


def main() -> None:
    for name in sorted(FAILING):
        path = NAV / name
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            text = raw.decode("utf-8-sig")
        else:
            text = raw.decode("utf-8")
        text = ensure_types_ns(text)
        text = fix_dataprovider(text)
        out = add_bom(text.encode("utf-8"))
        path.write_bytes(out)
        print(f"fixed {name}")


if __name__ == "__main__":
    main()
