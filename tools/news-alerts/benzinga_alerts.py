"""Poll a Gmail label for Benzinga emails, alert to Telegram, and record
tickers with fresh news in a catalyst file other scripts can read.

Env: GMAIL_USER, GMAIL_APP_PASSWORD, TG_TOKEN, TG_CHAT_ID
Optional: BZ_LABEL (default "benzinga"), CATALYST_FILE, POLL_SEC
"""
import email
import html
import imaplib
import json
import os
import re
import tempfile
import time
from email.header import decode_header, make_header

import requests

LABEL = os.environ.get("BZ_LABEL", "benzinga")
POLL_SEC = int(os.environ.get("POLL_SEC", "15"))
CATALYST_FILE = os.environ.get("CATALYST_FILE", "/tmp/catalysts.json")  # {"TICKER": unix_ts}
CATALYST_TTL = 900  # 15 min window

# $AAPL, (AAPL), (NASDAQ:AAPL), (NYSE: BRK.B) -- Benzinga mostly uses the exchange form.
TICKER_RE = re.compile(
    r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b"
    r"|\((?:NASDAQ|NYSE|NYSEARCA|NYSEAMERICAN|AMEX|OTC|OTCQX|OTCQB|CBOE|BATS)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\)"
    r"|\(([A-Z]{1,5})\)"
)
# Bare "(XYZ)" matches that are acronyms, not tickers.
NOT_TICKERS = {
    "CEO", "CFO", "COO", "CTO", "FDA", "SEC", "FTC", "DOJ", "EPS", "IPO", "ETF",
    "USD", "EUR", "GDP", "CPI", "PPI", "FOMC", "AI", "EV", "US", "USA", "UK", "EU",
    "Q", "PR", "ET", "EST", "EDT", "PT", "PDT", "PST", "NDA", "BLA", "PDUFA",
    "OTC", "NYSE", "AMEX", "YOY", "QOQ", "TTM", "ADR", "ESG", "M", "B", "K",
}


def tg(text):
    r = requests.post(
        f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
        json={"chat_id": os.environ["TG_CHAT_ID"], "text": text[:4000],
              "disable_web_page_preview": True},
        timeout=10,
    )
    r.raise_for_status()


def _decode(part):
    raw = part.get_payload(decode=True)
    if raw is None:
        return ""
    return raw.decode(part.get_content_charset() or "utf-8", errors="replace")


def _strip_html(h):
    h = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", h)
    return html.unescape(re.sub(r"<[^>]+>", " ", h))


def body_text(msg):
    parts = list(msg.walk()) if msg.is_multipart() else [msg]
    for p in parts:
        if p.get_content_type() == "text/plain":
            return _decode(p)
    for p in parts:
        if p.get_content_type() == "text/html":
            return _strip_html(_decode(p))
    return ""


def extract_tickers(text):
    out = set()
    for dollar, exch, paren in TICKER_RE.findall(text):
        if dollar or exch:
            out.add(dollar or exch)
        elif paren not in NOT_TICKERS:
            out.add(paren)
    return out


def update_catalysts(tickers, now=None):
    now = now or time.time()
    try:
        with open(CATALYST_FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d = {k: v for k, v in d.items() if now - v < CATALYST_TTL}
    for t in tickers:
        d[t] = now
    # Atomic replace so a reader never sees a half-written file.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CATALYST_FILE) or ".")
    with os.fdopen(fd, "w") as f:
        json.dump(d, f)
    os.replace(tmp, CATALYST_FILE)


def connect():
    m = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
    m.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
    typ, _ = m.select(f'"{LABEL}"')
    if typ != "OK":
        raise RuntimeError(f"cannot select label {LABEL!r}")
    return m


def handle(m, num):
    # BODY.PEEK so the message is only marked read after the alert actually went out.
    typ, raw = m.fetch(num, "(BODY.PEEK[])")
    if typ != "OK" or not raw or raw[0] is None:
        return
    msg = email.message_from_bytes(raw[0][1])
    subj = str(make_header(decode_header(msg["Subject"] or "")))
    tickers = extract_tickers(subj + " " + body_text(msg)[:1500])
    update_catalysts(tickers)
    tag = " ".join("$" + t for t in sorted(tickers))
    tg(f"[NEWS] {subj}" + (f"\n{tag}" if tag else ""))
    m.store(num, "+FLAGS", "\\Seen")


def poll(m):
    m.noop()  # surfaces a dead connection before searching
    typ, data = m.search(None, "UNSEEN")
    if typ != "OK":
        raise RuntimeError("search failed")
    for num in data[0].split():
        try:
            handle(m, num)
        except (requests.RequestException, imaplib.IMAP4.abort, OSError):
            raise  # transport problem: leave unread, reconnect, retry
        except Exception as e:
            # Unparseable message: mark read so it doesn't block every poll.
            print(f"skip msg {num!r}: {e!r}")
            m.store(num, "+FLAGS", "\\Seen")


def main():
    m = None
    while True:
        try:
            if m is None:
                m = connect()
            poll(m)
        except Exception as e:
            print("poll error:", repr(e))
            try:
                if m is not None:
                    m.logout()
            except Exception:
                pass
            m = None
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
