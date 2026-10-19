"""Inspect the source PDF and recommend an extraction strategy.

Reports page count, extractable text per page, and whether the document
looks scanned (little/no embedded text). Run before ingest.py:

    python -m ingest.inspect_pdf [path-to-pdf]
"""

import sys
from pathlib import Path

import pymupdf

DEFAULT_PDF = Path(__file__).resolve().parent.parent / "data" / "docs" / "source.pdf"

# Pages with fewer extracted characters than this are treated as image-only.
MIN_CHARS_PER_PAGE = 50
# If more than this fraction of pages look image-only, call the doc "scanned".
SCANNED_PAGE_FRACTION = 0.5


def inspect(pdf_path: Path) -> dict:
    doc = pymupdf.open(pdf_path)
    page_chars = [len(page.get_text("text").strip()) for page in doc]
    n_pages = doc.page_count
    doc.close()

    low_text_pages = [i + 1 for i, c in enumerate(page_chars) if c < MIN_CHARS_PER_PAGE]
    scanned = len(low_text_pages) > n_pages * SCANNED_PAGE_FRACTION

    # Heuristic for table-heavy docs: pages whose text contains many aligned
    # numeric/grid tokens tend to benefit from layout extraction too.
    total = sum(page_chars) or 1
    avg = total // n_pages if n_pages else 0

    return {
        "pages": n_pages,
        "total_chars": sum(page_chars),
        "avg_chars_per_page": avg,
        "page_chars": page_chars,
        "low_text_pages": low_text_pages,
        "looks_scanned": scanned,
    }


def main() -> int:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        print("Drop the source document into data/docs/ (any *.pdf works).")
        return 1

    info = inspect(pdf_path)
    print(f"File:            {pdf_path}")
    print(f"Pages:           {info['pages']}")
    print(f"Total chars:     {info['total_chars']}")
    print(f"Avg chars/page:  {info['avg_chars_per_page']}")
    print(
        "Low-text pages:  "
        + (", ".join(map(str, info["low_text_pages"])) or "none")
    )
    print(f"Looks scanned:   {'YES' if info['looks_scanned'] else 'no'}")
    print()
    if info["looks_scanned"]:
        print(
            "RECOMMENDATION: little extractable text — use Azure AI Document "
            "Intelligence (layout model, Entra ID auth). Set "
            "DOCUMENT_INTELLIGENCE_ENDPOINT and uncomment the package in "
            "requirements.txt."
        )
    else:
        print(
            "RECOMMENDATION: text is extractable — ingest.py will use pymupdf "
            "page by page. Document Intelligence is not needed."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
