import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
from tabulate import tabulate


# ----------------------------
# Config
# ----------------------------
INPUT_JSON = Path("/mnt/data/test.json")


# ----------------------------
# Helpers
# ----------------------------
def parse_element_ref(ref: str) -> Tuple[str, int]:
    """
    Parses Azure DI element reference like:
    "/paragraphs/2", "/tables/0"
    """
    parts = ref.strip("/").split("/")
    return parts[0], int(parts[1])


def safe_get_role(p: Dict[str, Any]) -> str:
    return p.get("role", "paragraph")


# ----------------------------
# Table Processing
# ----------------------------
def build_table_matrix(table: Dict[str, Any]) -> List[List[str]]:
    """
    Builds a full table matrix including spans.
    """
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
# Main Section Printer
# ----------------------------
def print_sections(data: Dict[str, Any]) -> None:
    sections = data.get("sections", [])
    paragraphs = data.get("paragraphs", [])
    tables = data.get("tables", [])
    figures = data.get("figures", [])

    if not sections:
        print("No sections found.")
        return

    for s_idx, section in enumerate(sections, start=1):
        print("\n" + "=" * 70)
        print(f"SECTION {s_idx}")
        print("=" * 70)

        elements = section.get("elements", [])

        for ref in elements:
            kind, idx = parse_element_ref(ref)

            if kind == "paragraphs":
                if idx < len(paragraphs):
                    p = paragraphs[idx]
                    role = safe_get_role(p)
                    text = p.get("content", "").strip()
                    print(f"\n[{role.upper()}]")
                    print(text)

            elif kind == "tables":
                if idx < len(tables):
                    print("\n[TABLE]")
                    print_table_with_tabulate(tables[idx])

            elif kind == "figures":
                if idx < len(figures):
                    print("\n[FIGURE]")
                    fig = figures[idx]
                    caption = fig.get("caption", {}).get("content")
                    if caption:
                        print("Caption:", caption)

            else:
                print(f"\n[Unknown element type: {kind}]")



# ----------------------------
# Entry
# ----------------------------
def main():
    if not INPUT_JSON.exists():
        raise FileNotFoundError("JSON file not found.")

    data = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    print_sections(data)


if __name__ == "__main__":
    main()
