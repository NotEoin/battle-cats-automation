"""Parse a bc.godfat.org table into {(index, track): cat name}.

Used only to check our own engine against the reference implementation.  The
page interleaves the two tracks: a row labelled NnA carries track B's cat for
position n-1, and the row labelled NnB carries track A's cat for position n.
"""

from bs4 import BeautifulSoup


def parse(html: str) -> dict[tuple[int, int], str]:
    """The page's roll table as {(index, track): cat name}."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    out: dict[tuple[int, int], str] = {}
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        ids = [c.get("id") for c in cells if c.get("id")]
        label = ids[0] if ids else None

        def catname(cell):
            a = cell.find("a")
            return a.get_text(strip=True) if a else None

        cats = [c for c in cells if "cat" in (c.get("class") or [])]
        if label and label.endswith("B"):
            # First cat cell on this row is track A of this index.
            n = int(label[1:-1])
            if cats and catname(cats[0]):
                out[(n, 0)] = catname(cats[0])
        elif label and label.endswith("A"):
            # Any cat cell here belongs to track B of the previous index.
            n = int(label[1:-1])
            named = [catname(c) for c in cats if catname(c)]
            if named and n > 1:
                out[(n - 1, 1)] = named[0]
    return out


def parse_guaranteed(html: str) -> dict[tuple[int, int], tuple[str, str]]:
    """Like parse(), but returns (cat, guaranteed uber) for guaranteed banners."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[tuple[int, int], tuple[str, str]] = {}
    for tr in soup.find("table").find_all("tr"):
        cells = tr.find_all("td")
        ids = [c.get("id") for c in cells if c.get("id")]
        if not ids:
            continue
        label = ids[0]
        cats = [c for c in cells if "cat" in (c.get("class") or [])]

        def catname(cell):
            a = cell.find("a")
            return a.get_text(strip=True) if a else None

        if label.endswith("B"):
            n = int(label[1:-1])
            if len(cats) >= 2 and catname(cats[0]) and catname(cats[1]):
                out[(n, 0)] = (catname(cats[0]), catname(cats[1]))
        elif label.endswith("A") and int(label[1:-1]) > 1:
            named = [catname(c) for c in cats if catname(c)]
            if len(named) >= 2:
                out[(int(label[1:-1]) - 1, 1)] = (named[0], named[1])
    return out
