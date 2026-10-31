# Cloud Doctor developer entry points (root Makefile is owned by Stream A).
.PHONY: up up-no-logs down reset smoke contracts

up:            ## bring the sandbox up (generates infra/.env and infra/generated/*)
	infra/scripts/up.sh

up-no-logs:    ## same without Loki/Promtail
	infra/scripts/up.sh --no-logs

down:          ## stop the sandbox, keep volumes
	infra/scripts/down.sh

reset:         ## stop and delete all sandbox state (clean slate between experiment runs)
	infra/scripts/down.sh --volumes

smoke:         ## check the sandbox against contracts/telemetry.md
	infra/scripts/smoke_test.sh

contracts:     ## validate the frozen contracts
	python3 tests/contract/validate_contracts.py
