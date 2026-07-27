-- name: list_tasks_default :many
-- param: search str
-- param: status str
-- param: limit int
-- param: offset int
-- column: id int
-- column: name str
-- column: status str
-- column: active int
-- column: notes str
SELECT id, name, status, active, notes
FROM task
WHERE (?1 = '' OR instr(lower(name), lower(?1)) > 0)
  AND (?2 = '' OR status = ?2)
ORDER BY id
LIMIT ?3 OFFSET ?4
