package cloud_doctor.policy_test

import rego.v1

import data.cloud_doctor.policy

client := {
	"min_confidence": 0.8,
	"freeze_windows": [{"start": "2026-12-24T00:00:00Z", "end": "2026-12-27T00:00:00Z"}],
	"service_allowlist": {
		"api": ["restart_service", "escalate"],
		"redis": ["restart_service", "escalate"],
	},
}

base := {
	"action": "restart_service",
	"params": {"service": "api"},
	"target": {"service": "api", "kind": "app"},
	"risk_class": "low",
	"confidence": 0.95,
	"counters": {"attempts_used": 0},
	"tenant": "acme",
	"channel": "C0",
	"time": "2026-11-02T09:00:00Z",
}

test_allow_when_no_restriction_fires if {
	policy.decision == {"result": "allow", "rule_ids": ["C-DEFAULT-ALLOW"]} with input as base with data.client as client
}

test_freeze_window_denies if {
	d := policy.decision with input as object.union(base, {"time": "2026-12-25T10:00:00Z"}) with data.client as client
	d.result == "deny"
	"C-FREEZE" in d.rule_ids
}

test_service_not_in_allowlist_denies if {
	inp := object.union(base, {"params": {"service": "worker"}, "target": {"service": "worker", "kind": "queue_worker"}})
	d := policy.decision with input as inp with data.client as client
	d.result == "deny"
	"C-SERVICE-ALLOWLIST" in d.rule_ids
}

test_action_not_allowed_for_service_denies if {
	d := policy.decision with input as object.union(base, {"action": "rollback_service"}) with data.client as client
	d.result == "deny"
}

test_cache_restart_requires_approval if {
	inp := object.union(base, {"params": {"service": "redis"}, "target": {"service": "redis", "kind": "cache"}})
	policy.decision == {"result": "allow_with_approval", "rule_ids": ["C-APPROVE-CACHE"]} with input as inp with data.client as client
}

test_low_confidence_denies if {
	d := policy.decision with input as object.union(base, {"confidence": 0.5}) with data.client as client
	d.result == "deny"
	"C-CONFIDENCE" in d.rule_ids
}

test_stricter_confidence_from_client_data if {
	strict := object.union(client, {"min_confidence": 0.99})
	d := policy.decision with input as base with data.client as strict
	d.result == "deny"
}

test_deny_wins_over_approval if {
	inp := object.union(base, {"params": {"service": "redis"}, "target": {"service": "redis", "kind": "cache"}, "confidence": 0.1})
	d := policy.decision with input as inp with data.client as client
	d.result == "deny"
}

test_malformed_input_denies if {
	d := policy.decision with input as {"action": "restart_service"} with data.client as client
	d.result == "deny"
	"C-INPUT-INVALID" in d.rule_ids
}

test_empty_input_denies if {
	d := policy.decision with input as {} with data.client as client
	d.result == "deny"
}

test_bad_time_denies if {
	d := policy.decision with input as object.union(base, {"time": "not-a-time"}) with data.client as client
	d.result == "deny"
}

test_escalate_is_never_blocked_by_freeze_or_allowlist if {
	inp := {"action": "escalate", "params": {}, "target": {}, "risk_class": "low", "confidence": 0.1, "counters": {}, "tenant": "acme", "channel": "C0", "time": "2026-12-25T10:00:00Z"}
	d := policy.decision with input as inp with data.client as client
	d.result == "allow"
}

test_no_client_data_still_allows_a_clean_input if {
	policy.decision.result == "allow" with input as base with data.client as {}
}
