-- name: update_task :one?
-- param: tenant_key str
-- param: id int
-- param: name str
-- param: status str
-- param: active bool
-- param: notes str
-- param: parent_id int?
-- column: id int
UPDATE task
SET name = ?3,
    status = ?4,
    active = ?5,
    notes = ?6,
    parent_id = ?7
WHERE tenant_key = ?1
  AND id = ?2
  AND (?7 IS NULL OR ?7 <> ?2)
  AND (
    ?7 IS NULL
    OR EXISTS (
      SELECT 1
      FROM task AS parent
      WHERE parent.tenant_key = ?1
        AND parent.id = ?7
    )
  )
RETURNING id
