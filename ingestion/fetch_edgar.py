"""
ingestion/fetch_edgar.py

Pulls 10-K and 10-Q filing metadata + MD&A text from SEC EDGAR
for all active symbols. Uses the free EDGAR full-text search API.
No API key required — only a User-Agent header (SEC policy).
"""

import os
import logging
import time
import re
from datetime import date

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from db.db_client import get_conn, execute_many, log_run

load_dotenv()

logger = logging.getLogger(__name__)

EDGAR_HEADERS = {
    "User-Agent": os.getenv(
        "SEC_USER_AGENT",
        "Quant Platform quant@example.com"   # update in .env
    ),
    "Accept-Encoding": "gzip, deflate",
}

EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_FILING_URL      = "https://www.sec.gov/Archives/edgar/{path}"
EDGAR_CIK_LOOKUP      = "https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt=2020-01-01&enddt=2030-01-01&forms=10-K,10-Q"


# ── CIK lookup ────────────────────────────────────────────────────────────────

def get_cik(symbol: str) -> str | None:
    """Resolve a ticker to an SEC CIK number."""
    url = f"https://efts.sec.gov/LATEST/search-index?q=%22{symbol}%22&forms=10-K"
    try:
        r = requests.get(url, headers=EDGAR_HEADERS, timeout=10)
        r.raise_for_status()
        hits = r.json().get("hits", {}).get("hits", [])
        for hit in hits:
            tickers = hit.get("_source", {}).get("tickers", [])
            if symbol.upper() in [t.upper() for t in tickers]:
                return hit["_source"].get("entity_id", "").lstrip("0")
    except Exception as e:
        logger.warning(f"CIK lookup failed for {symbol}: {e}")
    return None


def get_cik_from_ticker_json(symbol: str) -> str | None:
    """
    Alternative CIK lookup using SEC's company_tickers.json.
    More reliable for well-known S&P 500 names.
    """
    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=EDGAR_HEADERS, timeout=10
        )
        r.raise_for_status()
        data = r.json()
        for entry in data.values():
            if entry.get("ticker", "").upper() == symbol.upper():
                return str(entry["cik_str"])
    except Exception as e:
        logger.warning(f"company_tickers.json lookup failed: {e}")
    return None


# ── Filing metadata ───────────────────────────────────────────────────────────

def get_filings_metadata(cik: str, forms: list[str] = None) -> list[dict]:
    """
    Pull recent filing metadata from EDGAR submissions API.
    Returns list of dicts with form_type, filed_date, accession_number, etc.
    """
    if forms is None:
        forms = ["10-K", "10-Q"]

    cik_padded = cik.zfill(10)
    url = EDGAR_SUBMISSIONS_URL.format(cik=cik_padded)

    try:
        r = requests.get(url, headers=EDGAR_HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f"Submissions API error for CIK {cik}: {e}")
        return []

    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return []

    form_types        = recent.get("form", [])
    filed_dates       = recent.get("filingDate", [])
    report_dates      = recent.get("reportDate", [])
    accession_numbers = recent.get("accessionNumber", [])

    results = []
    for i, form in enumerate(form_types):
        if form not in forms:
            continue
        acc = accession_numbers[i].replace("-", "")
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/full-index/"
            f"{filed_dates[i][:4]}/QTR{((int(filed_dates[i][5:7])-1)//3)+1}/"
        )
        results.append({
            "form_type":         form,
            "filed_date":        filed_dates[i],
            "period_of_report":  report_dates[i] if i < len(report_dates) else None,
            "accession_number":  accession_numbers[i],
            "cik":               cik,
            "filing_url":        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}",
        })

    return results


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_mda_text(accession_number: str, cik: str) -> str | None:
    """
    Attempt to extract Management Discussion & Analysis section
    from a 10-K or 10-Q filing. Returns raw text or None.
    """
    cik_padded  = cik.zfill(10)
    acc_dashed  = f"{accession_number[:10]}-{accession_number[10:12]}-{accession_number[12:]}"
    acc_nodash  = accession_number.replace("-", "")
    index_url   = f"https://www.sec.gov/Archives/edgar/{cik_padded}/{acc_nodash}/{acc_dashed}-index.htm"

    try:
        r = requests.get(index_url, headers=EDGAR_HEADERS, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "lxml")
        # Find the primary document link (10-K or 10-Q htm file)
        doc_link = None
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 3:
                doc_type = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                if doc_type in ("10-K", "10-Q"):
                    a_tag = cells[2].find("a")
                    if a_tag:
                        doc_link = "https://www.sec.gov" + a_tag["href"]
                        break

        if not doc_link:
            return None

        r2 = requests.get(doc_link, headers=EDGAR_HEADERS, timeout=20)
        if r2.status_code != 200:
            return None

        filing_soup = BeautifulSoup(r2.text, "lxml")
        text = filing_soup.get_text(separator=" ", strip=True)

        # Crude but effective MDA extraction — find section boundaries
        mda_pattern = re.compile(
            r"(item\s+7\.?\s+management.{0,30}discussion)",
            re.IGNORECASE
        )
        match = mda_pattern.search(text)
        if match:
            start = match.start()
            # Take ~15,000 chars of MDA — enough context without entire filing
            return text[start : start + 15000]

        return text[:10000]  # Fallback: return beginning of filing

    except Exception as e:
        logger.warning(f"Text extraction failed for {accession_number}: {e}")
        return None


