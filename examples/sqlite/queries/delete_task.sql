-- name: delete_task :one?
-- param: id int
-- column: id int
DELETE FROM task
WHERE id = ?1
RETURNING id
