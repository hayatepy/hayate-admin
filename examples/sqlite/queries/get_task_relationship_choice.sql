-- name: get_task_relationship_choice :one?
-- param: tenant_key str
-- param: id int
-- param: exclude_id int?
-- column: id int
-- column: name str
SELECT id, name
FROM task
WHERE tenant_key = ?1
  AND id = ?2
  AND (?3 IS NULL OR id <> ?3)
