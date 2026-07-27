-- name: close_task :one?
-- param: id int
-- column: id int
UPDATE task
SET status = 'closed'
WHERE id = ?1
RETURNING id
