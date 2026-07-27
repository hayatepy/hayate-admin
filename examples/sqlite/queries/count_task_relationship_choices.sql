-- name: count_task_relationship_choices :one
-- param: tenant_key str
-- param: search str
-- param: exclude_id int?
-- column: total int
SELECT count(*) AS total
FROM task
WHERE tenant_key = ?1
  AND (?2 = '' OR instr(lower(name), lower(?2)) > 0)
  AND (?3 IS NULL OR id <> ?3)
