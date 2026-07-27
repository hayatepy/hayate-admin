-- name: upsert_admin_role :exec
-- param: user_id str
-- param: role str
INSERT INTO admin_role (user_id, role)
VALUES (?1, ?2)
ON CONFLICT (user_id) DO UPDATE SET role = excluded.role
