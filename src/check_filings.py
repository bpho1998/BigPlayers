#!/usr/bin/env python3
"""
Campaign Finance Filing Monitor
Checks SF Ethics Commission (DataSF SODA API) and Cal-Access bulk data
for new filings mentioning tracked names and organizations.
Sends Discord alerts for matches.
"""

import os
import json
import hashlib
import requests
import datetime
from pathlib import Path
from typing import Optional

# ── Tracked terms ─────────────────────────────────────────────────────────────

TRACKED_NAMES = [
    "Chris Larsen",
    "Ron Conway",
    "Sergey Brin",
    "Michael Seibel",
    "Garry Tan",
    "Arthur Rock",
    "Bill Oberndorf",
    "Michael Moritz",
    "David Sacks",
    "Jeremy Stoppelman",
    "Emmett Shear",
    "Jessica Livingston",
]

TRACKED_ORGS = [
    "Grow California",
    "Golden State Promise",
    "Fairshake",
    "FairShake",
    "Building a Better California",
    "Grow SF",
    "TogetherSF",
    "Together SF",
    "Neighbors for a Better SF",
    "Abundant SF",
    "Progress SF",
    "Stop Crime SF",
    "Forward Action SF",
    "ConnectedSF",
    "Advance SF",
    "Believe in SF",
    "SF Believes",
]

ALL_TERMS = TRACKED_NAMES + TRACKED_ORGS

# ── Paths ──────────────────────────────────────────────────────────────────────

SEEN_FILE = Path("data/seen_ids.json")

# ── DataSF / SF Ethics (SODA API) ─────────────────────────────────────────────
# Dataset: Campaign Finance – Transactions (pitq-e56w)
# Updated every 24 h; covers Forms 460, 461, 496, 497, 450.

SF_API_BASE = "https://data.sfgov.org/resource/pitq-e56w.json"
SF_FILINGS_API = "https://data.sfgov.org/resource/wo4n-ge8j.json"  # Campaign Filings Received

# ── Cal-Access bulk download ───────────────────────────────────────────────────
# The SoS provides daily tab-delimited bulk exports.
# RCPT_CD = contributions received; CVR_CAMPAIGN_DISCLOSURE_CD = cover pages.
CAL_ACCESS_URL = "https://campaignfinance.cdn.sos.ca.gov/dbwebexport.zip"

# ── Discord ───────────────────────────────────────────────────────────────────

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


def term_matches(text: str) -> list[str]:
    """Return list of tracked terms found (case-insensitive) in text."""
    text_lower = text.lower()
    return [t for t in ALL_TERMS if t.lower() in text_lower]


def row_to_text(row: dict) -> str:
    """Flatten all string values in a dict row to a searchable string."""
    return " ".join(str(v) for v in row.values() if v)


def make_id(row: dict, prefix: str) -> str:
    """Stable dedupe ID from a row's content hash."""
    raw = prefix + json.dumps(row, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def send_discord(embeds: list[dict]) -> None:
    if not DISCORD_WEBHOOK:
        print("⚠️  DISCORD_WEBHOOK_URL not set – skipping notification")
        return
    # Discord allows max 10 embeds per message
    for chunk_start in range(0, len(embeds), 10):
        chunk = embeds[chunk_start: chunk_start + 10]
        payload = {"username": "Campaign Finance Bot", "embeds": chunk}
        resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)
        resp.raise_for_status()


def discord_embed(
    title: str,
    description: str,
    color: int,
    fields: Optional[list] = None,
    url: Optional[str] = None,
) -> dict:
    embed: dict = {
        "title": title[:256],
        "description": description[:2048],
        "color": color,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "footer": {"text": "Campaign Finance Monitor"},
    }
    if url:
        embed["url"] = url
    if fields:
        embed["fields"] = fields[:25]
    return embed


# ══════════════════════════════════════════════════════════════════════════════
# SF Ethics – DataSF SODA
# ══════════════════════════════════════════════════════════════════════════════

def build_sf_where_clause() -> str:
    """
    Build a SODA $where OR clause that searches contributor/payee name fields
    for any tracked term. For broad coverage we also do a text search via $q.
    We use $q here (full-text search) and let SODA handle it server-side.
    Returns a pipe-separated search string suitable for $q.
    """
    # SODA $q does a full-text search across all indexed text columns
    return " OR ".join(f'"{t}"' for t in ALL_TERMS)


