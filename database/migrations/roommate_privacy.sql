CREATE SCHEMA IF NOT EXISTS civicnest;

CREATE TABLE IF NOT EXISTS civicnest.roommate_connections (
    id BIGSERIAL PRIMARY KEY,
    requester_id INTEGER NOT NULL
        REFERENCES civicnest.users(id) ON DELETE CASCADE,
    receiver_id INTEGER NOT NULL
        REFERENCES civicnest.users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'declined', 'blocked')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (requester_id, receiver_id)
);

ALTER TABLE civicnest.roommate_connections
    ADD COLUMN IF NOT EXISTS requester_met_at TIMESTAMPTZ;

ALTER TABLE civicnest.roommate_connections
    ADD COLUMN IF NOT EXISTS receiver_met_at TIMESTAMPTZ;

ALTER TABLE civicnest.roommate_connections
    ADD COLUMN IF NOT EXISTS released_at TIMESTAMPTZ;

ALTER TABLE civicnest.roommate_connections
    ADD COLUMN IF NOT EXISTS released_by INTEGER
        REFERENCES civicnest.users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS roommate_connections_requester_idx
    ON civicnest.roommate_connections (requester_id, created_at DESC);

CREATE INDEX IF NOT EXISTS roommate_connections_receiver_idx
    ON civicnest.roommate_connections (receiver_id, created_at DESC);
