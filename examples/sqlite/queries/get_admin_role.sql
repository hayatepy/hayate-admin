-- name: get_admin_role :one?
-- param: user_id str
-- column: role str
SELECT role
FROM admin_role
WHERE user_id = ?1
