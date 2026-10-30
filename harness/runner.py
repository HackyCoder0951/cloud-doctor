"""Run protocol: baseline -> control -> inject -> observe -> abort conditions -> teardown/reset.

Ground truth (fault, timestamps, expected cause) is written only to the run store and the experiment_runs sink.
The API client is only ever called with identifiers and query parameters.
"""
from __future__ import annotations

import enum
import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from harness.api_client import ApiError, CloudDoctorApi
from harness.clock import Clock, iso
from harness.faults import CONTAINER_FAULTS, FaultNotSupported, FaultSpec
from harness.injector import InjectionRecord, Injector, InjectorError, PersistentFaultWatcher
from harness.metadata import MetadataCollector
from harness.records import (EXECUTED_RESULTS, TERMINAL_STATES, derive_timestamps, load_run, steady_satisfied,
                             steady_violated)
from harness.scenario import Scenario
from harness.store import dumps

# Neutral on purpose: the system under test must not learn that the approval comes from a harness (recorded locally).
APPROVAL_REASON = "approved after review"
API_ERROR_LIMIT = 5


class Phase(enum.Enum):
    BASELINE = "baseline"
    CONTROL = "control"
    INJECT = "inject"
    OBSERVE = "observe"
    ABORT = "abort"
    TEARDOWN = "teardown"
    DONE = "done"


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str  # completed | aborted
    abort_reason: str | None
    kind: str


