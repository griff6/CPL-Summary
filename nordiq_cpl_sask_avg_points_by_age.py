from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from nordiq_cpl_sask_summary import (
    DIVISION_CODE,
    INDEX_URL,
    LIST_URL,
    YEARS,
    fetch_html,
    parse_index_rows,
    parse_rows_from_html,
    select_final_lists,
    to_float,
    write_csv,
)


OUT_CSV = Path("cpl_sask_avg_points_by_age_2020_2025.csv")


def extract_sk_rows(list_id: int) -> List[List[str]]:
    html = fetch_html(LIST_URL.format(list_id=list_id))
    rows = parse_rows_from_html(html)

    header_idx = -1
    for i, row in enumerate(rows):
        if len(row) == 13 and row[:3] == ["Details", "Rank", "SkierID"]:
            header_idx = i
            break
    if header_idx == -1:
        raise RuntimeError(f"Could not find athlete table header for list {list_id}.")

    athletes = [
        row
        for row in rows[header_idx + 1 :]
        if len(row) == 13 and row[1].isdigit() and row[2].isdigit()
    ]
    return [row for row in athletes if row[8] == DIVISION_CODE]


def normalize_age_group(cat: str) -> str:
    cat = cat.strip()
    # Common pattern in CPL lists: "U16 M", "U16 W", etc.
    if cat.endswith(" M") or cat.endswith(" F") or cat.endswith(" W"):
        return cat[:-2].strip()
    return cat


def main() -> None:
    index_html = fetch_html(INDEX_URL)
    index_rows = parse_index_rows(parse_rows_from_html(index_html))
    selected = select_final_lists(index_rows)

    out_rows: List[Dict[str, object]] = []
    age_groups_by_gender: Dict[str, set[str]] = {"Men": set(), "Women": set()}
    grouped_by_combo: Dict[Tuple[int, str, str], Dict[str, List[float]]] = {}
    list_meta_by_combo: Dict[Tuple[int, str, str], Dict[str, object]] = {}

    for year in YEARS:
        for discipline in ("Distance", "Sprint"):
            for gender in ("Men", "Women"):
                combo = (year, discipline, gender)
                chosen = selected[combo]
                sk_rows = extract_sk_rows(chosen.list_id)

                grouped: Dict[str, List[float]] = defaultdict(list)
                for row in sk_rows:
                    age_group = normalize_age_group(row[7]) if row[7] else "Unknown"
                    grouped[age_group].append(to_float(row[10]))
                    age_groups_by_gender[gender].add(age_group)

                grouped_by_combo[combo] = grouped
                list_meta_by_combo[combo] = {
                    "List Name": chosen.list_name,
                    "Publication Date": chosen.publication_date.date().isoformat(),
                    "List ID": chosen.list_id,
                }

    # Emit full matrix with explicit zero rows for missing age groups.
    for year in YEARS:
        for discipline in ("Distance", "Sprint"):
            for gender in ("Men", "Women"):
                combo = (year, discipline, gender)
                grouped = grouped_by_combo[combo]
                meta = list_meta_by_combo[combo]

                for age_group in sorted(age_groups_by_gender[gender]):
                    pts = grouped.get(age_group, [])
                    total = round(sum(pts), 2)
                    avg = round(total / len(pts), 2) if pts else 0.0
                    out_rows.append(
                        {
                            "Year": year,
                            "Discipline": discipline,
                            "Sex": gender,
                            "Age Group": age_group,
                            "SK Racers": len(pts),
                            "Average Points": avg,
                            "Total Points": total,
                            "List Name": meta["List Name"],
                            "Publication Date": meta["Publication Date"],
                            "List ID": meta["List ID"],
                        }
                    )

    write_csv(OUT_CSV, out_rows)
    print(f"Wrote {OUT_CSV}")
    print(f"Rows: {len(out_rows)}")


if __name__ == "__main__":
    main()
