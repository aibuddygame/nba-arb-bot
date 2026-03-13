"""
NBA Official Injury Report – compare the latest report with the 12:00 a.m ET report.

Source: https://official.nba.com/nba-injury-report-2025-26-season/

- Report date: taken from the page (the date under which reports are listed, e.g. "February 27:").
- Reports are linked in the format "hh:mm a.m/p.m ET report" (e.g. "12:00 a.m ET report").
- Latest report: the one for that date whose time is closest to (and not after) the current
  time in ET at the moment we run the comparison.
- Injury update: compares that latest report to the "12:00 a.m ET report" for the same date
  to find new or worsened injuries.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pdfplumber

# Module logger
logger = logging.getLogger(__name__)

# NBA team names as they appear in the PDF (no spaces)
NBA_TEAMS_PDF = [
    "AtlantaHawks", "BostonCeltics", "BrooklynNets", "CharlotteHornets",
    "ChicagoBulls", "ClevelandCavaliers", "DallasMavericks", "DenverNuggets",
    "DetroitPistons", "GoldenStateWarriors", "HoustonRockets", "IndianaPacers",
    "LAClippers", "LALakers", "MemphisGrizzlies", "MiamiHeat", "MilwaukeeBucks",
    "MinnesotaTimberwolves", "NewOrleansPelicans", "NewYorkKnicks",
    "OklahomaCityThunder", "OrlandoMagic", "Philadelphia76ers", "PhoenixSuns",
    "PortlandTrailBlazers", "SacramentoKings", "SanAntonioSpurs", "TorontoRaptors",
    "UtahJazz", "WashingtonWizards",
]

# Status order: worst to best (lower index = worse)
STATUS_ORDER = {"Out": 0, "Doubtful": 1, "Questionable": 2, "Probable": 3, "Available": 4}

# Display names for report (short names for readability)
TEAM_DISPLAY_NAMES = {
    "AtlantaHawks": "Atlanta", "BostonCeltics": "Boston", "BrooklynNets": "Brooklyn",
    "CharlotteHornets": "Charlotte", "ChicagoBulls": "Chicago",
    "ClevelandCavaliers": "Cleveland", "DallasMavericks": "Dallas",
    "DenverNuggets": "Denver", "DetroitPistons": "Detroit",
    "GoldenStateWarriors": "Golden State", "HoustonRockets": "Houston",
    "IndianaPacers": "Indiana", "LAClippers": "L.A. Clippers", "LALakers": "L.A. Lakers",
    "MemphisGrizzlies": "Memphis", "MiamiHeat": "Miami", "MilwaukeeBucks": "Milwaukee",
    "MinnesotaTimberwolves": "Minnesota", "NewOrleansPelicans": "New Orleans",
    "NewYorkKnicks": "New York", "OklahomaCityThunder": "Oklahoma City",
    "OrlandoMagic": "Orlando", "Philadelphia76ers": "Philadelphia",
    "PhoenixSuns": "Phoenix", "PortlandTrailBlazers": "Portland",
    "SacramentoKings": "Sacramento", "SanAntonioSpurs": "San Antonio",
    "TorontoRaptors": "Toronto", "UtahJazz": "Utah", "WashingtonWizards": "Washington",
}


@dataclass
class InjuryEntry:
    """One player line from the injury report."""
    team: str
    player: str
    status: str
    reason: str

    def key(self) -> tuple[str, str]:
        return (self.team, self.player)


def _team_display(team: str) -> str:
    return TEAM_DISPLAY_NAMES.get(team, team.replace("_", " "))


def _parse_injury_text(text: str, report_label: str) -> list[InjuryEntry]:
    """Parse full PDF text into list of InjuryEntry. Uses team names to split blocks."""
    entries: list[InjuryEntry] = []
    # Player line: "LastName,FirstName Status" or "LastName,FirstName Status Reason"
    status_re = re.compile(
        r"^([A-Za-z0-9]+[\w']*,[A-Za-z\.\s']+)\s+(Out|Doubtful|Questionable|Probable|Available)(?:\s+(.*))?$",
        re.IGNORECASE,
    )
    current_team: str | None = None
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n") if ln.strip()]
    i = 0
    while i < len(lines):
        line = lines[i]
        if "Injury Report:" in line or "GameDate" in line or line.startswith("Page"):
            i += 1
            continue
        # Check if line starts with a team name
        found_team = None
        rest_after_team = line
        for team in NBA_TEAMS_PDF:
            if line.startswith(team):
                found_team = team
                rest_after_team = line[len(team):].strip()
                break
        if found_team:
            current_team = found_team
            if not rest_after_team:
                i += 1
                continue
            line = rest_after_team
        if current_team is None:
            i += 1
            continue
        m = status_re.match(line)
        if m:
            player = m.group(1).strip()
            status = m.group(2)
            reason = (m.group(3) or "").strip()
            # One possible continuation line (reason often wraps)
            if i + 1 < len(lines):
                next_ln = lines[i + 1]
                if (
                    next_ln not in NBA_TEAMS_PDF
                    and not status_re.match(next_ln)
                    and not next_ln.startswith("NOTYETSUBMITTED")
                    and not re.match(r"^\d{2}/\d{2}/\d{4}", next_ln)
                    and not re.match(r"^\d{1,2}:\d{2}\(ET\)", next_ln)
                ):
                    reason = (reason + " " + next_ln).strip()
                    i += 1
            entries.append(InjuryEntry(team=current_team, player=player, status=status, reason=reason))
        i += 1
    return entries


def _extract_from_pdf(pdf_bytes: bytes) -> list[InjuryEntry]:
    """Extract injury entries from raw PDF bytes."""
    import io
    full_text = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                full_text.append(t)
    text = "\n".join(full_text)
    return _parse_injury_text(text, "pdf")


def _fetch_pdf(url: str) -> bytes:
    """Download PDF and return bytes."""
    r = httpx.get(url, timeout=30.0)
    r.raise_for_status()
    return r.content


INJURY_PAGE_URL = "https://official.nba.com/nba-injury-report-2025-26-season/"

# Regex for PDF links: Injury-Report_2026-02-27_12_00AM.pdf or _11_45PM.pdf
_INJURY_PDF_LINK_RE = re.compile(
    r"Injury-Report_(\d{4})-(\d{2})-(\d{2})_(\d{1,2})_(\d{2})(AM|PM)\.pdf",
    re.IGNORECASE,
)


def _suffix_to_minutes_since_midnight(suffix: str) -> int:
    """Convert '12_00AM' or '11_45PM' to minutes since midnight for ordering."""
    m = re.match(r"^(\d{1,2})_(\d{2})(AM|PM)$", suffix, re.IGNORECASE)
    if not m:
        return -1
    h, mn, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ampm == "PM" and h != 12:
        h += 12
    elif ampm == "AM" and h == 12:
        h = 0
    return h * 60 + mn


def _build_pdf_url(date: datetime, time_suffix: str) -> str:
    """Build NBA injury PDF URL. time_suffix is e.g. '12_00AM' or '11_45PM'."""
    date_str = date.strftime("%Y-%m-%d")
    return f"https://ak-static.cms.nba.com/referee/injury/Injury-Report_{date_str}_{time_suffix}.pdf"


def get_injury_report_date_from_page() -> datetime | None:
    """Scrape official NBA injury page and return the report date (e.g. today's games)."""
    try:
        r = httpx.get(INJURY_PAGE_URL, timeout=15.0)
        r.raise_for_status()
        match = re.search(r"Injury-Report_(\d{4})-(\d{2})-(\d{2})_12_00AM\.pdf", r.text)
        if match:
            y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return datetime(y, m, d, tzinfo=ZoneInfo("America/New_York"))
    except Exception as e:
        logger.warning("[INJURY] Could not get report date from page: %s", e)
    return None


def get_latest_report_suffix_from_page(
    report_date: datetime,
    now_et: datetime | None = None,
) -> str | None:
    """
    Scrape the NBA injury page and return the time suffix of the report that is
    closest to (and not after) the current ET time for that report date.

    Only considers reports under today's date on the page (same date as report_date).
    "Latest" = the report whose hh:mm a.m/p.m ET time is <= now and closest to now.

    Returns None if page cannot be fetched or no links found.
    """
    if now_et is None:
        now_et = datetime.now(ZoneInfo("America/New_York"))
    now_minutes = now_et.hour * 60 + now_et.minute
    try:
        r = httpx.get(INJURY_PAGE_URL, timeout=15.0)
        r.raise_for_status()
        y, m, d = report_date.year, report_date.month, report_date.day
        # Same calendar day for comparison (report_date is the "today" on the page)
        if (report_date.year, report_date.month, report_date.day) != (
            now_et.year,
            now_et.month,
            now_et.day,
        ):
            # Report date is not today ET: pick the last report of that day (max minutes)
            best_minutes = -1
            best_suffix: str | None = None
            for mat in _INJURY_PDF_LINK_RE.finditer(r.text):
                link_y, link_m, link_d = int(mat.group(1)), int(mat.group(2)), int(mat.group(3))
                if (link_y, link_m, link_d) != (y, m, d):
                    continue
                h, mn, ampm = int(mat.group(4)), int(mat.group(5)), mat.group(6).upper()
                suffix = f"{h}_{mn:02d}{ampm}"
                minutes = _suffix_to_minutes_since_midnight(suffix)
                if minutes > best_minutes:
                    best_minutes = minutes
                    best_suffix = suffix
            return best_suffix
        # Report date is today ET: pick report closest to now but not after now
        best_minutes = -1
        best_suffix = None
        for mat in _INJURY_PDF_LINK_RE.finditer(r.text):
            link_y, link_m, link_d = int(mat.group(1)), int(mat.group(2)), int(mat.group(3))
            if (link_y, link_m, link_d) != (y, m, d):
                continue
            h, mn, ampm = int(mat.group(4)), int(mat.group(5)), mat.group(6).upper()
            suffix = f"{h}_{mn:02d}{ampm}"
            minutes = _suffix_to_minutes_since_midnight(suffix)
            if minutes <= now_minutes and minutes > best_minutes:
                best_minutes = minutes
                best_suffix = suffix
        if best_suffix is not None:
            return best_suffix
        # All reports are in the future: use the earliest report of the day (12:00 a.m)
        for mat in _INJURY_PDF_LINK_RE.finditer(r.text):
            link_y, link_m, link_d = int(mat.group(1)), int(mat.group(2)), int(mat.group(3))
            if (link_y, link_m, link_d) != (y, m, d):
                continue
            h, mn, ampm = int(mat.group(4)), int(mat.group(5)), mat.group(6).upper()
            suffix = f"{h}_{mn:02d}{ampm}"
            if _suffix_to_minutes_since_midnight(suffix) == 0:
                return suffix
        return None
    except Exception as e:
        logger.warning("[INJURY] Could not get latest report from page: %s", e)
    return None


def _suffix_to_display_label(suffix: str) -> str:
    """Convert '11_45PM' to '11:45 p.m. ET' for display."""
    m = re.match(r"^(\d{1,2})_(\d{2})(AM|PM)$", suffix, re.IGNORECASE)
    if not m:
        return suffix
    h, mn, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    am_pm = "a.m." if ampm == "AM" else "p.m."
    return f"{h}:{mn:02d} {am_pm} ET"


def fetch_and_compare_injury_reports(
    report_date: datetime | None = None,
    first_report: str = "12_00AM",
    latest_report: str | None = None,
) -> tuple[list[InjuryEntry], list[InjuryEntry], list[tuple[InjuryEntry, str]], str]:
    """
    Fetch 12:00 a.m ET and the latest injury PDFs, parse them, and compare.

    If latest_report is None, the latest report is discovered from the official NBA
    injury page: among reports for that date, the one whose hh:mm a.m/p.m ET time
    is closest to (and not after) the current ET time.

    Returns:
        - all_entries_first: entries in the 12:00 a.m report
        - all_entries_latest: entries in the latest report
        - newly_injured: list of (entry, "new"|"status_worsened")
        - latest_report_suffix: the suffix used for the latest report (e.g. '11_45PM')
    """
    if report_date is None:
        report_date = get_injury_report_date_from_page()
    if report_date is None:
        report_date = datetime.now(ZoneInfo("America/New_York"))
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if latest_report is None:
        latest_report = get_latest_report_suffix_from_page(report_date, now_et=now_et)
    if latest_report is None:
        latest_report = "01_00AM"
        logger.warning("[INJURY] Could not discover latest report, using 01_00AM")
    url_first = _build_pdf_url(report_date, first_report)
    url_latest = _build_pdf_url(report_date, latest_report)
    logger.info("[INJURY] Fetching 12:00 a.m ET and latest (%s)", latest_report)
    try:
        first_bytes = _fetch_pdf(url_first)
        latest_bytes = _fetch_pdf(url_latest)
    except httpx.HTTPStatusError as e:
        logger.warning("[INJURY] HTTP error fetching PDFs: %s", e)
        return [], [], [], latest_report
    entries_first = _extract_from_pdf(first_bytes)
    entries_latest = _extract_from_pdf(latest_bytes)
    key_to_first = {e.key(): e for e in entries_first}
    key_to_latest = {e.key(): e for e in entries_latest}
    newly_injured: list[tuple[InjuryEntry, str]] = []
    for key, late in key_to_latest.items():
        if key not in key_to_first:
            newly_injured.append((late, "new"))
        else:
            early = key_to_first[key]
            o_early = STATUS_ORDER.get(early.status, 99)
            o_late = STATUS_ORDER.get(late.status, 99)
            if o_late < o_early:
                newly_injured.append((late, "status_worsened"))
    return entries_first, entries_latest, newly_injured, latest_report


def format_injury_update(
    newly_injured: list[tuple[InjuryEntry, str]],
    report_date: datetime | None = None,
    latest_report_label: str = "latest",
) -> str:
    """Format newly injured / status-worsened list for report or file."""
    if not newly_injured:
        return f"No new injuries or status changes between 12:00 a.m ET and {latest_report_label} reports.\n"
    lines = [
        "Injury update (new or worsened since 12:00 a.m ET report):",
        f"Compare: 12:00 a.m ET report vs latest report ({latest_report_label}).",
        "",
    ]
    if report_date:
        lines.append(f"Report date: {report_date.strftime('%Y-%m-%d')}")
        lines.append("")
    for entry, kind in newly_injured:
        team = _team_display(entry.team)
        lines.append(f"  [{kind}] {entry.player} ({team}) – {entry.status}" + (f" – {entry.reason}" if entry.reason else ""))
    return "\n".join(lines) + "\n"


def load_existing_injury_updates(data_dir: str | Path | None = None) -> str:
    """Load existing injury update text from data file if present."""
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    else:
        data_dir = Path(data_dir)
    path = data_dir / "injuries_latest.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def save_injury_updates(
    content: str,
    data_dir: str | Path | None = None,
) -> Path:
    """Append or overwrite injury update to data/injuries_latest.txt."""
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    else:
        data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "injuries_latest.txt"
    path.write_text(content, encoding="utf-8")
    return path