class _Abort(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason, self.detail = reason, detail


class Runner:
    def __init__(self, *, api: CloudDoctorApi, injector: Injector, store: Any, clock: Clock,
                 collector: MetadataCollector, sink: Any = None) -> None:
        self.api, self.injector, self.store, self.clock, self.collector, self.sink = api, injector, store, clock, collector, sink

    # ------------------------------------------------------------------ public
    def run(self, scenario: Scenario, *, kind: str = "experimental", seed: int = 0, repeat_index: int = 1,
            variant: dict[str, str] | None = None, allow_draft: bool = False, auto_approve: bool = False) -> RunSummary:
        if kind not in ("experimental", "control"):
            raise ValueError("kind must be experimental or control")
        if scenario.is_draft and not allow_draft:
            raise FaultNotSupported(f"{scenario.id} is a draft; pass allow_draft to run it")
        variant = variant or {"llm": "off", "log_noise": "off"}
        started = self.clock.now()
        run_id = f"{scenario.id}-{'x' if kind == 'experimental' else 'c'}-{started.strftime('%Y%m%dT%H%M%SZ')}-s{seed}-n{repeat_index}"
        w = self.store.open(run_id)
        st = _State(scenario, kind, random.Random(seed), auto_approve)
        meta = {"run_id": run_id, "scenario_id": scenario.id, "kind": kind, "seed": seed, "repeat_index": repeat_index,
                "variant": variant, "started_at": iso(started), "scenario": scenario.raw, **self.collector.collect()}
        w.metadata(meta)
        if self.sink:
            self.sink.upsert({"run_id": run_id, "scenario_id": scenario.id, "metadata": meta, "injected_at": None, "ground_truth": None})
        self._gt(w, "run_start", kind=kind)
        status, reason = "completed", None
        try:
            self._phase_baseline(w, st)
            if kind == "control":
                self._phase_control(w, st)
            else:
                self._phase_inject(w, st)
                self._phase_observe(w, st)
        except _Abort as a:
            status, reason = "aborted", a.reason
            self._phase(w, Phase.ABORT)
            self._gt(w, "abort", reason=a.reason, detail=a.detail)
        except FaultNotSupported as e:
            status, reason = "aborted", "harness_error"
            self._gt(w, "abort", reason="harness_error", detail=f"fault not supported: {e}")
        except InjectorError as e:
            status, reason = "aborted", "harness_error"
            self._gt(w, "abort", reason="harness_error", detail=f"injector: {e}")
        finally:
            self._teardown(w, st)
            ended = self.clock.now()
            self._gt(w, "run_end", status=status, abort_reason=reason, ended_at=iso(ended))
            self._phase(w, Phase.DONE)
            w.close()
        rec = load_run(w.directory)
        ts = derive_timestamps(rec)
        with open(w.directory / "ground_truth.ndjson", "a", encoding="utf-8") as f:
            f.write(dumps({"event": "timestamps", "t": iso(self.clock.now()), **ts}) + "\n")
        if self.sink:
            self.sink.upsert({"run_id": run_id, "scenario_id": scenario.id, "metadata": {**meta, "ended_at": iso(ended)},
                              "injected_at": ts["t_inject"], "ground_truth": {"timestamps": ts, "status": status,
                                                                             "abort_reason": reason,
                                                                             "expected_cause_class": scenario.cause_class}})
        return RunSummary(run_id, status, reason, kind)

    # ------------------------------------------------------------------ recording helpers
    def _gt(self, w, event: str, **fields: Any) -> None:
        w.ground_truth({"event": event, "t": iso(self.clock.now()), **fields})

    def _phase(self, w, phase: Phase) -> None:
        self._gt(w, "phase", phase=phase.value)

    def _call(self, w, st: "_State", endpoint: str, fn, *args):
        """API call that records failures; too many consecutive failures abort the run."""
        try:
            out = fn(*args)
            st.api_failures = 0
            return out
        except ApiError as e:
            st.api_failures += 1
            w.api({"kind": "api_error", "t": iso(self.clock.now()), "endpoint": endpoint, "status": e.status})
            if st.api_failures >= API_ERROR_LIMIT:
                raise _Abort("harness_error", f"{API_ERROR_LIMIT} consecutive API failures") from None
            return None

    # ------------------------------------------------------------------ phases
    def _phase_baseline(self, w, st: "_State") -> None:
        sc = st.scenario
        self._phase(w, Phase.BASELINE)
        tm = sc.timing
        deadline = self.clock.now() + timedelta(seconds=tm["baseline_timeout_seconds"])
        steady_since = None
        existing = self._call(w, st, "incidents", self.api.list_incidents)
        if existing is None:
            existing = []
        st.preexisting = {i["incident_id"] for i in existing}
        w.api({"kind": "preexisting_incidents", "t": iso(self.clock.now()), "ids": sorted(st.preexisting)})
        while True:
            sample = self._sample(w, st)
            ok = bool(sample) and steady_satisfied(sample, sc.raw["steady_state"]) and \
                not any(s.get("open_incident_ids") for s in sample.values())
            now = self.clock.now()
            steady_since = (steady_since or now) if ok else None
            if steady_since and (now - steady_since).total_seconds() >= tm["baseline_seconds"]:
                self._gt(w, "baseline_ok", steady_since=iso(steady_since))
                return
            if now >= deadline:
                raise _Abort("steady_state_not_reached")
            self.clock.sleep(tm["poll_seconds"])

    def _phase_inject(self, w, st: "_State") -> None:
        sc = st.scenario
        self._phase(w, Phase.INJECT)
        jitter = sc.timing.get("inject_jitter_seconds", 0)
        if jitter:
            self.clock.sleep(st.rng.uniform(0, jitter))
        decoy = sc.decoy
        if decoy:
            fault, lead = decoy
            rec = self._apply(w, st, fault, "decoy_injected")
            st.decoy_fault = fault
            self.clock.sleep(lead)
        fault = sc.fault
        st.fault = fault
        self._gt(w, "inject_start")
        rec = self._apply(w, st, fault, "inject")
        if fault.persistent:
            st.watcher = PersistentFaultWatcher(self.injector, fault)
        st.t_inject = self.clock.now()

    def _apply(self, w, st, fault: FaultSpec, event: str) -> InjectionRecord:
        rec = self.injector.apply(fault)
        self._gt(w, event, fault=fault.to_dict(), commands=[list(c) for c in rec.commands], http=[list(h) for h in rec.http])
        return rec

    def _phase_control(self, w, st: "_State") -> None:
        sc = st.scenario
        self._phase(w, Phase.CONTROL)
        start = self.clock.now()
        end = start + timedelta(seconds=sc.timing["max_duration_seconds"])
        while self.clock.now() < end:
            self.clock.sleep(sc.timing["poll_seconds"])
            self._tick(w, st)
            self._check_abort(w, st)
        self._gt(w, "observe_window", seconds=(self.clock.now() - start).total_seconds())

    def _phase_observe(self, w, st: "_State") -> None:
        sc = st.scenario
        self._phase(w, Phase.OBSERVE)
        tm = sc.timing
        start = self.clock.now()
        cap = start + timedelta(seconds=tm["max_duration_seconds"])
        miss_at = start + timedelta(seconds=tm["detection_deadline_seconds"])
        settled_since = None
        try:
            while True:
                self.clock.sleep(tm["poll_seconds"])
                now = self.clock.now()
                if st.watcher:
                    rec = st.watcher.step()
                    if rec:
                        self._gt(w, "fault_reapplied", count=st.watcher.reapplications,
                                 commands=[list(c) for c in rec.commands])
                self._tick(w, st)
                self._check_abort(w, st)
                terminal = bool(st.views) and all(v["incident"]["state"] in TERMINAL_STATES for v in st.views.values())
                settled_since = (settled_since or now) if terminal else None
                if settled_since and (now - settled_since).total_seconds() >= tm["settle_seconds"]:
                    return
                if not st.views and now >= miss_at:
                    self._gt(w, "detection_missed")
                    return
                if now >= cap:
                    raise _Abort("duration_cap")
        finally:
            self._gt(w, "observe_window", seconds=(self.clock.now() - start).total_seconds())

    # ------------------------------------------------------------------ polling
    def _sample(self, w, st: "_State") -> dict[str, dict] | None:
        services = self._call(w, st, "services", self.api.list_services)
        if services is None:
            return None
        flat = {s["name"]: {"state": s.get("state"), "missing_signal_state": s.get("missing_signal_state"),
                            "open_incident_ids": s.get("open_incident_ids", []), **s.get("slis", {})} for s in services}
        w.api({"kind": "sample", "t": iso(self.clock.now()), "services": flat})
        st.last_sample = flat
        return flat

    def _tick(self, w, st: "_State") -> None:
        self._sample(w, st)
        listed = self._call(w, st, "incidents", self.api.list_incidents)
        for inc in listed or []:
            iid = inc["incident_id"]
            if iid in st.preexisting:
                continue
            snap = self._snapshot(w, st, iid, inc)
            if snap is None:
                continue
            key = dumps(snap)
            if st.seen.get(iid) != key:
                st.seen[iid] = key
                w.api({"kind": "incident_snapshot", "t": iso(self.clock.now()), "incident_id": iid, "data": snap})
            st.views[iid] = snap
            if st.auto_approve:
                self._maybe_approve(w, st, iid, snap)
        audit = self._call(w, st, "audit", self.api.list_audit, None, 0, 500)
        if audit is not None:
            key = dumps(audit)
            if st.audit_key != key:
                st.audit_key = key
                w.api({"kind": "audit", "t": iso(self.clock.now()), "chain_valid": audit.get("chain_valid"),
                       "events": audit.get("events", [])})

    def _snapshot(self, w, st, iid: str, inc: dict) -> dict | None:
        a = self.api
        incident = self._call(w, st, "incident", a.get_incident, iid) or inc
        snap: dict[str, Any] = {"incident": incident}
        t = self._call(w, st, "timeline", a.get_timeline, iid)
        ev = self._call(w, st, "evidence", a.get_evidence, iid)
        snap["timeline"] = t if t is not None else []
        snap["evidence_ids"] = [e["evidence_id"] for e in ev] if ev else []
        snap["diagnosis"] = self._call(w, st, "diagnosis", a.get_diagnosis, iid)
        snap["remediation"] = self._call(w, st, "remediation", a.get_remediation, iid) or {}
        snap["verification"] = self._call(w, st, "verification", a.get_verification, iid) or []
        if incident.get("state") in TERMINAL_STATES:
            snap["report"] = self._call(w, st, "report", a.get_report, iid)
        return snap

    def _maybe_approve(self, w, st, iid: str, snap: dict) -> None:
        sc = st.scenario
        rem = snap.get("remediation") or {}
        accepted = {(a["action_id"], a["service"]) for a in sc.raw["accepted_remediation"]["actions"]}
        for d in rem.get("decisions", []):
            pid = d.get("plan_id")
            if d.get("final") != "allow_with_approval" or pid in st.approved:
                continue
            plan = next((p for p in rem.get("plans", []) if p["plan_id"] == pid), None)
            if plan and (plan["action_id"], plan["params"].get("service")) in accepted:
                st.approved.add(pid)
                self._call(w, st, "approve", self.api.approve_plan, iid, pid, plan["plan_hash"], APPROVAL_REASON)
                self._gt(w, "operator_approval", incident_id=iid, plan_id=pid)

    # ------------------------------------------------------------------ abort conditions
    def _check_abort(self, w, st: "_State") -> None:
        sc = st.scenario
        ab = sc.abort
        sample = st.last_sample or {}
        bad = {n for n, s in sample.items() if s.get("state") in ("DEGRADED", "UNHEALTHY")}
        bad |= set(steady_violated(sample, sc.raw["steady_state"]))
        if len(bad) > ab["max_unhealthy_services"]:
            raise _Abort("blast_radius_exceeded", f"{len(bad)} services unhealthy")
        executed, targets = 0, set()
        for v in st.views.values():
            rem = v.get("remediation") or {}
            plans = {p["plan_id"]: p for p in rem.get("plans", [])}
            for e in rem.get("executions", []):
                if e.get("result") in EXECUTED_RESULTS:
                    executed += 1
                    p = plans.get(e["plan_id"], {}).get("params", {})
                    targets |= {x for x in (p.get("service"), p.get("dependency")) if x}
        if executed > ab["max_executions"]:
            raise _Abort("max_executions_exceeded", f"{executed} executions")
        if len(targets) > ab["max_action_services"]:
            raise _Abort("action_blast_radius_exceeded", f"{len(targets)} services targeted")

    # ------------------------------------------------------------------ teardown
    def _teardown(self, w, st: "_State") -> None:
        self._phase(w, Phase.TEARDOWN)
        st.watcher = None  # stop re-applying before reverting
        for fault in (st.fault, st.decoy_fault):
            if fault is None:
                continue
            try:
                self.injector.revert(fault)
                self._gt(w, "revert", fault=fault.to_dict())
            except Exception as e:  # teardown must try every fault; failures are recorded, not hidden
                self._gt(w, "teardown_error", fault=fault.to_dict(), error=type(e).__name__)


class _State:
    def __init__(self, scenario: Scenario, kind: str, rng: random.Random, auto_approve: bool) -> None:
        self.scenario, self.kind, self.rng, self.auto_approve = scenario, kind, rng, auto_approve
        self.preexisting: set[str] = set()
        self.views: dict[str, dict] = {}
        self.seen: dict[str, str] = {}
        self.approved: set[str] = set()
        self.audit_key: str | None = None
        self.last_sample: dict[str, dict] | None = None
        self.api_failures = 0
        self.fault: FaultSpec | None = None
        self.decoy_fault: FaultSpec | None = None
        self.watcher: PersistentFaultWatcher | None = None
        self.t_inject = None
