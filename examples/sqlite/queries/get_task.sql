-- name: get_task :one?
-- param: id int
-- column: id int
-- column: name str
-- column: status str
-- column: active int
-- column: notes str
SELECT id, name, status, active, notes
FROM task
WHERE id = ?1
