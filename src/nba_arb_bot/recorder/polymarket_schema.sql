-- Explicit additive P03 extension, independent of the optional bookmaker archive.
BEGIN IMMEDIATE;
CREATE TABLE polymarket_component(version INTEGER NOT NULL CHECK(version=1));
INSERT INTO polymarket_component VALUES(1);
CREATE TABLE polymarket_bindings (
    binding_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(game_id),
    event_id TEXT NOT NULL,
    market_id TEXT NOT NULL UNIQUE,
    condition_id TEXT NOT NULL UNIQUE,
    rules_ref TEXT,
    observed_at TEXT NOT NULL,
    evidence TEXT NOT NULL
);
CREATE TABLE polymarket_bound_outcomes (
    binding_id TEXT NOT NULL REFERENCES polymarket_bindings(binding_id),
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    asset_id TEXT NOT NULL UNIQUE,
    PRIMARY KEY(binding_id,team_id),
    UNIQUE(binding_id,team_id,asset_id)
);
CREATE TABLE polymarket_raw_responses(sha256 TEXT PRIMARY KEY,body_gzip BLOB NOT NULL);
CREATE TABLE polymarket_captures (
    capture_id TEXT PRIMARY KEY,
    response_sha256 TEXT NOT NULL REFERENCES polymarket_raw_responses(sha256),
    adapter_version TEXT NOT NULL,
    request_started_at TEXT NOT NULL,
    request_finished_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    slots_json TEXT NOT NULL,
    max_quote_age_seconds INTEGER,
    max_levels INTEGER NOT NULL,
    source_status TEXT NOT NULL,
    source_error_code TEXT
);
CREATE TABLE polymarket_markets (
    capture_id TEXT NOT NULL REFERENCES polymarket_captures(capture_id),
    binding_id TEXT NOT NULL REFERENCES polymarket_bindings(binding_id),
    slot_id INTEGER NOT NULL REFERENCES snapshot_slots(slot_id),
    availability TEXT NOT NULL,
    source_rules_ref TEXT,
    fees_json TEXT NOT NULL,
    flags_json TEXT NOT NULL,
    PRIMARY KEY(capture_id,binding_id)
);
CREATE TABLE polymarket_quotes (
    capture_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    availability TEXT NOT NULL,
    best_bid TEXT,
    best_bid_size TEXT,
    best_ask TEXT,
    best_ask_size TEXT,
    midpoint TEXT,
    last_trade_price TEXT,
    last_trade_at TEXT,
    source_updated_at TEXT,
    quote_age_seconds TEXT,
    lateness_seconds TEXT NOT NULL,
    depth_complete INTEGER CHECK(depth_complete IN (0,1)),
    flags_json TEXT NOT NULL,
    research_eligible INTEGER CHECK(research_eligible IN (0,1)),
    cost_metadata_complete INTEGER NOT NULL CHECK(cost_metadata_complete IN (0,1)),
    PRIMARY KEY(capture_id,binding_id,team_id),
    FOREIGN KEY(capture_id,binding_id) REFERENCES polymarket_markets(capture_id,binding_id),
    FOREIGN KEY(binding_id,team_id,asset_id)
      REFERENCES polymarket_bound_outcomes(binding_id,team_id,asset_id)
);
CREATE TABLE polymarket_levels (
    capture_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('bid','ask')),
    rank INTEGER NOT NULL CHECK(rank>=0),
    price TEXT NOT NULL,
    size TEXT NOT NULL,
    PRIMARY KEY(capture_id,binding_id,team_id,side,rank),
    FOREIGN KEY(capture_id,binding_id,team_id)
      REFERENCES polymarket_quotes(capture_id,binding_id,team_id)
);
CREATE TRIGGER polymarket_bindings_no_update BEFORE UPDATE ON polymarket_bindings
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_bindings_no_delete BEFORE DELETE ON polymarket_bindings
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_bound_outcomes_no_update BEFORE UPDATE ON polymarket_bound_outcomes
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_bound_outcomes_no_delete BEFORE DELETE ON polymarket_bound_outcomes
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_raw_responses_no_update BEFORE UPDATE ON polymarket_raw_responses
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_raw_responses_no_delete BEFORE DELETE ON polymarket_raw_responses
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_captures_no_update BEFORE UPDATE ON polymarket_captures
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_captures_no_delete BEFORE DELETE ON polymarket_captures
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_markets_no_update BEFORE UPDATE ON polymarket_markets
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_markets_no_delete BEFORE DELETE ON polymarket_markets
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_quotes_no_update BEFORE UPDATE ON polymarket_quotes
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_quotes_no_delete BEFORE DELETE ON polymarket_quotes
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_levels_no_update BEFORE UPDATE ON polymarket_levels
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
CREATE TRIGGER polymarket_levels_no_delete BEFORE DELETE ON polymarket_levels
BEGIN SELECT RAISE(ABORT,'Polymarket evidence is immutable'); END;
COMMIT;
