-- name: delete_subtask :one?
-- param: tenant_key str
-- param: parent_id int
-- param: id int
-- column: id int
DELETE FROM task
WHERE tenant_key = ?1
  AND parent_id = ?2
  AND id = ?3
RETURNING id
