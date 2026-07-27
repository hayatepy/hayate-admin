-- name: create_task :one?
-- param: tenant_key str
-- param: name str
-- param: status str
-- param: active bool
-- param: notes str
-- param: parent_id int?
-- column: id int
INSERT INTO task (tenant_key, name, status, active, notes, parent_id)
SELECT ?1, ?2, ?3, ?4, ?5, parent.id
FROM (SELECT 1) AS one
LEFT JOIN task AS parent
  ON parent.tenant_key = ?1
 AND parent.id = ?6
WHERE ?6 IS NULL OR parent.id IS NOT NULL
RETURNING id
