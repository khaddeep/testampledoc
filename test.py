import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional, DefaultDict
from collections import defaultdict
from tabulate import tabulate

# ----------------------------
# Config
# ----------------------------
INPUT_JSON = Path("/mnt/data/test.json")

# Common paragraph roles used for header/footer (varies by model/version)
HEADER_ROLES = {"pageHeader", "header", "runningHeader"}
FOOTER_ROLES = {"pageFooter", "footer", "runningFooter"}


# ----------------------------
# Helpers
# ----------------------------
def parse_element_ref(ref: str) -> Tuple[str, int]:
    parts = ref.strip("/").split("/")
    if len(parts) != 2:
        raise ValueError(f"Unexpected element ref format: {ref}")
    return parts[0], int(parts[1])


def safe_get_role(p: Dict[str, Any]) -> str:
    return p.get("role", "paragraph")


def get_page_number(element: Dict[str, Any]) -> Optional[int]:
    """
    Returns the first bounding region's pageNumber if present.
    Works for paragraphs, tables, figures (best-effort).
    """
    brs = element.get("boundingRegions") or []
    if brs and isinstance(brs, list):
        pn = brs[0].get("pageNumber")
        if isinstance(pn, int):
            return pn
    return None


# ----------------------------
# Table Processing
# ----------------------------
def build_table_matrix(table: Dict[str, Any]) -> List[List[str]]:
    rows = table.get("rowCount", 0)
    cols = table.get("columnCount", 0)
    matrix = [["" for _ in range(cols)] for _ in range(rows)]

    for cell in table.get("cells", []):
        r = cell.get("rowIndex", 0)
        c = cell.get("columnIndex", 0)
        rs = cell.get("rowSpan", 1) or 1
        cs = cell.get("columnSpan", 1) or 1
        text = (cell.get("content") or "").strip()

        for rr in range(r, min(r + rs, rows)):
            for cc in range(c, min(c + cs, cols)):
                if rr == r and cc == c:
                    matrix[rr][cc] = text
                else:
                    # Leave spanned cells blank (or put a marker if you prefer)
                    if matrix[rr][cc] == "":
                        matrix[rr][cc] = ""

    return matrix


def print_table_with_tabulate(table: Dict[str, Any]) -> None:
    matrix = build_table_matrix(table)
    if not matrix:
        print("  (Empty table)")
        return

    headers = matrix[0]
    rows = matrix[1:] if len(matrix) > 1 else []
    print(tabulate(rows, headers=headers, tablefmt="grid"))


# ----------------------------
# Header/Footer Extraction
# ----------------------------
def collect_page_headers_footers(paragraphs: List[Dict[str, Any]]) -> Tuple[Dict[int, List[str]], Dict[int, List[str]]]:
    """
    Builds maps: pageNumber -> [header texts], pageNumber -> [footer texts]
    based on paragraph role and boundingRegions.pageNumber.
    """
    headers_by_page: DefaultDict[int, List[str]] = defaultdict(list)
    footers_by_page: DefaultDict[int, List[str]] = defaultdict(list)

    for p in paragraphs:
        role = safe_get_role(p)
        pn = get_page_number(p)
        if pn is None:
            continue

        text = (p.get("content") or "").strip()
        if not text:
            continue

        if role in HEADER_ROLES:
            headers_by_page[pn].append(text)
        elif role in FOOTER_ROLES:
            footers_by_page[pn].append(text)

    return dict(headers_by_page), dict(footers_by_page)


def print_page_header(page_num: int, total_pages: Optional[int], headers_by_page: Dict[int, List[str]]) -> None:
    print("\n" + "#" * 70)
    if total_pages:
        print(f"PAGE {page_num} of {total_pages}")
    else:
        print(f"PAGE {page_num}")
    print("#" * 70)

    header_lines = headers_by_page.get(page_num, [])
    if header_lines:
        print("[PAGE HEADER]")
        for line in header_lines:
            print(line)


def print_page_footer(page_num: int, total_pages: Optional[int], footers_by_page: Dict[int, List[str]]) -> None:
    footer_lines = footers_by_page.get(page_num, [])
    if footer_lines:
        print("\n[PAGE FOOTER]")
        for line in footer_lines:
            print(line)

    print("\n" + "-" * 70)
    if total_pages:
        print(f"End of Page {page_num} / {total_pages}")
    else:
        print(f"End of Page {page_num}")
    print("-" * 70)


# ----------------------------
# Main Printing (Section -> Elements, with Page Header/Footer)
# ----------------------------
def print_sections(data: Dict[str, Any]) -> None:
    sections = data.get("sections", []) or []
    paragraphs = data.get("paragraphs", []) or []
    tables = data.get("tables", []) or []
    figures = data.get("figures", []) or []
    pages = data.get("pages", []) or []

    total_pages = len(pages) if pages else None

    headers_by_page, footers_by_page = collect_page_headers_footers(paragraphs)

    if not sections:
        print("No sections found.")
        return

    for s_idx, section in enumerate(sections, start=1):
        print("\n" + "=" * 70)
        print(f"SECTION {s_idx}")
        print("=" * 70)

        elements = section.get("elements", []) or []

        current_page: Optional[int] = None

        def ensure_page_started(pn: Optional[int]) -> None:
            nonlocal current_page
            if pn is None:
                return
            if current_page != pn:
                # Close previous page (footer)
                if current_page is not None:
                    print_page_footer(current_page, total_pages, footers_by_page)
                # Start new page (header)
                current_page = pn
                print_page_header(current_page, total_pages, headers_by_page)

        # Print elements in the section’s element order
        for ref in elements:
            try:
                kind, idx = parse_element_ref(ref)
            except ValueError:
                print(f"\n[Unknown element ref: {ref}]")
                continue

            if kind == "paragraphs":
                if 0 <= idx < len(paragraphs):
                    p = paragraphs[idx]
                    pn = get_page_number(p)
                    ensure_page_started(pn)

                    role = safe_get_role(p)
                    text = (p.get("content") or "").strip()

                    # Skip printing header/footer paragraphs again in body (optional)
                    if role in HEADER_ROLES or role in FOOTER_ROLES:
                        continue

                    print(f"\n[{role.upper()}]")
                    print(text)

            elif kind == "tables":
                if 0 <= idx < len(tables):
                    t = tables[idx]
                    pn = get_page_number(t)
                    ensure_page_started(pn)

                    print("\n[TABLE]")
                    print_table_with_tabulate(t)

            elif kind == "figures":
                if 0 <= idx < len(figures):
                    f = figures[idx]
                    pn = get_page_number(f)
                    ensure_page_started(pn)

                    print("\n[FIGURE]")
                    caption = (f.get("caption") or {}).get("content")
                    if caption:
                        print("Caption:", caption)

            else:
                print(f"\n[Unsupported element kind: {kind}]")

        # Close last page of this section (footer)
        if current_page is not None:
            print_page_footer(current_page, total_pages, footers_by_page)


def main() -> None:
    if not INPUT_JSON.exists():
        raise FileNotFoundError(f"JSON file not found: {INPUT_JSON}")

    data = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    print_sections(data)


if __name__ == "__main__":
    main()
