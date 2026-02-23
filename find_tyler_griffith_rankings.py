from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from nordiq_cpl_sask_summary import (
    fetch_html,
    parse_index_rows,
    parse_rows_from_html,
    to_float,
    INDEX_URL,
    LIST_URL,
)


TARGET_FIRST = "tyler"
TARGET_LAST = "griffith"
TARGET_BIRTH_YEAR = 2013
TARGET_DIV = "SK"
TARGET_CLUB_TEXT = "saskatoon"
MIN_PUBLICATION_YEAR = 2024

OUT_CSV = Path("tyler_griffith_rankings.csv")


@dataclass
class AthleteRow:
    rank: int
    skier_id: int
    first_name: str
    last_name: str
    dob: Optional[int]
    category: str
    division: str
    club: str
    points: float


def parse_athlete_rows(list_id: int) -> List[AthleteRow]:
    html = fetch_html(LIST_URL.format(list_id=list_id))
    rows = parse_rows_from_html(html)

    header_idx = -1
    for i, row in enumerate(rows):
        if len(row) == 13 and row[:3] == ["Details", "Rank", "SkierID"]:
            header_idx = i
            break
    if header_idx == -1:
        return []

    athletes: List[AthleteRow] = []
    for row in rows[header_idx + 1 :]:
        if len(row) != 13:
            continue
        if not row[1].isdigit() or not row[2].isdigit():
            continue
        dob = int(row[6]) if row[6].isdigit() else None
        athletes.append(
            AthleteRow(
                rank=int(row[1]),
                skier_id=int(row[2]),
                first_name=row[3].strip(),
                last_name=row[4].strip(),
                dob=dob,
                category=row[7].strip(),
                division=row[8].strip(),
                club=row[9].strip(),
                points=to_float(row[10]),
            )
        )
    return athletes


def position_in_group(target: AthleteRow, group: List[AthleteRow]) -> Optional[int]:
    ordered = sorted(group, key=lambda a: a.rank)
    for i, row in enumerate(ordered, start=1):
        if row.skier_id == target.skier_id:
            return i
    return None


def main() -> None:
    index_rows = parse_index_rows(parse_rows_from_html(fetch_html(INDEX_URL)))
    candidate_lists = [
        r
        for r in index_rows
        if r.list_type == "Seeding"
        and r.publication_date.year >= MIN_PUBLICATION_YEAR
        and r.discipline in ("Distance", "Sprint")
    ]

    results: List[Dict[str, object]] = []

    for list_row in candidate_lists:
        athletes = parse_athlete_rows(list_row.list_id)
        if not athletes:
            continue

        for a in athletes:
            if a.first_name.lower() != TARGET_FIRST:
                continue
            if a.last_name.lower() != TARGET_LAST:
                continue
            if a.dob != TARGET_BIRTH_YEAR:
                continue
            if a.division != TARGET_DIV:
                continue
            if TARGET_CLUB_TEXT not in a.club.lower():
                continue

            same_birth_year = [x for x in athletes if x.dob == TARGET_BIRTH_YEAR]
            same_category = [x for x in athletes if x.category == a.category]
            birth_rank = position_in_group(a, same_birth_year)
            category_rank = position_in_group(a, same_category)

            results.append(
                {
                    "Publication Date": list_row.publication_date.date().isoformat(),
                    "List Name": list_row.list_name,
                    "List ID": list_row.list_id,
                    "Discipline": list_row.discipline,
                    "Gender": list_row.gender,
                    "Overall Rank": a.rank,
                    "Points": a.points,
                    "Category": a.category,
                    "Birth Year": TARGET_BIRTH_YEAR,
                    "Rank Among Birth Year": birth_rank if birth_rank is not None else "",
                    "Total In Birth Year": len(same_birth_year),
                    "Rank In Category": category_rank if category_rank is not None else "",
                    "Total In Category": len(same_category),
                    "Division": a.division,
                    "Club": a.club,
                    "Skier ID": a.skier_id,
                }
            )

    results.sort(key=lambda r: (r["Publication Date"], r["List ID"]))

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        if results:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)

    if not results:
        print("No matching records found for Tyler Griffith (2013, SK, Saskatoon).")
        return

    print(f"Wrote {OUT_CSV} ({len(results)} rows)")
    print("Publication | Discipline | Gender | Overall | BirthYearRank | CategoryRank | Category | Points")
    print("-" * 100)
    for r in results:
        print(
            f"{r['Publication Date']} | {r['Discipline']} | {r['Gender']} | "
            f"{r['Overall Rank']} | {r['Rank Among Birth Year']}/{r['Total In Birth Year']} | "
            f"{r['Rank In Category']}/{r['Total In Category']} | {r['Category']} | {r['Points']}"
        )


if __name__ == "__main__":
    main()
