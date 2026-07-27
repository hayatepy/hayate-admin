-- name: count_admin_audit_events_for_object :one
-- param: resource str
-- param: object_id str
-- column: total int
SELECT count(*) AS total
FROM admin_audit_event
WHERE resource = ?1
  AND object_id = ?2
