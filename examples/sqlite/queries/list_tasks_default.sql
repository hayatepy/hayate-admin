-- name: list_tasks_default :many
-- param: tenant_key str
-- param: search str
-- param: status str
-- param: limit int
-- param: offset int
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
LEFT JOIN task AS parent
  ON parent.id = child.parent_id
 AND parent.tenant_key = child.tenant_key
WHERE child.tenant_key = ?1
  AND (?2 = '' OR instr(lower(child.name), lower(?2)) > 0)
  AND (?3 = '' OR child.status = ?3)
ORDER BY child.id
LIMIT ?4 OFFSET ?5
