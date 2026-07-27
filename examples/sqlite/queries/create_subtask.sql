-- name: create_subtask :one?
-- param: tenant_key str
-- param: parent_id int
-- param: name str
-- param: status str
-- param: active bool
-- param: notes str
-- column: id int
INSERT INTO task (tenant_key, name, status, active, notes, parent_id)
SELECT ?1, ?3, ?4, ?5, ?6, parent.id
FROM task AS parent
WHERE parent.tenant_key = ?1
  AND parent.id = ?2
RETURNING id
