import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from tabulate import tabulate

# ----------------------------
# Config
# ----------------------------
INPUT_JSON = Path("/mnt/data/test.json")

HEADER_ROLES = {"pageHeader", "header", "runningHeader"}
FOOTER_ROLES = {"pageFooter", "footer", "runningFooter"}
HF_ROLES = HEADER_ROLES | FOOTER_ROLES


# ----------------------------
# Helpers
# ----------------------------
def get_page_number(element: Dict[str, Any]) -> Optional[int]:
    brs = element.get("boundingRegions") or []
    if brs and isinstance(brs, list):
        pn = brs[0].get("pageNumber")
        if isinstance(pn, int):
            return pn
    return None


def safe_role(p: Dict[str, Any]) -> str:
    return p.get("role", "paragraph")


def build_ref_to_section_map(sections: List[Dict[str, Any]], kind: str) -> Dict[int, int]:
    """
    Map {index -> section_number (1-based)} for refs like "/tables/3" or "/paragraphs/10".
    """
    out: Dict[int, int] = {}
    prefix = f"/{kind}/"
    for s_idx, section in enumerate(sections, start=1):
        for ref in (section.get("elements") or []):
            if isinstance(ref, str) and ref.startswith(prefix):
                try:
                    idx = int(ref.split("/")[-1])
                    out[idx] = s_idx
                except ValueError:
                    pass
    return out


# ----------------------------
# Table helpers
# ----------------------------
def build_table_matrix(table: Dict[str, Any]) -> List[List[str]]:
    rows = table.get("rowCount", 0)
    cols = table.get("columnCount", 0)
    matrix = [["" for _ in range(cols)] for _ in range(rows)]

    for cell in table.get("cells", []) or []:
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
                    if matrix[rr][cc] == "":
                        matrix[rr][cc] = ""

    return matrix


def matrix_to_tabulate_string(matrix: List[List[str]], max_rows: Optional[int] = 12) -> str:
    if not matrix:
        return "(empty table)"
    headers = matrix[0]
    rows = matrix[1:] if len(matrix) > 1 else []
    if max_rows is not None and len(rows) > max_rows:
        rows = rows[:max_rows] + [["…"] * len(headers)]
    return tabulate(rows, headers=headers, tablefmt="grid")


# ----------------------------
# Generic search engine (used by each entity function)
# ----------------------------
def search_entity_generic(
    data: Dict[str, Any],
    *,
    entity_name: str,
    regex_pattern: str,
    case_sensitive: bool = False,
    search_in_tables: bool = True,
    search_in_paragraphs: bool = True,
    include_headers_footers: bool = True,  # <--- controls footer/header scanning
    return_full_table_matrix: bool = True,
    table_preview_max_rows: int = 12,
) -> Dict[str, Any]:
    """
    Returns a dict with:
      - entity_name
      - matches: list of {intent, ...}
      - contexts: table contexts and paragraph contexts
    """
    sections = data.get("sections", []) or []
    tables = data.get("tables", []) or []
    paragraphs = data.get("paragraphs", []) or []

    table_to_section = build_ref_to_section_map(sections, "tables")
    para_to_section = build_ref_to_section_map(sections, "paragraphs")

    flags = 0 if case_sensitive else re.IGNORECASE
    rx = re.compile(regex_pattern, flags=flags)

    matches: List[Dict[str, Any]] = []
    contexts: Dict[str, Dict[int, Any]] = {"tables": {}, "paragraphs": {}}

    # ---- Tables ----
    if search_in_tables:
        for t_idx, table in enumerate(tables):
            page = get_page_number(table)
            section = table_to_section.get(t_idx)

            table_hit = False
            for cell in table.get("cells", []) or []:
                text = (cell.get("content") or "").strip()
                if not text:
                    continue
                m = rx.search(text)
                if not m:
                    continue

                table_hit = True
                matches.append(
                    {
                        "entity": entity_name,
                        "intent": "table",
                        "source_index": t_idx,
                        "section": section,
                        "page": page,
                        "row": cell.get("rowIndex"),
                        "col": cell.get("columnIndex"),
                        "match": m.group(0),
                        "cell_text": text,
                        "groups": m.groupdict() if m.groupdict() else m.groups(),
                    }
                )

            # Add full table context ONCE if any hit in that table
            if table_hit and t_idx not in contexts["tables"]:
                matrix = build_table_matrix(table)
                contexts["tables"][t_idx] = {
                    "intent": "table",
                    "table": t_idx,
                    "section": section,
                    "page": page,
                    "matrix": matrix if return_full_table_matrix else None,
                    "preview": matrix_to_tabulate_string(matrix, max_rows=table_preview_max_rows),
                }

    # ---- Paragraphs (including footer/header if enabled) ----
    if search_in_paragraphs:
        for p_idx, p in enumerate(paragraphs):
            role = safe_role(p)
            if not include_headers_footers and role in HF_ROLES:
                continue  # skip footer/header paragraphs if turned off

            text = (p.get("content") or "").strip()
            if not text:
                continue

            m = rx.search(text)
            if not m:
                continue

            page = get_page_number(p)
            section = para_to_section.get(p_idx)

            matches.append(
                {
                    "entity": entity_name,
                    "intent": "paragraph",          # paragraph intent includes header/footer/body
                    "paragraph_role": role,         # tells you if it was pageFooter etc.
                    "source_index": p_idx,
                    "section": section,
                    "page": page,
                    "match": m.group(0),
                    "paragraph_text": text,
                    "groups": m.groupdict() if m.groupdict() else m.groups(),
                }
            )

            if p_idx not in contexts["paragraphs"]:
                contexts["paragraphs"][p_idx] = {
                    "intent": "paragraph",
                    "paragraph": p_idx,
                    "role": role,
                    "section": section,
                    "page": page,
                    "content": text,  # entire paragraph (footer/header included if enabled)
                }

    return {
        "entity": entity_name,
        "regex": regex_pattern,
        "count": len(matches),
        "matches": matches,
        "contexts": contexts,
    }


