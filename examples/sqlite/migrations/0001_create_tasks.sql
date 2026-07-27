CREATE TABLE task (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    notes TEXT NOT NULL CHECK (length(notes) <= 2000)
);

CREATE TABLE admin_audit_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('attempt', 'success', 'failure')),
    action TEXT NOT NULL,
    operation TEXT,
    resource TEXT NOT NULL,
    object_id TEXT,
    actor_id TEXT,
    error_type TEXT
);

CREATE TABLE admin_role (
    user_id TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('viewer', 'editor', 'operator'))
);
