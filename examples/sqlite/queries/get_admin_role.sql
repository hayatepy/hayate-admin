-- name: get_admin_role :one?
-- param: user_id str
-- column: role str
-- column: tenant_key str
SELECT role, tenant_key
FROM admin_role
WHERE user_id = ?1
