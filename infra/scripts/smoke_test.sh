#!/usr/bin/env bash
# Verifies the sandbox against contracts/telemetry.md. Prints ok/FAIL per check; exit 0 only if all pass.
# Usage: infra/scripts/smoke_test.sh [--no-logs]
set -uo pipefail
PROM=http://127.0.0.1:9090
LOKI=http://127.0.0.1:3100
fail=0
ok()   { echo "ok  : $*"; }
bad()  { echo "FAIL: $*"; fail=1; }
q()    { curl -s -m 10 -G "$PROM/api/v1/query" --data-urlencode "query=$1" | python3 -c "import sys,json; d=json.load(sys.stdin)['data']['result']; print(d[0]['value'][1] if d else 'NONE')"; }

curl -sf -m 5 http://127.0.0.1:18000/healthz >/dev/null && ok "api /healthz" || bad "api /healthz"
code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:18000/work); [[ "$code" == 200 ]] && ok "api /work returns 200" || bad "api /work returned $code"
code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:18000/readyz); [[ "$code" == 200 ]] && ok "api /readyz returns 200" || bad "api /readyz returned $code"

for s in api worker loadgen redis app-db; do
  v=$(q "up{service=\"$s\",env=\"sandbox\"}"); [[ "$v" == 1 ]] && ok "up{service=$s} = 1" || bad "up{service=$s} = $v"
done
for s in redis app-db; do
  v=$(q "cd_service_up{service=\"$s\"}"); [[ "$v" == 1 ]] && ok "cd_service_up{service=$s} = 1" || bad "cd_service_up{service=$s} = $v"
done
v=$(q 'sum(rate(http_requests_total{service="api",route="/work"}[30s]))'); python3 - "$v" <<'EOF' && ok "api /work traffic about 10 rps (got $v)" || bad "api /work traffic rate $v outside 5..15"
import sys; v=sys.argv[1]; sys.exit(0 if v!="NONE" and 5<=float(v)<=15 else 1)
EOF
v=$(q 'sum(rate(http_requests_total{service="api",status=~"5.."}[30s]))'); [[ "$v" == "0" || "$v" == "NONE" || "$v" == 0* ]] && ok "no 5xx at steady state ($v)" || bad "5xx at steady state: $v"
v=$(q 'queue_depth{service="worker",queue="jobs"}'); python3 - "$v" <<'EOF' && ok "worker queue_depth present and small ($v)" || bad "worker queue_depth = $v"
import sys; v=sys.argv[1]; sys.exit(0 if v!="NONE" and float(v)<50 else 1)
EOF
v=$(q 'cd_queue_length{service="redis",queue="jobs"}'); python3 - "$v" <<'EOF' && ok "probe cd_queue_length present and small ($v)" || bad "probe cd_queue_length = $v"
import sys; v=sys.argv[1]; sys.exit(0 if v!="NONE" and float(v)<50 else 1)
EOF
for m in process_start_time_seconds build_info cd_dependency_up; do
  v=$(q "count($m)"); [[ "$v" != NONE ]] && ok "metric $m present" || bad "metric $m missing"
done

if [[ "${1:-}" != "--no-logs" ]]; then
  sleep 3
  n=$(curl -s -m 10 -G "$LOKI/loki/api/v1/query_range" --data-urlencode 'query={service="api"}' --data-urlencode 'limit=5' | python3 -c "import sys,json; print(sum(len(r['values']) for r in json.load(sys.stdin)['data']['result']))" 2>/dev/null || echo 0)
  [[ "$n" -gt 0 ]] && ok "Loki returns api log lines ($n)" || bad "Loki returned no api log lines (logs path not working)"
fi
echo; [[ $fail == 0 ]] && echo "SMOKE: PASS" || echo "SMOKE: FAIL"; exit $fail
