import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://classschedule.tulane.edu/Search.aspx"
REGISTER_URL = "https://classschedule.tulane.edu/Register/Register.aspx"
TERM_CODE = "202710"  # 2027 Spring
STATE_FILE = Path("state.json")

COURSES = {
    "10321": ("CHEM 1080-20", "General Chemistry II"),
    "39363": ("CHEM 1080-30", "General Chemistry II"),
    "40834": ("CHEM 1085-35", "General Chemistry Lab II"),
    "19723": ("CHEM 1085-37", "General Chemistry Lab II"),
    "56831": ("CHEM 1085-38", "General Chemistry Lab II"),
}
SEARCHES = sorted({sec.rsplit("-", 1)[0] for sec, _ in COURSES.values()})


def form_fields(soup):
    form = soup.find("form")
    data = {}
    for el in form.find_all("input"):
        name, kind = el.get("name"), (el.get("type") or "text").lower()
        if name and kind not in ("submit", "checkbox", "radio", "button", "image"):
            data[name] = el.get("value", "")
    for sel in form.find_all("select"):
        opt = sel.find("option", selected=True) or sel.find("option")
        if sel.get("name") and opt is not None and not sel.get("size"):
            data[sel["name"]] = opt.get("value", "")
    return data


def search(session, course):
    page = BeautifulSoup(session.get(URL, timeout=30).text, "html.parser")
    data = form_fields(page)
    data["ctl00$MenuContent$ddlterm"] = TERM_CODE
    data["ctl00$MainContent$tbcourse"] = course
    data["ctl00$MainContent$btnSearchAll"] = "Search"
    resp = session.post(URL, data=data, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    term = soup.find("select", attrs={"name": "ctl00$MenuContent$ddlterm"})
    chosen = term.find("option", selected=True) if term else None
    if not chosen or chosen.get("value") != TERM_CODE:
        raise RuntimeError(f"Search for {course} did not return term {TERM_CODE}")
    return soup


def field(block, label):
    for b in block.find_all("b"):
        if b.get_text(strip=True) == label:
            td = b.find_parent("td").find_next_sibling("td")
            return td.get_text(strip=True) if td else None
    return None


def extract(soup):
    found = {}
    for span in soup.find_all("span", string=re.compile(r"^\s*\d{5}\s*$")):
        crn = span.get_text(strip=True)
        if crn not in COURSES:
            continue
        block = span
        while block is not None and not (block.name == "table" and "1px solid" in (block.get("style") or "")):
            block = block.find_parent("table")
        if block is None:
            continue
        btn = block.find("button", class_="course-desc-link")
        onclick = btn.get("onclick", "") if btn else ""
        if f"'{TERM_CODE}'" not in onclick:
            raise RuntimeError(f"CRN {crn} result is not for term {TERM_CODE}")
        label = btn.get_text(strip=True).replace("-", " ", 1)
        if label != COURSES[crn][0]:
            raise RuntimeError(f"CRN {crn} shows {label}, expected {COURSES[crn][0]}")
        avail, maximum = field(block, "Avail. Seats"), field(block, "Max Seats")
        if avail is None or not re.fullmatch(r"-?\d+", avail):
            raise RuntimeError(f"CRN {crn}: could not read available seats ({avail!r})")
        found[crn] = {"available": int(avail), "max": maximum}
    return found


def fetch_all():
    session = requests.Session()
    session.headers["User-Agent"] = "TulaneSeatMonitor/1.0 (personal, checks every ~10 min)"
    results = {}
    for course in SEARCHES:
        results.update(extract(search(session, course)))
    missing = [c for c in COURSES if c not in results]
    if missing:
        raise RuntimeError(f"CRNs not found in search results: {', '.join(missing)}")
    return results


def notify(title, message):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC not set; would have sent:", message)
        return
    r = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": "urgent", "Tags": "rotating_light", "Click": REGISTER_URL},
        timeout=20,
    )
    r.raise_for_status()


def alert_text(crn, seats):
    section, name = COURSES[crn]
    noun = "seat" if seats == 1 else "seats"
    return (f"Tulane Seat Alert! {name} {section} (CRN {crn}) has {seats} available {noun}. "
            f"Register now: {REGISTER_URL}")


def main():
    if os.environ.get("TEST_ALERT") == "true":
        notify("Tulane Seat Monitor test", "Test alert: your Tulane seat monitor can reach your phone.")
        print("Test alert sent.")

    try:
        results = fetch_all()
    except Exception as error:
        print("CHECK FAILED (no availability reported):", error)
        sys.exit(1)

    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    new_state = {"_keepalive_month": datetime.now(timezone.utc).strftime("%Y-%m")}
    for crn, info in results.items():
        seats = info["available"]
        was_open = state.get(crn, {}).get("open", False)
        is_open = seats > 0
        print(f"{COURSES[crn][0]} (CRN {crn}): {seats} available of {info['max']}")
        if is_open and not was_open:
            notify("Tulane Seat Alert!", alert_text(crn, seats))
            print("  -> alert sent")
        new_state[crn] = {"open": is_open, "available": seats}

    if new_state != state:
        STATE_FILE.write_text(json.dumps(new_state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
