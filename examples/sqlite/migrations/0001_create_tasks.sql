CREATE TABLE task (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_key TEXT NOT NULL CHECK (length(tenant_key) BETWEEN 1 AND 120),
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    notes TEXT NOT NULL CHECK (length(notes) <= 2000),
    parent_id INTEGER,
    UNIQUE (tenant_key, id),
    FOREIGN KEY (tenant_key, parent_id)
        REFERENCES task(tenant_key, id)
        ON DELETE RESTRICT,
    CHECK (parent_id IS NULL OR parent_id <> id)
);

CREATE INDEX task_tenant_parent ON task (tenant_key, parent_id, id);

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
    role TEXT NOT NULL CHECK (role IN ('viewer', 'editor', 'operator')),
    tenant_key TEXT NOT NULL CHECK (length(tenant_key) BETWEEN 1 AND 120)
);
