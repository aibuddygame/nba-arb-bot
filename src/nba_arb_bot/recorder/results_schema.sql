BEGIN IMMEDIATE;
CREATE TABLE results_component(version INTEGER NOT NULL CHECK(version=1));
INSERT INTO results_component VALUES(1);
CREATE TABLE result_raw_responses(sha256 TEXT PRIMARY KEY,body_gzip BLOB NOT NULL);
CREATE TABLE game_result_versions (
    record_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(game_id),
    revision_id INTEGER NOT NULL REFERENCES schedule_revisions(revision_id),
    source TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version>=1),
    supersedes_record_id TEXT REFERENCES game_result_versions(record_id),
    status TEXT NOT NULL,
    away_score INTEGER,
    home_score INTEGER,
    winner_team_id TEXT REFERENCES teams(team_id),
    published_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    final_at TEXT,
    response_sha256 TEXT NOT NULL REFERENCES result_raw_responses(sha256),
    input_json TEXT NOT NULL,
    UNIQUE(game_id,source,version)
);
CREATE TABLE resolution_versions (
    record_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL REFERENCES polymarket_bindings(binding_id),
    source TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version>=1),
    supersedes_record_id TEXT REFERENCES resolution_versions(record_id),
    status TEXT NOT NULL,
    published_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    resolved_at TEXT,
    response_sha256 TEXT NOT NULL REFERENCES result_raw_responses(sha256),
    input_json TEXT NOT NULL,
    UNIQUE(binding_id,source,version)
);
CREATE TABLE resolution_payouts (
    record_id TEXT NOT NULL REFERENCES resolution_versions(record_id),
    binding_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    payout TEXT,
    PRIMARY KEY(record_id,team_id),
    FOREIGN KEY(binding_id,team_id,asset_id)
      REFERENCES polymarket_bound_outcomes(binding_id,team_id,asset_id)
);
CREATE TRIGGER result_raw_responses_no_update BEFORE UPDATE ON result_raw_responses
BEGIN SELECT RAISE(ABORT,'results evidence is immutable'); END;
CREATE TRIGGER result_raw_responses_no_delete BEFORE DELETE ON result_raw_responses
BEGIN SELECT RAISE(ABORT,'results evidence is immutable'); END;
CREATE TRIGGER game_result_versions_no_update BEFORE UPDATE ON game_result_versions
BEGIN SELECT RAISE(ABORT,'results evidence is immutable'); END;
CREATE TRIGGER game_result_versions_no_delete BEFORE DELETE ON game_result_versions
BEGIN SELECT RAISE(ABORT,'results evidence is immutable'); END;
CREATE TRIGGER resolution_versions_no_update BEFORE UPDATE ON resolution_versions
BEGIN SELECT RAISE(ABORT,'results evidence is immutable'); END;
CREATE TRIGGER resolution_versions_no_delete BEFORE DELETE ON resolution_versions
BEGIN SELECT RAISE(ABORT,'results evidence is immutable'); END;
CREATE TRIGGER resolution_payouts_no_update BEFORE UPDATE ON resolution_payouts
BEGIN SELECT RAISE(ABORT,'results evidence is immutable'); END;
CREATE TRIGGER resolution_payouts_no_delete BEFORE DELETE ON resolution_payouts
BEGIN SELECT RAISE(ABORT,'results evidence is immutable'); END;
COMMIT;
