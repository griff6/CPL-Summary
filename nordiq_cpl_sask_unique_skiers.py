from __future__ import annotations

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


UNIQUE_SUMMARY_CSV = Path("cpl_sask_unique_skiers_2020_2025.csv")
UNIQUE_DETAILS_CSV = Path("cpl_sask_unique_skiers_details.csv")


def extract_skier_ids_for_division(list_id: int, division_code: str = DIVISION_CODE) -> Set[str]:
    html = fetch_html(LIST_URL.format(list_id=list_id))
    rows = parse_rows_from_html(html)

    header_idx = -1
    for i, row in enumerate(rows):
        if len(row) == 13 and row[:3] == ["Details", "Rank", "SkierID"]:
            header_idx = i
            break
    if header_idx == -1:
        raise RuntimeError(f"Could not find athlete table header for list {list_id}.")

    skier_ids: Set[str] = set()
    for row in rows[header_idx + 1 :]:
        if len(row) != 13:
            continue
        # Athlete rows have numeric rank and skier id.
        if not row[1].isdigit() or not row[2].isdigit():
            continue
        if row[8] == division_code:
            skier_ids.add(row[2])

    return skier_ids


def main() -> None:
    index_html = fetch_html(INDEX_URL)
    index_rows = parse_index_rows(parse_rows_from_html(index_html))
    selected = select_final_lists(index_rows)

    detail_rows: List[Dict[str, object]] = []
    summary_rows: List[Dict[str, object]] = []

    for year in YEARS:
        unique_by_gender: Dict[str, Set[str]] = {"Men": set(), "Women": set()}

        for gender in ("Men", "Women"):
            for discipline in ("Distance", "Sprint"):
                chosen = selected[(year, discipline, gender)]
                ids = extract_skier_ids_for_division(chosen.list_id)
                unique_by_gender[gender].update(ids)

                detail_rows.append(
                    {
                        "Year": year,
                        "Gender": gender,
                        "Discipline": discipline,
                        "List Name": chosen.list_name,
                        "Publication Date": chosen.publication_date.date().isoformat(),
                        "List ID": chosen.list_id,
                        "Unique SK Skiers In List": len(ids),
                    }
                )

        summary_rows.append(
            {
                "Year": year,
                "Unique SK Males": len(unique_by_gender["Men"]),
                "Unique SK Females": len(unique_by_gender["Women"]),
                "Unique SK Total": len(unique_by_gender["Men"] | unique_by_gender["Women"]),
            }
        )

    write_csv(UNIQUE_DETAILS_CSV, detail_rows)
    write_csv(UNIQUE_SUMMARY_CSV, summary_rows)

    print(f"Wrote {UNIQUE_DETAILS_CSV}")
    print(f"Wrote {UNIQUE_SUMMARY_CSV}")
    print()
    print("Year | Unique SK Males | Unique SK Females | Unique SK Total")
    print("-" * 60)
    for row in summary_rows:
        print(
            f"{row['Year']} | {row['Unique SK Males']} | "
            f"{row['Unique SK Females']} | {row['Unique SK Total']}"
        )


if __name__ == "__main__":
    main()
