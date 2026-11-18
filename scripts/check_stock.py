#!/usr/bin/env python3
"""
check_stock.py — stock status checker for a gurapan.jp (EC-CUBE) product.

Runs on a schedule inside GitHub Actions. It fetches the product page, detects
whether the item is in stock or sold out from the page's own markers, updates
data/status.json (current state + history), and leaves the file for git to
commit. Safe to re-run any number of times.

Detection rules (EC-CUBE template):
  * sold_out  -> page contains `product_soldOut_message`, the text
                 `ただいま品切れ中です`, or a cart button with `disabled`.
  * in_stock  -> page contains the `カートに入れる` (add to cart) text and no
                 sold-out marker.
  * error     -> the fetch itself failed; the last known status is preserved
                 and an `error` row is recorded in history.
  * unknown   -> page fetched fine but none of the markers matched (template
                 changed?); recorded as-is so you can investigate.

Exit code is always 0 so a transient fetch failure never fails the workflow.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PRODUCT_URL = "https://gurapan.jp/products/detail/214418"
PRODUCT_ID = "214418"
SITE_NAME = "gurapan.jp"

# Resolve the status file relative to this script (repo root / data / status.json).
REPO_ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = REPO_ROOT / "data" / "status.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; StockWatchBot/1.0; "
    "+https://github.com/) Stock-status tracker for a single product page."
)

JST = timezone(timedelta(hours=9))

# Only append a same-status history entry if this many minutes have passed since
# the last entry, to keep history compact across frequent runs.
DEDUP_MINUTES = 30
# Hard cap on history length (status-change rows are always within this window
# because they are recent relative to capped tail).
HISTORY_CAP = 2000


# ---------------------------------------------------------------------------
# Fetch + detect
# ---------------------------------------------------------------------------
def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    # The site serves UTF-8. Fall back gracefully if anything is off.
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def detect(html: str) -> str:
    """Return 'in_stock', 'sold_out', or 'unknown'."""
    has_soldout_msg = "product_soldOut_message" in html
    has_zaiore_text = "ただいま品切れ中です" in html
    has_cart_text = "カートに入れる" in html
    has_disabled_cart = bool(
        re.search(r'class="ec-blockBtn--action"[^>]*\bdisabled\b', html, re.I)
    )

    if has_soldout_msg or has_zaiore_text or has_disabled_cart:
        return "sold_out"
    if has_cart_text:
        return "in_stock"
    return "unknown"


def html_unescape(s: str) -> str:
    return (
        s.replace("&amp;", "&")
        .replace("&#039;", "'")
        .replace("&apos;", "'")
        .replace("&quot;", '"')
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def extract_meta(html: str) -> dict:
    meta = {}
    m = re.search(r'property="og:title"\s+content="([^"]+)"', html)
    if m:
        meta["name"] = html_unescape(m.group(1))
    m = re.search(r'property="og:image"\s+content="([^"]+)"', html)
    if m:
        meta["image"] = m.group(1)
    m = re.search(r"販売価格.*?(￥[\d,]+)", html, re.S)
    if m:
        meta["price"] = f"{m.group(1)} (税込)"
    return meta


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_jst_string() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")


def parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def new_skeleton() -> dict:
    now = now_utc_iso()
    return {
        "product": {
            "name": None,
            "url": PRODUCT_URL,
            "image": None,
            "price": None,
            "site": SITE_NAME,
            "id": PRODUCT_ID,
        },
        "tracking": {"started_at": now, "timezone": "Asia/Tokyo"},
        "current": {
            "status": None,
            "checked_at": now,
            "checked_at_local": now_jst_string(),
        },
        "last_available_at": None,
        "last_change_at": None,
        "history": [],
    }


def main() -> int:
    # ---- Fetch + detect ---------------------------------------------------
    status = "error"
    meta: dict = {}
    try:
        html = fetch(PRODUCT_URL)
        status = detect(html)
        meta = extract_meta(html)
    except Exception as exc:  # network / HTTP errors -> record, keep last known
        print(f"::warning::fetch failed: {exc}")

    # ---- Load existing data ----------------------------------------------
    if STATUS_FILE.exists():
        try:
            data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("::warning::status.json was malformed; resetting to skeleton")
            data = new_skeleton()
    else:
        data = new_skeleton()

    # Make sure required keys exist (tolerant of older schemas).
    data.setdefault("product", {}).setdefault("url", PRODUCT_URL)
    data.setdefault("tracking", {}).setdefault("timezone", "Asia/Tokyo")
    data.setdefault("current", {})
    data.setdefault("history", [])
    data.setdefault("last_available_at", None)
    data.setdefault("last_change_at", None)

    now = now_utc_iso()
    jst = now_jst_string()
    prev_status = data["current"].get("status")

    # ---- Refresh product meta (name / image / price) ---------------------
    data["product"]["url"] = PRODUCT_URL
    data["product"]["site"] = SITE_NAME
    data["product"]["id"] = PRODUCT_ID
    if meta.get("name"):
        data["product"]["name"] = meta["name"]
    if meta.get("image"):
        data["product"]["image"] = meta["image"]
    if meta.get("price"):
        data["product"]["price"] = meta["price"]

    # ---- Update current state --------------------------------------------
    if status == "error":
        # Keep the last known status, but refresh "last checked" so the page
        # shows the bot is still alive. Record the error in history.
        data["current"]["checked_at"] = now
        data["current"]["checked_at_local"] = jst
        data["current"]["last_error"] = now
        data["history"].append({"at": now, "status": "error"})
    else:
        data["current"] = {
            "status": status,
            "checked_at": now,
            "checked_at_local": jst,
        }
        data["current"].pop("last_error", None)

        # A genuine status change.
        if status != prev_status:
            data["last_change_at"] = now
            if status == "in_stock":
                data["last_available_at"] = now

        # Append a history row (with dedup for noisy same-status runs).
        last = data["history"][-1] if data["history"] else None
        should_append = True
        if last and last.get("status") == status:
            t_last = parse_iso(last.get("at", ""))
            t_now = parse_iso(now)
            if t_last and t_now and (t_now - t_last).total_seconds() < DEDUP_MINUTES * 60:
                should_append = False
        if should_append:
            data["history"].append({"at": now, "status": status})

    # Cap history length.
    if len(data["history"]) > HISTORY_CAP:
        data["history"] = data["history"][-HISTORY_CAP:]

    # ---- Persist ---------------------------------------------------------
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"status={status} prev={prev_status} checked_at={now} "
        f"jst={jst} history_len={len(data['history'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
