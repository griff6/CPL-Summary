from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

from nordiq_cpl_sask_summary import (
    DIVISION_CODE,
    INDEX_URL,
    LIST_URL,
    YEARS,
    fetch_html,
    parse_index_rows,
    parse_rows_from_html,
    select_final_lists,
    write_csv,
)


OUT_BY_SEX_CSV = Path("cpl_sask_unique_racers_by_age_group_2020_2025.csv")
OUT_ALL_SEXES_CSV = Path("cpl_sask_unique_racers_by_age_group_all_sexes_2020_2025.csv")


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


def main() -> None:
    index_html = fetch_html(INDEX_URL)
    index_rows = parse_index_rows(parse_rows_from_html(index_html))
    selected = select_final_lists(index_rows)

    # (year, sex, age_group) -> unique skier ids
    by_sex: Dict[Tuple[int, str, str], Set[str]] = defaultdict(set)
    # (year, age_group) -> unique skier ids
    all_sexes: Dict[Tuple[int, str], Set[str]] = defaultdict(set)

    for year in YEARS:
        for sex in ("Men", "Women"):
            for discipline in ("Distance", "Sprint"):
                chosen = selected[(year, discipline, sex)]
                for row in extract_sk_rows(chosen.list_id):
                    skier_id = row[2]
                    age_group = (row[7] or "Unknown").strip()
                    by_sex[(year, sex, age_group)].add(skier_id)
                    all_sexes[(year, age_group)].add(skier_id)

    by_sex_rows: List[Dict[str, object]] = []
    for year in YEARS:
        keys = [k for k in by_sex if k[0] == year]
        for _, sex, age_group in sorted(keys, key=lambda x: (x[1], x[2])):
            by_sex_rows.append(
                {
                    "Year": year,
                    "Sex": sex,
                    "Age Group": age_group,
                    "Unique SK Racers": len(by_sex[(year, sex, age_group)]),
                }
            )

    all_sexes_rows: List[Dict[str, object]] = []
    for year in YEARS:
        keys = [k for k in all_sexes if k[0] == year]
        for _, age_group in sorted(keys, key=lambda x: x[1]):
            all_sexes_rows.append(
                {
                    "Year": year,
                    "Age Group": age_group,
                    "Unique SK Racers": len(all_sexes[(year, age_group)]),
                }
            )

    write_csv(OUT_BY_SEX_CSV, by_sex_rows)
    write_csv(OUT_ALL_SEXES_CSV, all_sexes_rows)

    print(f"Wrote {OUT_BY_SEX_CSV}")
    print(f"Wrote {OUT_ALL_SEXES_CSV}")
    print()
    print("Year | Sex | Age Group | Unique SK Racers")
    print("-" * 45)
    for row in by_sex_rows:
        print(f"{row['Year']} | {row['Sex']} | {row['Age Group']} | {row['Unique SK Racers']}")


if __name__ == "__main__":
    main()
