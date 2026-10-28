-- P01 foundation only. Quote, attempt/lease and analysis tables belong to P02–P05.
BEGIN IMMEDIATE;
CREATE TABLE teams (
    team_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE games (
    game_id TEXT PRIMARY KEY CHECK(length(trim(game_id)) > 0),
    season TEXT NOT NULL CHECK(length(trim(season)) > 0),
    away_team_id TEXT NOT NULL REFERENCES teams(team_id),
    home_team_id TEXT NOT NULL REFERENCES teams(team_id),
    status TEXT NOT NULL CHECK(status IN
        ('scheduled','delayed','postponed','live','final','cancelled')),
    last_observed_at TEXT NOT NULL,
    CHECK(away_team_id <> home_team_id)
);
CREATE TABLE source_event_mappings (
    source TEXT NOT NULL CHECK(length(trim(source)) > 0),
    source_event_id TEXT NOT NULL CHECK(length(trim(source_event_id)) > 0),
    game_id TEXT NOT NULL REFERENCES games(game_id),
    observed_at TEXT NOT NULL,
    evidence TEXT NOT NULL CHECK(length(trim(evidence)) > 0),
    PRIMARY KEY(source, source_event_id)
);
CREATE TABLE schedule_revisions (
    revision_id INTEGER PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(game_id),
    revision_number INTEGER NOT NULL CHECK(revision_number >= 1),
    scheduled_start_utc TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    previous_revision_id INTEGER REFERENCES schedule_revisions(revision_id),
    UNIQUE(game_id, revision_number)
);
CREATE TABLE snapshot_slots (
    slot_id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES schedule_revisions(revision_id),
    slot_index INTEGER NOT NULL CHECK(slot_index BETWEEN 0 AND 24),
    planned_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('planned','complete','partial','missed',
        'superseded','cancelled_after_start','cancelled_event')),
    UNIQUE(revision_id, slot_index)
);
CREATE INDEX slots_due ON snapshot_slots(state, planned_at);
CREATE TRIGGER slot_identity_no_update
BEFORE UPDATE OF revision_id,slot_index,planned_at ON snapshot_slots
BEGIN SELECT RAISE(ABORT, 'slot identity is immutable'); END;
CREATE TRIGGER slot_no_delete BEFORE DELETE ON snapshot_slots
BEGIN SELECT RAISE(ABORT, 'slots must be retained'); END;
CREATE TRIGGER game_identity_no_update
BEFORE UPDATE OF game_id,season,away_team_id,home_team_id ON games
BEGIN SELECT RAISE(ABORT, 'game identity is immutable'); END;
CREATE TABLE slot_events (
    event_id INTEGER PRIMARY KEY,
    slot_id INTEGER NOT NULL REFERENCES snapshot_slots(slot_id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE game_events (
    event_id INTEGER PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(game_id),
    status TEXT NOT NULL,
    observed_at TEXT NOT NULL
);
CREATE TRIGGER revision_no_update BEFORE UPDATE ON schedule_revisions
BEGIN SELECT RAISE(ABORT, 'schedule history is immutable'); END;
CREATE TRIGGER revision_no_delete BEFORE DELETE ON schedule_revisions
BEGIN SELECT RAISE(ABORT, 'schedule history is immutable'); END;
CREATE TRIGGER slot_event_no_update BEFORE UPDATE ON slot_events
BEGIN SELECT RAISE(ABORT, 'slot audit is immutable'); END;
CREATE TRIGGER slot_event_no_delete BEFORE DELETE ON slot_events
BEGIN SELECT RAISE(ABORT, 'slot audit is immutable'); END;
CREATE TRIGGER game_event_no_update BEFORE UPDATE ON game_events
BEGIN SELECT RAISE(ABORT, 'game audit is immutable'); END;
CREATE TRIGGER game_event_no_delete BEFORE DELETE ON game_events
BEGIN SELECT RAISE(ABORT, 'game audit is immutable'); END;
CREATE TRIGGER mapping_no_update BEFORE UPDATE ON source_event_mappings
BEGIN SELECT RAISE(ABORT, 'mapping history is immutable'); END;
CREATE TRIGGER mapping_no_delete BEFORE DELETE ON source_event_mappings
BEGIN SELECT RAISE(ABORT, 'mapping history is immutable'); END;
PRAGMA application_id = 1312964944;
PRAGMA user_version = 1;
COMMIT;
