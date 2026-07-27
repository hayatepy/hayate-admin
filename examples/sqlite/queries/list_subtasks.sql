-- name: list_subtasks :many
-- param: tenant_key str
-- param: parent_id int
-- param: limit int
-- column: id int
-- column: name str
-- column: status str
-- column: active int
-- column: notes str
-- column: parent_id int?
-- column: parent_name str?
SELECT child.id, child.name, child.status, child.active, child.notes,
       child.parent_id, parent.name AS parent_name
FROM task AS child
JOIN task AS parent
  ON parent.id = child.parent_id
 AND parent.tenant_key = child.tenant_key
WHERE child.tenant_key = ?1
  AND child.parent_id = ?2
ORDER BY child.id
LIMIT ?3
