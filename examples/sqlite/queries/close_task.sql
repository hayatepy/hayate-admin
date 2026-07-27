-- name: close_task :one?
-- param: tenant_key str
-- param: id int
-- column: id int
UPDATE task
SET status = 'closed'
WHERE tenant_key = ?1
  AND id = ?2
RETURNING id
