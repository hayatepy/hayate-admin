-- name: count_tasks :one
-- param: search str
-- param: status str
-- column: total int
SELECT count(*) AS total
FROM task
WHERE (?1 = '' OR instr(lower(name), lower(?1)) > 0)
  AND (?2 = '' OR status = ?2)
