-- name: list_admin_audit_events :many
-- column: id int
-- column: occurred_at str
-- column: phase str
-- column: action str
-- column: operation str?
-- column: resource str
-- column: object_id str?
-- column: actor_id str?
-- column: error_type str?
SELECT id, occurred_at, phase, action, operation,
       resource, object_id, actor_id, error_type
FROM admin_audit_event
ORDER BY id
