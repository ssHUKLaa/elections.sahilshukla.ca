"""Download Illinois State Board of Elections' 2026 general candidate export."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests


URL = "https://www.elections.il.gov/ElectionOperations/CandidateFilingSearch.aspx?ID=sejIrI%2BQmww%3D"


class HiddenInputs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "input" and attr.get("type", "").lower() == "hidden" and attr.get("name"):
            self.values[attr["name"]] = attr.get("value", "")


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "us2026forecast-ballot-inventory/0.1", "Accept-Encoding": "identity"})
    first = session.get(URL, timeout=45)
    first.raise_for_status()
    parser = HiddenInputs()
    parser.feed(first.text)
    if "__VIEWSTATE" not in parser.values:
        raise ValueError("Illinois ASP.NET view state missing")
    form = dict(parser.values)
    form.update({
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$btnDownloadCanFiles",
        "__EVENTARGUMENT": "",
    })
    response = session.post(URL, data=form, timeout=120)
    response.raise_for_status()
    if "DownloadCandidates.aspx" not in response.url or "__VIEWSTATE" not in response.text:
        raise ValueError("Illinois candidate download form did not open")
    download_form = HiddenInputs()
    download_form.feed(response.text)
    second = dict(download_form.values)
    second.update({
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$btnText",
        "__EVENTARGUMENT": "",
    })
    response = session.post(response.url, data=second, timeout=120)
    response.raise_for_status()
    payload = response.content
    if len(payload) < 1000 or payload.lstrip().lower().startswith((b"<!doctype", b"<html")):
        raise ValueError(f"Illinois export returned HTML or small response: {response.headers.get('Content-Type')}")
    timestamp = datetime.now(timezone.utc)
    output_dir = Path("data/raw/state_ballots") / (timestamp.strftime("%Y%m%dT%H%M%SZ") + "-IL")
    output_dir.mkdir(parents=True, exist_ok=False)
    path = output_dir / "IL_candidate_export.bin"
    path.write_bytes(payload)
    meta = {
        "url": URL, "retrieved_at_utc": timestamp.isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
        "content_type": response.headers.get("Content-Type"),
    }
    (output_dir / "manifest.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {path}: {len(payload):,} bytes, {meta['content_type']}")


if __name__ == "__main__":
    main()
