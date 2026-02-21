import re
import time
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service


URL = "https://nordiqcanada.ca/races/point-list/"

# ---- What you asked for ----
YEARS = [
    # Your mapping: "2020" == 2019-2020 final list, end date April 1, 2020
    ("2020", "2019-2020"),
    ("2021", "2020-2021"),
    ("2022", "2021-2022"),
    ("2023", "2022-2023"),
    ("2024", "2023-2024"),
    ("2025", "2024-2025"),
]

RECORDS = {
    "Distance": "Final CPL Distance",
    "Sprint": "Final CPL Sprint",
}

SEXES = {
    "Men": "Male",
    "Women": "Female",
}

DIVISION_TEXT = "Saskatchewan"

# ---- Output ----
OUT_DIR = "cpl_exports"
SUMMARY_OUT = "cpl_sask_summary.csv"


@dataclass
class ScrapeResult:
    year_label: str
    season_text: str
    discipline: str
    sex_group: str
    record_text: str
    rows: pd.DataFrame  # raw rows scraped


def _safe_mkdir(path: str) -> None:
    import os
    os.makedirs(path, exist_ok=True)


def _is_select_element(el) -> bool:
    return el.tag_name.lower() == "select"


def _try_set_filter_by_select(driver, select_el, visible_text: str) -> bool:
    """If the control is a <select>, use Selenium Select()."""
    try:
        Select(select_el).select_by_visible_text(visible_text)
        return True
    except Exception:
        return False


def _try_set_filter_by_typing(driver, container_el, visible_text: str) -> bool:
    """
    Handles many custom dropdowns:
    - click container
    - type option text
    - press Enter
    """
    try:
        container_el.click()
        time.sleep(0.2)
        active = driver.switch_to.active_element
        active.send_keys(Keys.CONTROL, "a")
        active.send_keys(visible_text)
        time.sleep(0.2)
        active.send_keys(Keys.ENTER)
        return True
    except Exception:
        return False


def set_filter_near_label(driver, label_regex: str, option_text: str, timeout: int = 20) -> None:
    """
    Generic “find filter by label” helper.

    It searches for an element containing label text (like "Record", "Season", "Division", "Sex")
    then tries to find the nearest select/control and set it.

    This is the piece most likely to need light tweaking depending on Nordiq’s HTML.
    """
    wait = WebDriverWait(driver, timeout)

    # Find any element whose visible text matches the label
    label_el = wait.until(
        EC.presence_of_element_located(
            (By.XPATH, f"//*[normalize-space() and re:match(normalize-space(.), '{label_regex}')]")
        )
    )


def set_filter_by_label_xpath(driver, label_contains: str, option_text: str, timeout: int = 20) -> None:
    """
    More compatible version (no XPath regex). Finds a label by partial text, then looks for a nearby control.

    If it can't find a nearby control, you'll edit the XPaths here.
    """
    wait = WebDriverWait(driver, timeout)

    # 1) locate label-like element
    label_el = wait.until(
        EC.presence_of_element_located(
            (By.XPATH, f"//*[contains(normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')), "
                       f"'{label_contains.lower()}')]")
        )
    )

    # 2) try to find a select next to it (common patterns)
    candidate_xpaths = [
        ".//following::select[1]",
        ".//following::input[1]",
        ".//following::*[self::div or self::span][1]",
        "./ancestor::*[self::div or self::section][1]//select",
        "./ancestor::*[self::div or self::section][1]//input",
    ]

    control_el = None
    for xp in candidate_xpaths:
        try:
            control_el = label_el.find_element(By.XPATH, xp)
            if control_el is not None:
                break
        except Exception:
            continue

    if control_el is None:
        raise RuntimeError(
            f"Could not find a control near label containing '{label_contains}'. "
            f"Open DevTools and update set_filter_by_label_xpath() candidate_xpaths."
        )

    # 3) set value using best available strategy
    if _is_select_element(control_el):
        if not _try_set_filter_by_select(driver, control_el, option_text):
            raise RuntimeError(f"Failed selecting '{option_text}' in <select> for '{label_contains}'.")
    else:
        # If it's an input, type and Enter; if it's a div-based dropdown, typing often still works
        if not _try_set_filter_by_typing(driver, control_el, option_text):
            # fallback: click + send keys to active element
            control_el.click()
            time.sleep(0.2)
            active = driver.switch_to.active_element
            active.send_keys(Keys.CONTROL, "a")
            active.send_keys(option_text)
            time.sleep(0.2)
            active.send_keys(Keys.ENTER)

    time.sleep(0.8)  # allow results to refresh


