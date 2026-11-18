# This is vibe coded  don't look

A tiny static site that tells you whether a product on `gurapan.jp` is **in
stock** or **sold out**, with a live timer showing how many **days it has been
unavailable** since tracking began. It runs entirely on **GitHub Pages + GitHub
Actions**, so hosting costs nothing.

The tracked product is set by default to
[ST03【Zeon's Rush】開封済みスタートデッキ](https://gurapan.jp/products/detail/214418)
(product id `214418`). You can point it at any other EC-CUBE product page on
the same store by editing one constant.

---

## How it works

```
           ┌──────────────────────────┐   every 3 hours (cron)
           │   GitHub Actions workflow │
           │   scripts/check_stock.py  │
           └─────────────┬────────────┘
                         │ fetches gurapan.jp/products/detail/214418
                         │ detects stock from HTML markers
                         ▼
                  data/status.json   ◀── committed back to the repo
                         │
                         ▼
              index.html (GitHub Pages)  ◀── reads data/status.json
                  live “days unavailable” timer
```

1. **`scripts/check_stock.py`** fetches the product page with a normal browser
   User-Agent and detects the stock state from the page's own markers:
   - **Sold out** → the page contains `product_soldOut_message`, the text
     `ただいま品切れ中です`, or an `ec-blockBtn--action` button with a
     `disabled` attribute.
   - **In stock** → the page contains the `カートに入れる` (add-to-cart) text
     and no sold-out marker.
2. It writes the result into **`data/status.json`** (current status + a history
   row + product metadata) and the workflow commits the file back to `main`.
3. **GitHub Pages** serves `index.html` and `data/status.json` statically. The
   page fetches the JSON on load (and every 5 minutes) and renders the status,
   a live days/hours/minutes/seconds outage counter, a tracking summary, and a
   recent-checks table.

No server, no database, no API keys, no third-party services. The browser only
ever talks to your own GitHub Pages origin, so there are no CORS issues.

---

## Repo layout

```
.
├── index.html                      # the static page (inline CSS + JS)
├── data/
│   └── status.json                 # auto-updated by the workflow
├── scripts/
│   └── check_stock.py              # the detector run by GitHub Actions
├── .github/
│   └── workflows/
│       └── check-stock.yml         # cron + manual trigger
└── README.md
```

---

## Setup (about 5 minutes)

1. **Create a new public repository** on GitHub (e.g. `gurapan-stock-watch`).
   Public repos get free GitHub Pages and free scheduled Actions minutes.
   *Private repos need GitHub Pro/Team for Pages and burn paid Actions minutes.*

2. **Copy these files** into the repo root, preserving the folder structure:
   `index.html`, `data/status.json`, `scripts/check_stock.py`,
   `.github/workflows/check-stock.yml`, `README.md`.
   The initial `data/status.json` already contains a real reading taken when
   this project was generated, so the page works as soon as it is online.

3. **Push to GitHub** (`main` branch):
   ```bash
   git add -A
   git commit -m "init: stock watch"
   git push origin main
   ```

4. **Enable GitHub Pages:** repo → *Settings* → *Pages* → *Build and
   deployment* → **Deploy from a branch** → Branch: `main` / root → *Save*.
   Your site goes live at
   `https://<your-username>.github.io/<your-repo>/`.

5. **Enable Actions:** repo → *Settings* → *Actions* → *General* → allow all
   actions. The first scheduled run happens at the next 3-hour mark
   (`00:00, 03:00, 06:00, …` UTC). To run it immediately, go to the
   *Actions* tab → *Check stock* → *Run workflow*.

That's it. From then on the page updates itself.

---

## What the page shows

- **Status banner** — red *Sold Out* (pulsing) or green *In Stock*, with a note
  about which marker the checker found.
- **Live outage timer** — days / hours / minutes / seconds since the product
  last went out of stock (or since tracking began if it has never been in
  stock). Counts up every second while it is sold out. When it is in stock the
  timer is replaced with *Available now* and the restock timestamp.
- **Tracking summary** — tracking-since date, **total days unavailable since
  the site went up** (distinct calendar days recorded as sold out), last
  restock time, and the number of checks logged.
- **Recent checks table** — the last 15 checks with JST timestamps and colored
  status badges.
- **Auto-refresh** every 5 minutes, plus a manual *Refresh now* button.

---

## Customizing

**Track a different product.** Edit `scripts/check_stock.py`:

```python
PRODUCT_URL = "https://gurapan.jp/products/detail/214418"
PRODUCT_ID  = "214418"
```

The detection markers (`product_soldOut_message`, `ただいま品切れ中です`,
`カートに入れる`) are standard EC-CUBE, so any product on the same store works
without further changes. For a different store/platform, update the markers in
the `detect()` function. Also update the fallback `product` block near the top
of `index.html` so the page shows sensible info before the first check lands.

**Change how often it checks.** Edit the `cron:` line in
`.github/workflows/check-stock.yml`:

| Cadence          | cron            |
|------------------|-----------------|
| Hourly           | `0 * * * *`     |
| Every 3 hours    | `0 */3 * * *`   |
| Twice daily      | `0 6,18 * * *`  |
| Daily at 09:00 JST (00:00 UTC) | `0 0 * * *` |

**Local test.** The page needs to be served (opening `index.html` from disk
makes the browser block the JSON fetch). From the repo root:

```bash
python3 -m http.server 8080
# open http://localhost:8080/
```

Run the checker locally any time:

```bash
python3 scripts/check_stock.py   # writes data/status.json in place
```

---

## Notes & caveats

- **GitHub Actions cron is not exact.** Runs can drift several minutes and, by
  GitHub policy, scheduled workflows are paused after **60 days of repo
  inactivity**. Push any commit (or trigger the workflow manually) before then
  to keep it alive. For day-granularity tracking, this is more than sufficient.
- **Public repo recommended.** GitHub Pages and scheduled Actions minutes are
  free for public repos. On a private repo, Pages requires a paid plan and
  Actions minutes count against your monthly quota (the check itself uses a few
  seconds × 8 runs/day ≈ well under the free allowance, but Pages is the
  deciding factor).
- **Be polite to the store.** The checker fetches one page every few hours
  with a descriptive User-Agent — light traffic. Don't lower the interval to
  something aggressive.
- **Day counter semantics.** “Days unavailable since the site went up” counts
  distinct JST calendar days recorded as *sold out* since the tracking start
  date. If the product is sold out on the day you read this, today is included.
  The live second-by-second timer is the precise current-outage duration.
- If a check fails to reach the store, the last known status is preserved (the
  page shows *Last checked* but does not flip the banner) and an `error` row is
  recorded in history so you can see it happened.
