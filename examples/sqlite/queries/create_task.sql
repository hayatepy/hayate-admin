-- name: create_task :one
-- param: name str
-- param: status str
-- param: active bool
-- param: notes str
-- column: id int
-- column: name str
-- column: status str
-- column: active int
-- column: notes str
INSERT INTO task (name, status, active, notes)
VALUES (?1, ?2, ?3, ?4)
RETURNING id, name, status, active, notes