def fetch_sf_transactions(since_date: str) -> list[dict]:
    """
    Fetch SF Ethics transactions modified/filed since `since_date` (ISO date).
    Uses SODA $q full-text search for efficiency.
    """
    results = []
    limit = 1000
    offset = 0

    # Key columns that hold names: contributor_name, payee_name, filer_name,
    # committee_name, entity_name, last_name, first_name, contributor_lastname
    # We query each tracked term individually to avoid $q length limits.
    for term in ALL_TERMS:
        params = {
            "$q": term,
            "$where": f"date >= '{since_date}'",
            "$limit": limit,
            "$offset": 0,
            "$order": "date DESC",
        }
        try:
            resp = requests.get(SF_API_BASE, params=params, timeout=30)
            resp.raise_for_status()
            rows = resp.json()
            for row in rows:
                row["_matched_term"] = term
                row["_source"] = "SF Ethics"
            results.extend(rows)
        except Exception as exc:
            print(f"  SF API error for term '{term}': {exc}")

    return results


def fetch_sf_filings(since_date: str) -> list[dict]:
    """Fetch recently received campaign filings (filer/committee names)."""
    results = []
    for term in ALL_TERMS:
        params = {
            "$q": term,
            "$where": f"date_filed >= '{since_date}'",
            "$limit": 200,
            "$order": "date_filed DESC",
        }
        try:
            resp = requests.get(SF_FILINGS_API, params=params, timeout=30)
            resp.raise_for_status()
            rows = resp.json()
            for row in rows:
                row["_matched_term"] = term
                row["_source"] = "SF Filings"
            results.extend(rows)
        except Exception as exc:
            print(f"  SF Filings API error for term '{term}': {exc}")
    return results


