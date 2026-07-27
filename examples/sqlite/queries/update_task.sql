-- name: update_task :one?
-- param: id int
-- param: name str
-- param: status str
-- param: active bool
-- param: notes str
-- column: id int
-- column: name str
-- column: status str
-- column: active int
-- column: notes str
UPDATE task
SET name = ?2,
    status = ?3,
    active = ?4,
    notes = ?5
WHERE id = ?1
RETURNING id, name, status, active, notes
