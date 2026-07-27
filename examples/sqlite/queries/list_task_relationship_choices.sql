-- name: list_task_relationship_choices :many
-- param: tenant_key str
-- param: search str
-- param: exclude_id int?
-- param: limit int
-- param: offset int
-- column: id int
-- column: name str
SELECT id, name
FROM task
WHERE tenant_key = ?1
  AND (?2 = '' OR instr(lower(name), lower(?2)) > 0)
  AND (?3 IS NULL OR id <> ?3)
ORDER BY name, id
LIMIT ?4 OFFSET ?5
