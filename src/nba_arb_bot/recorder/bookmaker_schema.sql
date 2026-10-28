-- Explicit optional extension to the P01 database; core user_version stays 1.
BEGIN IMMEDIATE;
CREATE TABLE bookmaker_component(version INTEGER NOT NULL CHECK(version=1));
INSERT INTO bookmaker_component VALUES(1);
CREATE TABLE bookmaker_raw_responses (
    sha256 TEXT PRIMARY KEY,
    body_gzip BLOB NOT NULL
);
CREATE TABLE bookmaker_captures (
    capture_id TEXT PRIMARY KEY,
    response_sha256 TEXT NOT NULL REFERENCES bookmaker_raw_responses(sha256),
    adapter_version TEXT NOT NULL,
    request_started_at TEXT NOT NULL,
    request_finished_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    bindings_json TEXT NOT NULL,
    expected_books_json TEXT NOT NULL,
    max_quote_age_seconds INTEGER,
    source_status TEXT NOT NULL,
    source_error_code TEXT
);
CREATE TABLE bookmaker_markets (
    capture_id TEXT NOT NULL REFERENCES bookmaker_captures(capture_id),
    slot_id INTEGER NOT NULL REFERENCES snapshot_slots(slot_id),
    book_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    market_type TEXT NOT NULL CHECK(market_type='moneyline'),
    period TEXT NOT NULL CHECK(period='full_game'),
    rules_ref TEXT,
    availability TEXT NOT NULL,
    source_updated_at TEXT,
    quote_age_seconds TEXT,
    lateness_seconds TEXT NOT NULL,
    flags_json TEXT NOT NULL,
    benchmark_eligible INTEGER CHECK(benchmark_eligible IN (0,1)),
    PRIMARY KEY(capture_id,slot_id,book_id)
);
CREATE TABLE bookmaker_quotes (
    capture_id TEXT NOT NULL,
    slot_id INTEGER NOT NULL,
    book_id TEXT NOT NULL,
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    original_price_json TEXT NOT NULL,
    odds_format TEXT,
    decimal_odds TEXT,
    implied_probability TEXT,
    availability TEXT NOT NULL,
    PRIMARY KEY(capture_id,slot_id,book_id,team_id),
    FOREIGN KEY(capture_id,slot_id,book_id)
      REFERENCES bookmaker_markets(capture_id,slot_id,book_id)
);
CREATE TRIGGER bookmaker_raw_no_update BEFORE UPDATE ON bookmaker_raw_responses
BEGIN SELECT RAISE(ABORT,'raw evidence is immutable'); END;
CREATE TRIGGER bookmaker_raw_no_delete BEFORE DELETE ON bookmaker_raw_responses
BEGIN SELECT RAISE(ABORT,'raw evidence is immutable'); END;
CREATE TRIGGER bookmaker_capture_no_update BEFORE UPDATE ON bookmaker_captures
BEGIN SELECT RAISE(ABORT,'captures are immutable'); END;
CREATE TRIGGER bookmaker_capture_no_delete BEFORE DELETE ON bookmaker_captures
BEGIN SELECT RAISE(ABORT,'captures are immutable'); END;
CREATE TRIGGER bookmaker_market_no_update BEFORE UPDATE ON bookmaker_markets
BEGIN SELECT RAISE(ABORT,'markets are immutable'); END;
CREATE TRIGGER bookmaker_market_no_delete BEFORE DELETE ON bookmaker_markets
BEGIN SELECT RAISE(ABORT,'markets are immutable'); END;
CREATE TRIGGER bookmaker_quote_no_update BEFORE UPDATE ON bookmaker_quotes
BEGIN SELECT RAISE(ABORT,'quotes are immutable'); END;
CREATE TRIGGER bookmaker_quote_no_delete BEFORE DELETE ON bookmaker_quotes
BEGIN SELECT RAISE(ABORT,'quotes are immutable'); END;
COMMIT;
