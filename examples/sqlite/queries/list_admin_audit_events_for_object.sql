-- name: list_admin_audit_events_for_object :many
-- param: resource str
-- param: object_id str
-- param: limit int
-- param: offset int
-- column: occurred_at str
-- column: phase str
-- column: action str
-- column: operation str?
-- column: resource str
-- column: object_id str?
-- column: actor_id str?
-- column: error_type str?
SELECT occurred_at, phase, action, operation,
       resource, object_id, actor_id, error_type
FROM admin_audit_event
WHERE resource = ?1
  AND object_id = ?2
ORDER BY id DESC
LIMIT ?3 OFFSET ?4
