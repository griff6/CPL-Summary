from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from urllib.request import Request, urlopen


INDEX_URL = "https://services.nordiqcanada.ca/ViewPoints.asp"
LIST_URL = "https://services.nordiqcanada.ca/ViewPointsList.asp?id={list_id}"
YEARS = list(range(2020, 2026))
DIVISION_CODE = "SK"

SUMMARY_CSV = Path("cpl_sask_summary_2020_2025.csv")
DETAILS_CSV = Path("cpl_sask_selected_final_lists.csv")


@dataclass
class ListRow:
    list_name: str
    gender: str
    discipline: str
    list_type: str
    start_date: datetime
    end_date: datetime
    publication_date: datetime
    list_id: int


class SimpleTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: List[List[str]] = []
        self._in_tr = False
        self._in_cell = False
        self._row: List[str] = []
        self._cell_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._in_tr = True
            self._row = []
        elif self._in_tr and tag in ("td", "th"):
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._in_tr and self._in_cell and tag in ("td", "th"):
            text = "".join(self._cell_parts).replace("\xa0", " ")
            text = re.sub(r"\s+", " ", text).strip()
            self._row.append(text)
            self._in_cell = False
        elif tag == "tr" and self._in_tr:
            if self._row:
                self.rows.append(self._row)
            self._in_tr = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)


def fetch_html(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def parse_rows_from_html(html: str) -> List[List[str]]:
    parser = SimpleTableParser()
    parser.feed(html)
    return parser.rows


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%b %d, %Y")


def parse_index_rows(rows: Iterable[List[str]]) -> List[ListRow]:
    out: List[ListRow] = []
    for row in rows:
        if len(row) != 10 or row[0] != "View":
            continue
        out.append(
            ListRow(
                list_name=row[1],
                gender=row[2],
                discipline=row[3],
                list_type=row[4],
                start_date=parse_date(row[5]),
                end_date=parse_date(row[6]),
                publication_date=parse_date(row[8]),
                list_id=int(row[9]),
            )
        )
    return out


def select_final_lists(index_rows: List[ListRow]) -> Dict[Tuple[int, str, str], ListRow]:
    selected: Dict[Tuple[int, str, str], ListRow] = {}
    for year in YEARS:
        for discipline in ("Distance", "Sprint"):
            for gender in ("Men", "Women"):
                candidates = [
                    r
                    for r in index_rows
                    if r.list_type == "Seeding"
                    and r.discipline == discipline
                    and r.gender == gender
                    and r.publication_date.year == year
                    and "Masters" not in r.list_name
                ]
                if not candidates:
                    raise RuntimeError(
                        f"No candidate lists found for {year} {discipline} {gender}."
                    )

                # Prefer lists explicitly labeled as Final.
                final_named = [
                    r
                    for r in candidates
                    if "final" in r.list_name.lower() or r.list_name.lower().startswith("end of ")
                ]
                if final_named:
                    best = sorted(final_named, key=lambda r: (r.publication_date, r.list_id))[-1]
                else:
                    # If no explicit Final exists, use latest spring publication (typical season end).
                    spring_candidates = [r for r in candidates if r.publication_date.month <= 4]
                    pool = spring_candidates if spring_candidates else candidates
                    best = sorted(pool, key=lambda r: (r.publication_date, r.list_id))[-1]

                selected[(year, discipline, gender)] = best
    return selected


def to_float(value: str) -> float:
    try:
        return float(value.replace(",", ""))
    except Exception:
        return 0.0


def summarize_list(list_id: int) -> Tuple[int, float, float]:
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
        if len(row) == 13 and row[1].isdigit()
    ]

    sk_athletes = [row for row in athletes if row[8] == DIVISION_CODE]
    points = [to_float(row[10]) for row in sk_athletes]

    count = len(points)
    total = round(sum(points), 2)
    avg = round(total / count, 2) if count else 0.0
    return count, total, avg


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    index_html = fetch_html(INDEX_URL)
    index_rows = parse_index_rows(parse_rows_from_html(index_html))
    selected = select_final_lists(index_rows)

    detail_rows: List[Dict[str, object]] = []
    year_rows: List[Dict[str, object]] = []

    for year in YEARS:
        metrics: Dict[Tuple[str, str], Tuple[int, float, float]] = {}
        for discipline in ("Distance", "Sprint"):
            for gender in ("Men", "Women"):
                chosen = selected[(year, discipline, gender)]
                count, total, avg = summarize_list(chosen.list_id)
                metrics[(discipline, gender)] = (count, total, avg)

                detail_rows.append(
                    {
                        "Year": year,
                        "Discipline": discipline,
                        "Gender": gender,
                        "List Name": chosen.list_name,
                        "Publication Date": chosen.publication_date.date().isoformat(),
                        "List ID": chosen.list_id,
                        "SK Racers": count,
                        "SK Total Points": total,
                        "SK Average Points": avg,
                    }
                )

        year_rows.append(
            {
                "Year": year,
                "Distance Men Racers": metrics[("Distance", "Men")][0],
                "Distance Women Racers": metrics[("Distance", "Women")][0],
                "Sprint Men Racers": metrics[("Sprint", "Men")][0],
                "Sprint Women Racers": metrics[("Sprint", "Women")][0],
                "Distance Men Total Points": metrics[("Distance", "Men")][1],
                "Distance Men Avg Points": metrics[("Distance", "Men")][2],
                "Distance Women Total Points": metrics[("Distance", "Women")][1],
                "Distance Women Avg Points": metrics[("Distance", "Women")][2],
                "Sprint Men Total Points": metrics[("Sprint", "Men")][1],
                "Sprint Men Avg Points": metrics[("Sprint", "Men")][2],
                "Sprint Women Total Points": metrics[("Sprint", "Women")][1],
                "Sprint Women Avg Points": metrics[("Sprint", "Women")][2],
            }
        )

    write_csv(DETAILS_CSV, detail_rows)
    write_csv(SUMMARY_CSV, year_rows)

    print(f"Wrote {DETAILS_CSV}")
    print(f"Wrote {SUMMARY_CSV}")
    print()
    print("Year | Dist M | Dist W | Spr M | Spr W | Dist M Tot | Dist W Tot | Spr M Tot | Spr W Tot")
    print("-" * 95)
    for r in year_rows:
        print(
            f"{r['Year']} | "
            f"{r['Distance Men Racers']} | {r['Distance Women Racers']} | "
            f"{r['Sprint Men Racers']} | {r['Sprint Women Racers']} | "
            f"{r['Distance Men Total Points']:.2f} | {r['Distance Women Total Points']:.2f} | "
            f"{r['Sprint Men Total Points']:.2f} | {r['Sprint Women Total Points']:.2f}"
        )


if __name__ == "__main__":
    main()
