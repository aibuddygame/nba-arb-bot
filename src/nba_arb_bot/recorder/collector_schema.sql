BEGIN IMMEDIATE;
CREATE TABLE collector_component(version INTEGER NOT NULL CHECK(version=1));
INSERT INTO collector_component VALUES(1);
CREATE TABLE collector_policies(policy_id TEXT PRIMARY KEY,body_json TEXT NOT NULL);
CREATE TABLE collector_slots (
    slot_id INTEGER PRIMARY KEY REFERENCES snapshot_slots(slot_id),
    policy_id TEXT NOT NULL REFERENCES collector_policies(policy_id),
    bookmaker_event_id TEXT NOT NULL,
    binding_id TEXT NOT NULL REFERENCES polymarket_bindings(binding_id),
    expected_books_json TEXT NOT NULL,
    registered_at TEXT NOT NULL
);
CREATE TABLE collector_jobs (
    job_id INTEGER PRIMARY KEY,
    slot_id INTEGER NOT NULL REFERENCES collector_slots(slot_id),
    source TEXT NOT NULL CHECK(source IN ('bookmaker','polymarket')),
    state TEXT NOT NULL CHECK(state IN ('pending','running','succeeded','exhausted','cancelled')),
    next_at TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    active_attempt_id INTEGER,
    lease_until TEXT,
    UNIQUE(slot_id,source)
);
CREATE INDEX collector_due ON collector_jobs(state,next_at);
CREATE TABLE collector_attempts (
    attempt_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES collector_jobs(job_id),
    retry_number INTEGER NOT NULL,
    worker_id TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    lease_until TEXT NOT NULL,
    capture_id TEXT NOT NULL UNIQUE,
    game_observed_at TEXT NOT NULL,
    UNIQUE(job_id,retry_number)
);
CREATE TABLE collector_quota (
    attempt_id INTEGER PRIMARY KEY REFERENCES collector_attempts(attempt_id),
    policy_id TEXT NOT NULL REFERENCES collector_policies(policy_id),
    source TEXT NOT NULL,
    units INTEGER NOT NULL CHECK(units=1),
    reserved_at TEXT NOT NULL
);
CREATE TABLE collector_attempt_results (
    attempt_id INTEGER PRIMARY KEY REFERENCES collector_attempts(attempt_id),
    status TEXT NOT NULL,
    capture_id TEXT,
    request_started_at TEXT,
    request_finished_at TEXT,
    received_at TEXT,
    body_sha256 TEXT,
    error_code TEXT,
    recorded_at TEXT NOT NULL,
    game_observed_at TEXT
);
CREATE TABLE collector_job_events (
    event_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES collector_jobs(job_id),
    state TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE collector_pairs (
    slot_id INTEGER NOT NULL REFERENCES collector_slots(slot_id),
    policy_id TEXT NOT NULL REFERENCES collector_policies(policy_id),
    pairing_version TEXT NOT NULL,
    book_id TEXT NOT NULL,
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    bookmaker_capture_id TEXT,
    polymarket_capture_id TEXT,
    binding_id TEXT NOT NULL REFERENCES polymarket_bindings(binding_id),
    receipt_gap_seconds TEXT,
    research_eligible INTEGER NOT NULL CHECK(research_eligible IN (0,1)),
    cost_metadata_complete INTEGER NOT NULL CHECK(cost_metadata_complete IN (0,1)),
    flags_json TEXT NOT NULL,
    finalized_at TEXT NOT NULL,
    PRIMARY KEY(slot_id,book_id,team_id),
    FOREIGN KEY(bookmaker_capture_id,slot_id,book_id,team_id)
      REFERENCES bookmaker_quotes(capture_id,slot_id,book_id,team_id),
    FOREIGN KEY(polymarket_capture_id,binding_id,team_id)
      REFERENCES polymarket_quotes(capture_id,binding_id,team_id)
);
CREATE TRIGGER collector_policies_no_update BEFORE UPDATE ON collector_policies
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_policies_no_delete BEFORE DELETE ON collector_policies
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_slots_no_update BEFORE UPDATE ON collector_slots
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_slots_no_delete BEFORE DELETE ON collector_slots
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_attempts_no_update BEFORE UPDATE ON collector_attempts
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_attempts_no_delete BEFORE DELETE ON collector_attempts
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_quota_no_update BEFORE UPDATE ON collector_quota
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_quota_no_delete BEFORE DELETE ON collector_quota
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_attempt_results_no_update BEFORE UPDATE ON collector_attempt_results
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_attempt_results_no_delete BEFORE DELETE ON collector_attempt_results
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_job_events_no_update BEFORE UPDATE ON collector_job_events
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_job_events_no_delete BEFORE DELETE ON collector_job_events
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_pairs_no_update BEFORE UPDATE ON collector_pairs
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
CREATE TRIGGER collector_pairs_no_delete BEFORE DELETE ON collector_pairs
BEGIN SELECT RAISE(ABORT,'collector evidence is immutable'); END;
COMMIT;