def process_sf_row(row: dict) -> dict:
    """Extract display fields from an SF transaction row."""
    return {
        "date": row.get("date") or row.get("date_filed", ""),
        "filer": row.get("filer_name") or row.get("committee_name", ""),
        "contributor": (
            row.get("contributor_name")
            or f"{row.get('contributor_firstname','')} {row.get('contributor_lastname','')}".strip()
            or row.get("payee_name", "")
        ),
        "amount": row.get("amount") or row.get("tran_amt1", ""),
        "form_type": row.get("form_type", ""),
        "description": row.get("expenditure_description") or row.get("memo_text", ""),
        "filing_id": row.get("filing_id", ""),
        "matched_term": row.get("_matched_term", ""),
        "source": row.get("_source", "SF Ethics"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Cal-Access – bulk TSV download
# ══════════════════════════════════════════════════════════════════════════════

def fetch_calaccess_contributions() -> list[dict]:
    """
    Download Cal-Access RCPT_CD.TSV (contributions received) and search for
    tracked terms. This is a large file (~200MB compressed); we stream it.
    Returns matching rows only.
    """
    import zipfile
    import io
    import csv

    print("  Downloading Cal-Access bulk export (this may take a minute)…")
    try:
        resp = requests.get(CAL_ACCESS_URL, timeout=120, stream=True)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  Cal-Access download error: {exc}")
        return []

    raw = b""
    for chunk in resp.iter_content(chunk_size=1024 * 1024):
        raw += chunk

    matches = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            target_files = [
                "RCPT_CD.TSV",       # contributions received
                "S496_CD.TSV",       # Form 496 IE contributions
                "S497_CD.TSV",       # Form 497 late contributions
                "CVR_CAMPAIGN_DISCLOSURE_CD.TSV",  # filing cover pages
            ]
            available = zf.namelist()
            for fname in target_files:
                if fname not in available:
                    # try case-insensitive
                    fname = next((n for n in available if n.upper() == fname.upper()), None)
                if not fname:
                    continue
                print(f"  Scanning {fname}…")
                with zf.open(fname) as f:
                    reader = csv.DictReader(
                        io.TextIOWrapper(f, encoding="latin-1", errors="replace"),
                        delimiter="\t",
                    )
                    for row in reader:
                        text = row_to_text(row)
                        hits = term_matches(text)
                        if hits:
                            row["_matched_terms"] = hits
                            row["_calaccess_file"] = fname
                            row["_source"] = "Cal-Access"
                            matches.append(row)
    except Exception as exc:
        print(f"  Cal-Access parse error: {exc}")

    return matches


def process_calaccess_row(row: dict) -> dict:
    """Extract display fields from a Cal-Access row."""
    return {
        "date": row.get("RCPT_DATE") or row.get("RPT_DATE") or row.get("FILING_DATE", ""),
        "filer": row.get("FILER_NAML") or row.get("CMTE_ID", ""),
        "contributor": (
            f"{row.get('CTRIB_NAMF','')} {row.get('CTRIB_NAML','')}".strip()
            or row.get("ENTITY_CD", "")
        ),
        "amount": row.get("AMOUNT") or row.get("RCPT_AMT", ""),
        "form_type": row.get("FORM_TYPE", ""),
        "description": row.get("MEMO_CODE", "") or row.get("CTRIB_EMP", ""),
        "filing_id": row.get("FILING_ID", ""),
        "matched_term": ", ".join(row.get("_matched_terms", [])),
        "source": f"Cal-Access ({row.get('_calaccess_file','')})",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Discord embed builders
# ══════════════════════════════════════════════════════════════════════════════

COLOR_SF = 0x1a73e8       # blue
COLOR_CALACCESS = 0xe8711a  # orange
COLOR_SUMMARY = 0x2ecc71   # green


def build_embed(info: dict) -> dict:
    source = info.get("source", "")
    color = COLOR_SF if "SF" in source else COLOR_CALACCESS

    name_or_org = info.get("contributor") or info.get("filer") or "Unknown"
    term = info.get("matched_term", "")

    title = f"🔔 Match: {term[:80]}"
    description = f"**{name_or_org}** appeared in a new {source} filing."

    fields = []
    for label, key in [
        ("📅 Date", "date"),
        ("🏛️ Committee / Filer", "filer"),
        ("👤 Contributor / Payee", "contributor"),
        ("💰 Amount", "amount"),
        ("📄 Form Type", "form_type"),
        ("📝 Description", "description"),
        ("🆔 Filing ID", "filing_id"),
    ]:
        val = str(info.get(key) or "").strip()
        if val:
            fields.append({"name": label, "value": val[:1024], "inline": True})

    sf_url = None
    if "SF" in source and info.get("filing_id"):
        sf_url = f"https://public.netfile.com/pub2/?aid=sfo&filing={info['filing_id']}"

    return discord_embed(title, description, color, fields, sf_url)


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"🚀 Campaign Finance Bot starting at {datetime.datetime.utcnow().isoformat()}Z")
    seen = load_seen()
    new_seen = set()
    embeds = []

    # Look back 48 h to catch weekend/holiday gaps
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=48)).strftime("%Y-%m-%d")
    print(f"📅 Checking filings since {since}")

    # ── SF Ethics transactions ──────────────────────────────────────────────
    print("\n── SF Ethics Transactions ──")
    sf_rows = fetch_sf_transactions(since)
    print(f"  Fetched {len(sf_rows)} matching transaction rows")
    for row in sf_rows:
        uid = make_id(row, "sf_txn_")
        if uid in seen:
            continue
        new_seen.add(uid)
        info = process_sf_row(row)
        embeds.append(build_embed(info))

    # ── SF Ethics filings received ──────────────────────────────────────────
    print("\n── SF Ethics Filings Received ──")
    sf_filings = fetch_sf_filings(since)
    print(f"  Fetched {len(sf_filings)} matching filing rows")
    for row in sf_filings:
        uid = make_id(row, "sf_fil_")
        if uid in seen:
            continue
        new_seen.add(uid)
        info = process_sf_row(row)
        embeds.append(build_embed(info))

    # ── Cal-Access ──────────────────────────────────────────────────────────
    run_calaccess = os.environ.get("SKIP_CALACCESS", "").lower() not in ("1", "true", "yes")
    if run_calaccess:
        print("\n── Cal-Access Bulk Data ──")
        ca_rows = fetch_calaccess_contributions()
        print(f"  Found {len(ca_rows)} matching Cal-Access rows")
        for row in ca_rows:
            uid = make_id(row, "ca_")
            if uid in seen:
                continue
            new_seen.add(uid)
            info = process_calaccess_row(row)
            embeds.append(build_embed(info))
    else:
        print("\n── Cal-Access skipped (SKIP_CALACCESS=1) ──")

    # ── Notify ──────────────────────────────────────────────────────────────
    if embeds:
        print(f"\n📨 Sending {len(embeds)} Discord alerts…")
        # Add a summary embed at the top
        summary = discord_embed(
            title=f"📊 Campaign Finance Digest — {datetime.date.today()}",
            description=(
                f"Found **{len(embeds)} new match(es)** across SF Ethics and Cal-Access.\n"
                f"Tracked **{len(TRACKED_NAMES)} individuals** and **{len(TRACKED_ORGS)} organizations**."
            ),
            color=COLOR_SUMMARY,
        )
        send_discord([summary] + embeds)
        print("✅ Alerts sent!")
    else:
        print("\n✅ No new matches found.")

    # Save newly seen IDs
    save_seen(seen | new_seen)
    print(f"\nDone. Total seen IDs tracked: {len(seen | new_seen)}")


if __name__ == "__main__":
    main()