def wait_for_table(driver, timeout: int = 30) -> None:
    wait = WebDriverWait(driver, timeout)
    wait.until(EC.presence_of_element_located((By.XPATH, "//table")))


def scrape_table_to_df(driver) -> pd.DataFrame:
    """
    Scrapes the first visible HTML table into a DataFrame.
    You may need to adjust if the page renders multiple tables.
    """
    tables = driver.find_elements(By.XPATH, "//table")
    if not tables:
        return pd.DataFrame()

    table = tables[0]

    # header
    headers = []
    try:
        ths = table.find_elements(By.XPATH, ".//thead//th")
        headers = [th.text.strip() for th in ths if th.text.strip()]
    except Exception:
        headers = []

    # rows
    body_rows = table.find_elements(By.XPATH, ".//tbody//tr")
    data = []
    for tr in body_rows:
        tds = tr.find_elements(By.XPATH, ".//td")
        row = [td.text.strip() for td in tds]
        if any(row):
            data.append(row)

    df = pd.DataFrame(data)
    if headers and len(headers) == df.shape[1]:
        df.columns = headers

    return df


def extract_points_column(df: pd.DataFrame) -> pd.Series:
    """
    Attempts to find the points column and convert to float.
    Adjust column name guesses if needed.
    """
    possible_cols = ["Points", "CPL Points", "Point", "Pts"]
    col = None
    for c in possible_cols:
        if c in df.columns:
            col = c
            break

    # If unknown headers, guess last numeric-ish column
    if col is None:
        # try each column from right to left and see which parses best
        best = None
        best_nonnull = -1
        for c in df.columns[::-1]:
            s = df[c].astype(str).str.replace(",", "", regex=False)
            nums = pd.to_numeric(s, errors="coerce")
            nn = nums.notna().sum()
            if nn > best_nonnull:
                best_nonnull = nn
                best = nums
        if best is None:
            return pd.Series(dtype=float)
        return best

    s = df[col].astype(str).str.replace(",", "", regex=False)
    return pd.to_numeric(s, errors="coerce")


def build_driver(headless: bool = False) -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1400,1000")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


def main():
    _safe_mkdir(OUT_DIR)
    driver = build_driver(headless=False)
    driver.get(URL)

    # Give the page time to initialize
    time.sleep(3)

    results: List[ScrapeResult] = []

    try:
        for year_label, season_text in YEARS:
            for discipline, record_text in RECORDS.items():
                for sex_group, sex_text in SEXES.items():
                    # ---- Set filters ----
                    # These label_contains strings are the most likely to need tweaking.
                    # Open DevTools → Elements, find the filter labels used on the page,
                    # then update these calls accordingly.
                    set_filter_by_label_xpath(driver, "record", record_text)
                    set_filter_by_label_xpath(driver, "season", season_text)   # may be "Year" or "Season"
                    set_filter_by_label_xpath(driver, "division", DIVISION_TEXT)
                    set_filter_by_label_xpath(driver, "sex", sex_text)

                    # If there is a "Status" or "List type" filter, you can add it here:
                    # set_filter_by_label_xpath(driver, "status", "Final")

                    wait_for_table(driver)
                    df = scrape_table_to_df(driver)

                    # Save raw export
                    out_csv = f"{OUT_DIR}/CPL_{year_label}_{discipline}_{sex_group}.csv"
                    df.to_csv(out_csv, index=False)

                    results.append(ScrapeResult(
                        year_label=year_label,
                        season_text=season_text,
                        discipline=discipline,
                        sex_group=sex_group,
                        record_text=record_text,
                        rows=df
                    ))

                    print(f"Saved {out_csv} ({len(df)} rows)")

        # ---- Build summary ----
        summary_rows = []
        for r in results:
            pts = extract_points_column(r.rows)
            pts = pts.dropna()
            summary_rows.append({
                "Year": r.year_label,
                "Season": r.season_text,
                "Discipline": r.discipline,
                "Sex": r.sex_group,
                "Racers": int(len(r.rows)),
                "Total Points": float(pts.sum()) if len(pts) else 0.0,
                "Average Points": float(pts.mean()) if len(pts) else 0.0,
            })

        summary = pd.DataFrame(summary_rows)
        summary.to_csv(SUMMARY_OUT, index=False)
        print(f"\nWrote summary -> {SUMMARY_OUT}\n")

        # Optional: pivot to match your exact layout
        pivot = summary.pivot_table(
            index="Year",
            columns=["Sex", "Discipline"],
            values=["Racers", "Total Points", "Average Points"],
            aggfunc="first"
        )
        pivot.to_csv("cpl_sask_pivot_like_table.csv")
        print("Wrote pivot-like table -> cpl_sask_pivot_like_table.csv")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()