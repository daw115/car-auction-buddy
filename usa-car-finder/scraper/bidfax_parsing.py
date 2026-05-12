"""Pure HTML / URL parsing for bidfax.info results.

Browser-free — easy to unit-test and import without the rest of the
bidfax stack.
"""

from __future__ import annotations

import re

try:
    from bs4 import BeautifulSoup
    _DEPS_OK = True
except ImportError:
    _DEPS_OK = False


IN_PROGRESS = "In Progress"

RESULT_URL_RE = re.compile(r'^https://bidfax\.info/[^/]+/[^/]+/.+\.html$')
VIN_FROM_URL_RE = re.compile(r'-vin-([a-z0-9]+)\.html$', re.IGNORECASE)


def url_make_matches(csv_make: str, bidfax_url: str) -> bool:
    parts = bidfax_url.replace("https://bidfax.info/", "").split("/")
    url_make = parts[0].lower() if parts else ""
    norm = re.sub(r"[\s_]+", "-", csv_make.strip().lower())
    return bool(url_make) and (
        url_make == norm
        or norm.startswith(url_make)
        or url_make.startswith(norm)
    )


def extract_grid_result(html: str) -> tuple[str, str, str] | None:
    """Parse bidfax results-page HTML. Returns (price, vin, url) or None.

    None = no result grid (either homepage bounce or genuine no-result).
    Callers distinguish via homepage marker detection.
    """
    if not _DEPS_OK:
        return None
    soup = BeautifulSoup(html, "lxml")
    grid = soup.find(id="grid")
    if not grid:
        return None
    url = next(
        (str(a["href"]) for a in grid.find_all("a", href=True)
         if RESULT_URL_RE.match(str(a["href"]))),
        None,
    )
    if not url:
        return None
    m_vin = VIN_FROM_URL_RE.search(url)
    vin = m_vin.group(1).upper() if m_vin else ""
    price = IN_PROGRESS
    span = grid.find("span", class_="prices")
    if span:
        raw = span.get_text(strip=True)
        if raw.isdigit():
            price = f"${int(raw):,}"
    return price, vin, url
