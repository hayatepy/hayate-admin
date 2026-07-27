-- name: upsert_admin_role :exec
-- param: user_id str
-- param: role str
-- param: tenant_key str
INSERT INTO admin_role (user_id, role, tenant_key)
VALUES (?1, ?2, ?3)
ON CONFLICT (user_id) DO UPDATE SET
    role = excluded.role,
    tenant_key = excluded.tenant_key
