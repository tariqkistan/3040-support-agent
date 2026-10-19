"""Structure-aware chunking for technical PDFs.

Why structure-aware? A support agent answers questions like "what is the
torque spec in step 3" — if a table or a numbered procedure is sliced in
half, retrieval returns fragments and groundedness collapses. So we chunk
on document *structure* (sections, tables, procedures), not fixed windows:

* headings start a new chunk and become `section_title`
* tables and numbered procedures are atomic — never split mid-item
* plain paragraphs pack up to ~800 tokens with ~100 tokens of overlap
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
import tiktoken

ENC = tiktoken.get_encoding("cl100k_base")

MAX_CHUNK_TOKENS = 800
OVERLAP_TOKENS = 100

HEADING_SIZE_RATIO = 1.12  # span clearly bigger than page median => heading
BOLD_FLAG = 16  # pymupdf span flag bit for bold

NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*\.?\s+\S")
ALL_CAPS = re.compile(r"^[A-Z0-9][A-Z0-9 \-:()/&.,]{3,}$")
STEP_LINE = re.compile(r"^(step\s*\d+|\d+\s*[.)])\s+\S", re.IGNORECASE)


def token_len(text: str) -> int:
    return len(ENC.encode(text))


@dataclass
class Block:
    """One atomic unit of a page: a paragraph, a table, or a procedure."""

    text: str
    page: int
    kind: str = "para"  # para | table | procedure
    section: str = ""


@dataclass
class Chunk:
    id: str
    content: str
    page_number: int
    section_title: str
    source_file: str
    token_count: int
    blocks: list[Block] = field(default_factory=list, repr=False)


def _median(numbers: list[float]) -> float:
    if not numbers:
        return 1.0
    s = sorted(numbers)
    return s[len(s) // 2]


def _line_text(line: dict) -> str:
    return "".join(span["text"] for span in line["spans"]).strip()


def _looks_like_heading_text(text: str) -> bool:
    """Headings are letter-dominant — this filters out phone numbers, part
    numbers, and other big/bold numeric noise."""
    letters = sum(c.isalpha() for c in text)
    digits = sum(c.isdigit() for c in text)
    return letters >= 3 and letters >= digits


def _is_heading(line: dict, median_size: float) -> bool:
    text = _line_text(line)
    if not text or len(text) > 120 or not _looks_like_heading_text(text):
        return False
    sizes = [s["size"] for s in line["spans"]]
    bold = any(s["flags"] & BOLD_FLAG for s in line["spans"])
    big = max(sizes, default=0) >= median_size * HEADING_SIZE_RATIO
    return big or (bold and (NUMBERED_HEADING.match(text) or ALL_CAPS.match(text)))


def extract_blocks(pdf_path: str) -> tuple[int, list[Block]]:
    """Extract atomic blocks (paragraphs, tables, procedures) page by page."""
    doc = pymupdf.open(pdf_path)
    all_blocks: list[Block] = []

    for page_index in range(doc.page_count):
        page = doc[page_index]
        page_no = page_index + 1
        d = page.get_text("dict")

        # Table regions stay atomic via page.find_tables().
        table_rects: list[pymupdf.Rect] = []
        try:
            for t in page.find_tables():
                table_rects.append(pymupdf.Rect(t.bbox))
        except Exception:
            table_rects = []

        sizes = [
            span["size"]
            for block in d["blocks"]
            if block.get("type") == 0
            for line in block["lines"]
            for span in line["spans"]
            if span["text"].strip()
        ]
        median_size = _median(sizes)

        for block in d["blocks"]:
            if block.get("type") != 0:  # skip images
                continue
            lines = [_line_text(line) for line in block["lines"]]
            lines = [ln for ln in lines if ln]
            if not lines:
                continue

            if _is_heading(block["lines"][0], median_size) and len(lines) == 1:
                all_blocks.append(
                    Block(text=lines[0], page=page_no, kind="heading")
                )
                continue

            text = "\n".join(lines)
            rect = pymupdf.Rect(block["bbox"])
            if any(rect.intersects(tr) for tr in table_rects):
                kind = "table"
            elif all(STEP_LINE.match(ln) for ln in lines) or (
                len(lines) > 1 and sum(1 for ln in lines if STEP_LINE.match(ln)) >= len(lines) // 2
            ):
                kind = "procedure"
            else:
                kind = "para"
            all_blocks.append(Block(text=text, page=page_no, kind=kind))

    n_pages = doc.page_count
    doc.close()
    return n_pages, all_blocks


def _chunk_id(source_file: str, ordinal: int, content: str) -> str:
    digest = hashlib.sha256(f"{source_file}|{ordinal}|{content}".encode()).hexdigest()[:16]
    return f"{Path(source_file).stem}-{ordinal:04d}-{digest}"


def _tail_tokens(text: str, n: int) -> str:
    tokens = ENC.encode(text)
    return ENC.decode(tokens[-n:]) if len(tokens) > n else ""


def chunk_blocks(blocks: list[Block], source_file: str) -> list[Chunk]:
    """Pack atomic blocks into <=800-token chunks with ~100-token overlap."""
    chunks: list[Chunk] = []
    current: list[Block] = []
    current_section = ""
    current_page = 1
    carry = ""  # overlap text prepended to the next chunk

    def flush() -> None:
        nonlocal current, carry
        if not current:
            return
        body_parts = []
        if carry:
            body_parts.append(carry)
        body_parts.extend(b.text for b in current)
        content = "\n\n".join(body_parts).strip()
        chunks.append(
            Chunk(
                id=_chunk_id(source_file, len(chunks), content),
                content=content,
                page_number=current_page,
                section_title=current_section,
                source_file=source_file,
                token_count=token_len(content),
                blocks=current,
            )
        )
        # Overlap: tail of the last paragraph-ish block only — never duplicate
        # a table/procedure across chunks.
        tail_source = next(
            (b for b in reversed(current) if b.kind == "para"), None
        )
        carry = _tail_tokens(tail_source.text, OVERLAP_TOKENS) if tail_source else ""
        current = []

    def current_tokens() -> int:
        return sum(token_len(b.text) for b in current)

    for block in blocks:
        if block.kind == "heading":
            flush()
            carry = ""
            current_section = block.text
            continue

        if block.kind in ("table", "procedure"):
            # Atomic: flush what we have, emit the item alone if needed.
            if current and token_len(block.text) > MAX_CHUNK_TOKENS // 2:
                flush()
                current = [block]
                current_page = block.page
                flush()
            else:
                if current and current_tokens() + token_len(block.text) > MAX_CHUNK_TOKENS:
                    flush()
                    if carry:  # overlap doesn't apply to atomic items
                        current = [Block(text=carry, page=block.page, kind="para")]
                current.append(block)
                if not any(b.kind == "para" for b in current):
                    current_page = block.page
            continue

        # Regular paragraph
        if current_tokens() + token_len(block.text) > MAX_CHUNK_TOKENS and current:
            flush()
            if carry:
                current = [Block(text=carry, page=block.page, kind="para")]
        if not current:
            current_page = block.page
        current.append(block)

    flush()
    return chunks
