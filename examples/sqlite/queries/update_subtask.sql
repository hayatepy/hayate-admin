-- name: update_subtask :one?
-- param: tenant_key str
-- param: parent_id int
-- param: id int
-- param: name str
-- param: status str
-- param: active bool
-- param: notes str
-- column: id int
UPDATE task
SET name = ?4,
    status = ?5,
    active = ?6,
    notes = ?7
WHERE tenant_key = ?1
  AND parent_id = ?2
  AND id = ?3
RETURNING id
