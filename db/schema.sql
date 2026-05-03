-- ============================================================
-- Quant Signal Platform — Database Schema
-- ============================================================

-- Master symbol registry
CREATE TABLE IF NOT EXISTS symbols (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(10) NOT NULL UNIQUE,
    name            TEXT,
    sector          TEXT,
    industry        TEXT,
    market_cap_tier VARCHAR(10),   -- large, mid, small
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Daily OHLCV price data (partitioned by year for query performance)
CREATE TABLE IF NOT EXISTS ohlcv_daily (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(10) NOT NULL REFERENCES symbols(symbol),
    date        DATE NOT NULL,
    open        NUMERIC(12, 4),
    high        NUMERIC(12, 4),
    low         NUMERIC(12, 4),
    close       NUMERIC(12, 4),
    adj_close   NUMERIC(12, 4),
    volume      BIGINT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_date ON ohlcv_daily(symbol, date DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_date ON ohlcv_daily(date DESC);

-- SEC filing metadata (10-K, 10-Q)
CREATE TABLE IF NOT EXISTS earnings_filings (
    id                SERIAL PRIMARY KEY,
    symbol            VARCHAR(10) NOT NULL REFERENCES symbols(symbol),
    cik               VARCHAR(20),
    form_type         VARCHAR(10),   -- 10-K, 10-Q
    filed_date        DATE,
    period_of_report  DATE,
    filing_url        TEXT,
    accession_number  VARCHAR(30) UNIQUE,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_filings_symbol ON earnings_filings(symbol, filed_date DESC);

-- Raw transcript/document text from SEC filings
CREATE TABLE IF NOT EXISTS earnings_transcripts (
    id          BIGSERIAL PRIMARY KEY,
    filing_id   INT NOT NULL REFERENCES earnings_filings(id) ON DELETE CASCADE,
    section     VARCHAR(50),   -- mda, risk_factors, full
    raw_text    TEXT,
    word_count  INT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transcripts_filing ON earnings_transcripts(filing_id);

-- Pipeline run audit log
CREATE TABLE IF NOT EXISTS ingestion_log (
    id            BIGSERIAL PRIMARY KEY,
    run_id        UUID DEFAULT gen_random_uuid(),
    dag_id        TEXT,
    task_id       TEXT,
    symbol        VARCHAR(10),
    status        VARCHAR(20),   -- success, failed, skipped
    rows_inserted INT DEFAULT 0,
    error_msg     TEXT,
    run_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_log_run_at ON ingestion_log(run_at DESC);
CREATE INDEX IF NOT EXISTS idx_log_dag ON ingestion_log(dag_id, status);

-- Seed S&P 500 large-cap symbols (top 30 to start, expand later)
INSERT INTO symbols (symbol, name, sector, market_cap_tier) VALUES
    ('AAPL',  'Apple Inc.',                   'Technology',          'large'),
    ('MSFT',  'Microsoft Corporation',         'Technology',          'large'),
    ('GOOGL', 'Alphabet Inc.',                 'Technology',          'large'),
    ('AMZN',  'Amazon.com Inc.',               'Consumer Cyclical',   'large'),
    ('NVDA',  'NVIDIA Corporation',            'Technology',          'large'),
    ('META',  'Meta Platforms Inc.',           'Technology',          'large'),
    ('TSLA',  'Tesla Inc.',                    'Consumer Cyclical',   'large'),
    ('BRK-B', 'Berkshire Hathaway Inc.',       'Financial Services',  'large'),
    ('JPM',   'JPMorgan Chase & Co.',          'Financial Services',  'large'),
    ('V',     'Visa Inc.',                     'Financial Services',  'large'),
    ('UNH',   'UnitedHealth Group Inc.',       'Healthcare',          'large'),
    ('JNJ',   'Johnson & Johnson',             'Healthcare',          'large'),
    ('XOM',   'Exxon Mobil Corporation',       'Energy',              'large'),
    ('WMT',   'Walmart Inc.',                  'Consumer Defensive',  'large'),
    ('MA',    'Mastercard Inc.',               'Financial Services',  'large'),
    ('PG',    'Procter & Gamble Co.',          'Consumer Defensive',  'large'),
    ('HD',    'Home Depot Inc.',               'Consumer Cyclical',   'large'),
    ('CVX',   'Chevron Corporation',           'Energy',              'large'),
    ('MRK',   'Merck & Co. Inc.',              'Healthcare',          'large'),
    ('ABBV',  'AbbVie Inc.',                   'Healthcare',          'large'),
    ('BAC',   'Bank of America Corp.',         'Financial Services',  'large'),
    ('KO',    'Coca-Cola Company',             'Consumer Defensive',  'large'),
    ('PEP',   'PepsiCo Inc.',                  'Consumer Defensive',  'large'),
    ('AVGO',  'Broadcom Inc.',                 'Technology',          'large'),
    ('COST',  'Costco Wholesale Corp.',        'Consumer Defensive',  'large'),
    ('ADBE',  'Adobe Inc.',                    'Technology',          'large'),
    ('CRM',   'Salesforce Inc.',               'Technology',          'large'),
    ('TMO',   'Thermo Fisher Scientific',      'Healthcare',          'large'),
    ('ACN',   'Accenture plc',                 'Technology',          'large'),
    ('AMD',   'Advanced Micro Devices Inc.',   'Technology',          'large')
ON CONFLICT (symbol) DO NOTHING;