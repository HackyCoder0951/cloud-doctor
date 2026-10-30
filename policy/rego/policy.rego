# Cloud Doctor Layer 2: example client policy.
#
# Contract with the caller (policy/cd_policy/opa_client.py):
#   POST /v1/data/cloud_doctor/policy/decision  {"input": <minimised input>}
#   -> {"result": {"result": "allow" | "allow_with_approval" | "deny", "rule_ids": [...]}}
#
# These rules can only RESTRICT. Layer 1 (the `invariants` package) is evaluated separately and the
# two results are conjoined in code, so nothing written here can make a Layer 1 denial executable.
# Default is deny; "allow" is produced only for a well-formed input on which no restriction fires.
#
# The input is minimised by the caller: action, params, target, risk_class, confidence, counters,
# tenant, channel, time. It never contains logs, evidence text or LLM text.
#
# NOTE: written for OPA with `rego.v1`; `opa test policy/rego` runs policy_test.rego.
package cloud_doctor.policy

import rego.v1

default decision := {"result": "deny", "rule_ids": ["C-DEFAULT-DENY"]}

# --- client configuration (data.client), all optional ------------------------------------------
default min_confidence := 0.8

min_confidence := data.client.min_confidence

# --- input sanity: anything unexpected is a deny -----------------------------------------------
valid_input if {
	input.action in {"restart_service", "rollback_service", "scale_service", "clear_cache", "isolate_dependency", "escalate"}
	input.risk_class in {"low", "medium", "high"}
	is_number(input.confidence)
	is_string(input.tenant)
	is_string(input.channel)
	is_object(input.counters)
	time.parse_rfc3339_ns(input.time)
	has_target
}

# escalate is non-executing and may carry no target service
has_target if input.action == "escalate"

has_target if is_string(input.target.service)

# The restrictions below never apply to `escalate`: handing the incident to a human must stay possible.
executing if input.action != "escalate"

# --- restrictions ----------------------------------------------------------------------------
deny_ids contains "C-FREEZE" if {
	executing
	some window in data.client.freeze_windows
	start := time.parse_rfc3339_ns(window.start)
	end := time.parse_rfc3339_ns(window.end)
	now := time.parse_rfc3339_ns(input.time)
	now >= start
	now < end
}

deny_ids contains "C-SERVICE-ALLOWLIST" if {
	executing
	allowlist := data.client.service_allowlist
	not allowlist[input.target.service]
}

deny_ids contains "C-SERVICE-ALLOWLIST" if {
	executing
	actions := data.client.service_allowlist[input.target.service]
	not input.action in actions
}

deny_ids contains "C-CONFIDENCE" if {
	executing
	input.confidence < min_confidence
}

deny_ids contains "C-INPUT-INVALID" if not valid_input

approval_ids contains "C-APPROVE-CACHE" if {
	input.action == "restart_service"
	input.target.kind == "cache"
}

# --- decision --------------------------------------------------------------------------------
decision := {"result": "deny", "rule_ids": sort(deny_ids)} if count(deny_ids) > 0

decision := {"result": "allow_with_approval", "rule_ids": sort(approval_ids)} if {
	count(deny_ids) == 0
	count(approval_ids) > 0
}

decision := {"result": "allow", "rule_ids": ["C-DEFAULT-ALLOW"]} if {
	count(deny_ids) == 0
	count(approval_ids) == 0
	valid_input
}