# ── DB writes ─────────────────────────────────────────────────────────────────

FILING_UPSERT = """
    INSERT INTO earnings_filings
        (symbol, cik, form_type, filed_date, period_of_report,
         filing_url, accession_number)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (accession_number) DO NOTHING
    RETURNING id
"""

TRANSCRIPT_INSERT = """
    INSERT INTO earnings_transcripts (filing_id, section, raw_text, word_count)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT DO NOTHING
"""


def save_filing(symbol: str, filing: dict) -> int | None:
    """Insert filing metadata and return the new row id."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(FILING_UPSERT, (
                symbol,
                filing["cik"],
                filing["form_type"],
                filing["filed_date"] or None,
                filing["period_of_report"] or None,
                filing["filing_url"],
                filing["accession_number"],
            ))
            row = cur.fetchone()
            return row[0] if row else None


def save_transcript(filing_id: int, section: str, text: str):
    word_count = len(text.split()) if text else 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(TRANSCRIPT_INSERT, (filing_id, section, text, word_count))


# ── Main entry point ──────────────────────────────────────────────────────────

def run_edgar_ingestion(
    symbols: list[str] | None = None,
    max_filings_per_symbol: int = 8,
    rate_limit_sleep: float = 0.5,
) -> dict:
    """
    Main entry point called by the Airflow DAG.
    Pulls filing metadata + MDA text for all active symbols.
    """
    if symbols is None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT symbol FROM symbols WHERE active = TRUE ORDER BY symbol")
                symbols = [r[0] for r in cur.fetchall()]

    summary = {"success": [], "failed": [], "total_filings": 0}

    for symbol in symbols:
        logger.info(f"Processing EDGAR filings for {symbol}")
        try:
            cik = get_cik_from_ticker_json(symbol)
            if not cik:
                logger.warning(f"Could not resolve CIK for {symbol}, skipping")
                summary["failed"].append(symbol)
                continue

            filings = get_filings_metadata(cik)[:max_filings_per_symbol]

            for filing in filings:
                filing_id = save_filing(symbol, filing)
                if not filing_id:
                    continue  # already exists

                time.sleep(rate_limit_sleep)
                mda_text = extract_mda_text(
                    filing["accession_number"].replace("-", ""), cik
                )
                if mda_text:
                    save_transcript(filing_id, "mda", mda_text)

                summary["total_filings"] += 1
                time.sleep(rate_limit_sleep)

            summary["success"].append(symbol)
            log_run("edgar_dag", "fetch_filings", symbol, "success",
                    len(filings))

        except Exception as e:
            logger.error(f"EDGAR ingestion failed for {symbol}: {e}")
            summary["failed"].append(symbol)
            log_run("edgar_dag", "fetch_filings", symbol, "failed",
                    error_msg=str(e))

        time.sleep(rate_limit_sleep)

    logger.info(
        f"EDGAR complete — {len(summary['success'])} succeeded, "
        f"{len(summary['failed'])} failed, {summary['total_filings']} filings stored"
    )
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Test with 3 symbols first
    result = run_edgar_ingestion(symbols=["AAPL", "MSFT", "NVDA"], max_filings_per_symbol=4)
    print(result)