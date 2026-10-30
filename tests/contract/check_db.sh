#!/usr/bin/env bash
# Validates contracts/db/schema.sql against a throw-away PostgreSQL container (needs Docker).
# Usage: tests/contract/check_db.sh [image]   (default postgres:18)
# Exit code 0 only if the schema loads and every behavioural check passes.
set -euo pipefail
IMAGE="${1:-postgres:18}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAME="cd-schema-check-$$"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$NAME" -e POSTGRES_PASSWORD=check "$IMAGE" >/dev/null
for _ in $(seq 1 40); do
  docker exec "$NAME" pg_isready -U postgres >/dev/null 2>&1 && break
  sleep 1
done
psqlx() { docker exec -i "$NAME" psql -U postgres -v ON_ERROR_STOP=1 -q "$@"; }
expect_fail() { # description, sql
  if psqlx -c "$2" >/dev/null 2>&1; then echo "FAIL: $1 was accepted"; exit 1; else echo "ok  : $1 rejected"; fi
}

psqlx < "$ROOT/contracts/db/schema.sql"
echo "ok  : schema loads on $IMAGE"

ZERO="sha256:$(printf '0%.0s' $(seq 1 64))"
H1="sha256:$(printf '1%.0s' $(seq 1 64))"
H2="sha256:$(printf '2%.0s' $(seq 1 64))"
psqlx -c "INSERT INTO audit_log (seq, actor, event, detail, prev_hash, hash, created_at) VALUES (1,'detector','incident.opened','{}','$ZERO','$H1', now());"
echo "ok  : first audit row accepted"
psqlx -c "INSERT INTO audit_log (seq, actor, event, detail, prev_hash, hash, created_at) VALUES (2,'api','login.ok','{}','$H1','$H2', now());"
echo "ok  : chained audit row accepted"
expect_fail "audit row with wrong prev_hash" "INSERT INTO audit_log (seq, actor, event, detail, prev_hash, hash, created_at) VALUES (3,'api','bad.chain','{}','$ZERO','sha256:$(printf '3%.0s' $(seq 1 64))', now());"
expect_fail "audit row with skipped seq" "INSERT INTO audit_log (seq, actor, event, detail, prev_hash, hash, created_at) VALUES (9,'api','skip.seq','{}','$H2','sha256:$(printf '4%.0s' $(seq 1 64))', now());"
expect_fail "audit UPDATE" "UPDATE audit_log SET event='tampered.event' WHERE seq=1;"
expect_fail "audit DELETE" "DELETE FROM audit_log WHERE seq=1;"
expect_fail "audit TRUNCATE" "TRUNCATE audit_log;"
expect_fail "audit row with invalid actor" "INSERT INTO audit_log (seq, actor, event, detail, prev_hash, hash, created_at) VALUES (3,'root','x.event','{}','$H2','sha256:$(printf '5%.0s' $(seq 1 64))', now());"

# application role privileges on the audit log
priv=$(psqlx -t -A -c "SELECT string_agg(privilege_type, ',' ORDER BY privilege_type) FROM information_schema.role_table_grants WHERE grantee='cloud_doctor_app' AND table_name='audit_log';")
[ "$priv" = "INSERT,SELECT" ] && echo "ok  : app role holds only INSERT,SELECT on audit_log" || { echo "FAIL: app role privileges on audit_log = $priv"; exit 1; }

# JSONB rejects NUL characters (documents why sanitising before insert is required)
psqlx -c "INSERT INTO services (name,kind,container) VALUES ('redis','cache','cd-redis');" -c "INSERT INTO incidents (incident_id,state,severity,opened_at,services) VALUES ('INC-0001','detected','high',now(),'{redis}');"
expect_fail "evidence payload containing a NUL escape (\\u0000)" "INSERT INTO evidence (incident_id,evidence_id,source,type,service,observed_at,collected_at,query,status,payload,payload_hash,untrusted) VALUES ('INC-0001','EV-001','loki','log','redis',now(),now(),'q','ok','{\"line\":\"a\\u0000b\"}','sha256:$(printf 'a%.0s' $(seq 1 64))',true);"
psqlx -c "INSERT INTO evidence (incident_id,evidence_id,source,type,service,observed_at,collected_at,query,status,payload,payload_hash,untrusted) VALUES ('INC-0001','EV-001','loki','log','redis',now(),now(),'q','ok','{\"line\":\"clean\"}','sha256:$(printf 'a%.0s' $(seq 1 64))',true);"
echo "ok  : sanitised evidence row accepted"
echo "RESULT: PASS"