# ----------------------------
# Independent entity functions (examples)
# ----------------------------
def extract_invoice_numbers(data: Dict[str, Any]) -> Dict[str, Any]:
    return search_entity_generic(
        data,
        entity_name="InvoiceNumber",
        regex_pattern=r"\bINV[- ]?\d{3,}\b",
        include_headers_footers=True,   # searches footers too
    )


def extract_dollar_amounts(data: Dict[str, Any]) -> Dict[str, Any]:
    return search_entity_generic(
        data,
        entity_name="DollarAmount",
        regex_pattern=r"\$\s?\d+(?:,\d{3})*(?:\.\d{2})?",
        include_headers_footers=True,
    )


def extract_dates(data: Dict[str, Any]) -> Dict[str, Any]:
    return search_entity_generic(
        data,
        entity_name="Date",
        regex_pattern=r"\b(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b",
        include_headers_footers=True,
    )


def extract_emails(data: Dict[str, Any]) -> Dict[str, Any]:
    return search_entity_generic(
        data,
        entity_name="Email",
        regex_pattern=r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        include_headers_footers=True,
    )


# ----------------------------
# Example: run and print later
# ----------------------------
def main() -> None:
    data = json.loads(INPUT_JSON.read_text(encoding="utf-8"))

    # Each entity is independent (your requirement)
    results = [
        extract_invoice_numbers(data),
        extract_dollar_amounts(data),
        extract_dates(data),
        extract_emails(data),
    ]

    # Print at the end (only here)
    for res in results:
        print("\n" + "=" * 100)
        print(f"{res['entity']} | matches={res['count']} | regex={res['regex']}")
        print("=" * 100)

        for m in res["matches"]:
            if m["intent"] == "table":
                print(
                    f"- [TABLE] table#{m['source_index']} page={m['page']} section={m['section']} "
                    f"row={m['row']} col={m['col']} match={m['match']}"
                )
            else:
                print(
                    f"- [PARA] para#{m['source_index']} role={m.get('paragraph_role')} "
                    f"page={m['page']} section={m['section']} match={m['match']}"
                )

        # Contexts
        if res["contexts"]["paragraphs"]:
            print("\n--- Paragraph contexts ---")
            for _, pctx in sorted(res["contexts"]["paragraphs"].items()):
                print(f"[para#{pctx['paragraph']}] role={pctx['role']} page={pctx['page']} section={pctx['section']}")
                print(pctx["content"])

        if res["contexts"]["tables"]:
            print("\n--- Table contexts (preview) ---")
            for _, tctx in sorted(res["contexts"]["tables"].items()):
                print(f"[table#{tctx['table']}] page={tctx['page']} section={tctx['section']}")
                print(tctx["preview"])


if __name__ == "__main__":
    main()