def run_injury_comparison_and_update(
    first_report: str = "12_00AM",
    latest_report: str | None = None,
    report_date: datetime | None = None,
    save_to_data: bool = True,
) -> tuple[list[tuple[InjuryEntry, str]], str]:
    """
    Compare 12:00 a.m ET report with the latest report of the day, format update, and optionally save.

    If latest_report is None, the latest report is discovered from the NBA injury page.

    Returns:
        (newly_injured list, formatted string). If save_to_data, also writes/updates
        data/injuries_latest.txt with the new injuries merged into existing content.
    """
    if report_date is None:
        report_date = get_injury_report_date_from_page() or datetime.now(ZoneInfo("America/New_York"))
    _, _, newly_injured, latest_suffix = fetch_and_compare_injury_reports(
        report_date=report_date,
        first_report=first_report,
        latest_report=latest_report,
    )
    latest_label = _suffix_to_display_label(latest_suffix)
    new_section = format_injury_update(newly_injured, report_date, latest_report_label=latest_label)
    if save_to_data:
        existing = load_existing_injury_updates()
        merged = existing.strip() + "\n\n" + new_section if existing.strip() else new_section
        path = save_injury_updates(merged)
        logger.info("[INJURY] Updated %s", path)
    return newly_injured, new_section


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    newly, text = run_injury_comparison_and_update()
    print(text)
    print(f"Total new/worsened: {len(newly)}")
