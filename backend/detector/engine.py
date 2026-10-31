"""Deterministic detector: polls a PromClient, applies the rules in detector.yaml with consecutive-poll hysteresis.

Signals per rule per poll are tri-state: True (breach), False (clear) or None (hold: cannot be established, e.g.
collection failed, low traffic, missing data). Hold never enters or leaves an alert, so missing data cannot make an
alert resolve (keep_firing_for semantics) and failed collection never reads as 'healthy'.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime

from backend.domain.catalog import Catalog
from backend.domain.clock import iso
from backend.domain.models import Alert
from backend.telemetry.base import PromClient, PromResult

from .config import DetectorConfig, RuleConfig
from .expected import ExpectedStateRegistry

SEVERITY_ORDER = {"HEALTHY": 0, "UNKNOWN": 1, "DEGRADED": 2, "UNHEALTHY": 3}


@dataclass
class ServiceStatus:
    name: str
    kind: str
    state: str = "UNKNOWN"
    missing_signal_state: str = "none"
    slis: dict = field(default_factory=dict)
    updated_at: datetime | None = None
    firing: list[str] = field(default_factory=list)


@dataclass
class BackgroundEvent:
    """Observation that is not (part of) an incident: kept so it can appear in a later timeline."""
    event_time: datetime
    collected_at: datetime
    kind: str  # timeline kind
    service: str | None
    summary: str
    suppressed: bool = True
    key: str = ""


@dataclass
class PollResult:
    at: datetime
    alerts: list[Alert]  # state changes this poll (firing / resolved), in order
    background: list[BackgroundEvent]
    prometheus_ok: bool
    statuses: dict[str, ServiceStatus]


@dataclass
class _RuleState:
    state: str = "inactive"  # inactive | pending | firing
    breach: int = 0
    clear: int = 0
    observed_at: datetime | None = None
    fired_at: datetime | None = None
    suppressed: bool = False
    suppress_reason: str | None = None


class Detector:
    def __init__(self, prom: PromClient, catalog: Catalog, cfg: DetectorConfig | None = None,
                 registry: ExpectedStateRegistry | None = None) -> None:
        self.prom, self.catalog = prom, catalog
        self.cfg = cfg or DetectorConfig.load()
        self.registry = registry or ExpectedStateRegistry()
        self._rs: dict[tuple[str, str, str], _RuleState] = {}
        self._hist: dict[tuple[str, str], deque] = {}
        self._last_start: dict[str, float] = {}
        self.statuses: dict[str, ServiceStatus] = {n: ServiceStatus(n, catalog.kind(n)) for n in catalog.names()}
        self._expected_noted: set[tuple[str, str]] = set()
        self.prometheus_ok: bool | None = None

    # ---------------------------------------------------------------- queries
    def _q(self, metric: str, svc: str, now: datetime, dep: str = "") -> PromResult:
        return self.prom.query(self.cfg.query(metric, svc, dep), now)

    @staticmethod
    def _val(res: PromResult) -> float | None:
        if res.failed or not res.series:
            return None
        vals = [s.points[-1][1] for s in res.series if s.points]
        return min(vals) if vals else None

    # ---------------------------------------------------------------- hysteresis
    def _step(self, key: tuple[str, str, str], rule: RuleConfig, signal: bool | None, now: datetime, observed: datetime | None,
              suppressed: bool = False, reason: str | None = None) -> str | None:
        st = self._rs.setdefault(key, _RuleState())
        if signal is None:
            return None
        if signal:
            st.breach, st.clear = st.breach + 1, 0
            if st.state == "inactive":
                st.state, st.observed_at = "pending", observed or now
            lapsed = st.state == "firing" and st.suppressed and not suppressed  # declaration expired while still faulty
            st.suppressed, st.suppress_reason = suppressed, reason
            if lapsed:
                st.fired_at = now
                return "firing"
            if st.breach >= rule.enter_after and st.state != "firing":
                st.state, st.fired_at = "firing", now
                return "firing"
            return None
        st.clear, st.breach = st.clear + 1, 0
        if st.state == "pending":
            st.state = "inactive"
        elif st.state == "firing" and st.clear >= rule.leave_after:
            st.state = "inactive"
            return "resolved"
        return None

    def _alert(self, key, rule: RuleConfig, state: str, now: datetime, summary: str, value: float | None) -> Alert:
        st = self._rs[key]
        svc, name, qual = key
        return Alert(fingerprint=f"{svc}/{name}" + (f"/{qual}" if qual else ""), service=svc, rule=name, state=state, layer=rule.layer,
                     severity=rule.severity, observed_at=st.observed_at or now, fired_at=st.fired_at or now,
                     resolved_at=now if state == "resolved" else None, summary=summary[:300], value=value,
                     suppressed=st.suppressed, suppress_reason=st.suppress_reason)

    # ---------------------------------------------------------------- poll
    def poll(self, now: datetime) -> PollResult:
        out: list[Alert] = []
        bg: list[BackgroundEvent] = []
        any_ok = False
        for svc in self.catalog.names():
            kind = self.catalog.kind(svc)
            stat = self.statuses[svc]
            failed_q = False
            slis: dict = {}
            decl = self.registry.active(svc, now) or self.registry.active_for_dependency(self.catalog.dependencies(svc), now)

            def fire(rule_name: str, signal: bool | None, summary: str, value: float | None = None, qual: str = "",
                     observed: datetime | None = None, suppressed: bool = False, reason: str | None = None) -> None:
                rule = self.cfg.rules[rule_name]
                key = (svc, rule_name, qual)
                tr = self._step(key, rule, signal, now, observed, suppressed, reason)
                if tr:
                    out.append(self._alert(key, rule, tr, now, summary, value))

            def applies(rule_name: str) -> bool:
                return kind in self.cfg.rules[rule_name].kinds

            # --- liveness
            up, cdu = self._q("up", svc, now), self._q("cd_service_up", svc, now)
            probe_backed = kind in ("cache", "database")  # up{} is the probe sidecar: cd_service_up is authoritative
            gap_res = self._q("absent_cd_service_up" if probe_backed else "absent_up", svc, now)
            if up.failed or cdu.failed or gap_res.failed:
                failed_q = True
            else:
                any_ok = True
            if applies("service_down"):
                uv, cv = self._val(up), self._val(cdu)
                if up.failed or cdu.failed:
                    sig = None
                elif (uv is not None and uv == 0) or (cv is not None and cv == 0):
                    sig = True
                elif (cv is not None) if probe_backed else (uv is not None):
                    sig = False
                else:
                    sig = None  # no series at all: the telemetry_gap rule owns this case
                reason = f"expected down: {decl.reason} (owner {decl.owner})" if decl and decl.service == svc else None
                fire("service_down", sig, f"{svc} is down (up/cd_service_up == 0)", 0.0 if sig else 1.0,
                     suppressed=bool(reason), reason=reason)
                slis["availability"] = 0.0 if sig else (1.0 if sig is False else None)
            gap_sig: bool | None = None if gap_res.failed else bool(gap_res.series)
            if applies("telemetry_gap"):
                greason = f"expected absent: {decl.reason} (owner {decl.owner})" if decl and decl.service == svc else None
                fire("telemetry_gap", gap_sig, f"no telemetry series for {svc} (absent)", 1.0 if gap_sig else 0.0,
                     suppressed=bool(greason), reason=greason)

            # --- app SLIs
            if kind == "app":
                rate, err, lat = self._q("request_rate", svc, now), self._q("error_ratio", svc, now), self._q("latency_p95", svc, now)
                failed_q |= rate.failed or err.failed or lat.failed
                rv, ev, lv = self._val(rate), self._val(err), self._val(lat)
                if rv is not None:
                    slis["throughput_rps"] = rv
                traffic_ok = rv is not None and rv >= self.cfg.low_traffic_floor_rps
                if ev is not None and traffic_ok:
                    slis["error_ratio"] = min(max(ev, 0.0), 1.0)
                if lv is not None and traffic_ok:
                    slis["latency_p95_seconds"] = lv
                r = self.cfg.rules["error_ratio"]
                esig = None if (ev is None or not traffic_ok) else ev >= r.params["threshold"]  # minimum-traffic guard: hold
                if not traffic_ok and rv is not None and ev is not None and ev >= r.params["threshold"]:
                    bg.append(BackgroundEvent(now, now, "note", svc, f"error ratio {ev:.2f} ignored: traffic {rv:.2f} rps below floor "
                                              f"{self.cfg.low_traffic_floor_rps} rps", True, f"lowtraffic/{svc}/{iso(now)[:16]}"))
                fire("error_ratio", esig, f"{svc} 5xx ratio {ev:.2f} at {rv:.1f} rps" if ev is not None and rv is not None else "", ev)
                lr = self.cfg.rules["latency_p95"]
                limit = self.catalog.get(svc).slo_latency_p95 or lr.params["threshold_seconds"]
                fire("latency_p95", None if (lv is None or not traffic_ok) else lv >= limit, f"{svc} p95 latency {lv:.2f}s >= {limit}s" if lv else "", lv)

            # --- queue / worker
            if kind == "queue_worker":
                qd, qabs = self._q("queue_depth", svc, now), self._q("absent_queue_depth", svc, now)
                failed_q |= qd.failed or qabs.failed
                qv = self._val(qd)
                if qv is not None:
                    slis["queue_depth"] = qv
                    h = self._hist.setdefault((svc, "queue"), deque(maxlen=self.cfg.rules["queue_growth"].params["growth_window_polls"] + 1))
                    h.append(qv)
                p = self.cfg.rules["queue_growth"].params
                h = self._hist.get((svc, "queue"), deque())
                if qd.failed:
                    gsig = None
                elif qv is None:
                    gsig = None
                elif qv < p["min_depth"]:
                    gsig = False
                elif len(h) <= p["growth_window_polls"]:
                    gsig = None
                else:
                    seq = list(h)
                    gsig = qv - seq[0] >= p["min_growth"] and all(b >= a for a, b in zip(seq, seq[1:]))
                fire("queue_growth", gsig, f"{svc} queue depth {qv} growing", qv)
                fire("queue_absent", None if qabs.failed else bool(qabs.series), f"{svc} queue_depth series absent (redis unreachable?)", 1.0)

            # --- dependencies as seen by the service itself
            if applies("dependency_down"):
                for dep in self.catalog.dependencies(svc):
                    dres = self._q("dependency_up", svc, now, dep)
                    failed_q |= dres.failed
                    dv = self._val(dres)
                    fire("dependency_down", None if dv is None else dv == 0, f"{svc} cannot reach {dep}", dv, qual=dep)

            # --- restarts
            if applies("restart"):
                st = self._q("start_time", svc, now)
                failed_q |= st.failed
                sv = self._val(st)
                rsig: bool | None = None
                observed = None
                if sv is not None:
                    last = self._last_start.get(svc)
                    rsig = last is not None and sv > last + 1
                    if rsig:
                        observed = datetime.fromtimestamp(sv, now.tzinfo)
                    self._last_start[svc] = sv if last is None else max(sv, last)
                fire("restart", rsig, f"{svc} restarted (process_start_time_seconds changed)", sv, observed=observed)

            # --- memory trend (optional signal)
            if applies("memory_growth"):
                mr = self._q("memory_bytes", svc, now)
                failed_q |= mr.failed
                mv = self._val(mr)
                p = self.cfg.rules["memory_growth"].params
                msig: bool | None = None
                if mv is not None:
                    h = self._hist.setdefault((svc, "mem"), deque(maxlen=p["growth_window_polls"] + 1))
                    h.append(mv)
                    if len(h) > p["growth_window_polls"]:
                        seq = list(h)
                        msig = mv - seq[0] >= p["min_growth_bytes"] and all(b >= a - 3e6 for a, b in zip(seq, seq[1:]))
                    else:
                        msig = None
                    if len(h) >= 2 and h[-1] < h[-2] - 10e6:  # dropped (restart): trend over
                        h.clear()
                        h.append(mv)
                        msig = False
                fire("memory_growth", msig, f"{svc} memory growing ({mv / 1e6:.0f} MB)" if mv else "", mv)

            # --- status
            stat.slis = {k: v for k, v in slis.items() if v is not None}
            stat.updated_at = now
            stat.firing = sorted(k[1] + (f"/{k[2]}" if k[2] else "") for k, s in self._rs.items() if k[0] == svc and s.state == "firing")
            worst = "HEALTHY"
            for (s2, rname, _q), rs in self._rs.items():
                if s2 == svc and rs.state == "firing":
                    h = self.cfg.rules[rname].health
                    if SEVERITY_ORDER[h] > SEVERITY_ORDER[worst]:
                        worst = h
            gap_firing = self._rs.get((svc, "telemetry_gap", ""), _RuleState()).state == "firing" or bool(gap_sig)
            if failed_q:
                stat.state, stat.missing_signal_state = "UNKNOWN", "collection_failed"
            elif gap_sig:
                stat.state = "UNKNOWN" if worst == "HEALTHY" or worst == "UNKNOWN" else worst
                stat.missing_signal_state = "no_data_expected" if decl and decl.service == svc else "no_data_unexpected"
            else:
                stat.state, stat.missing_signal_state = worst, "none"
            if gap_firing and worst == "HEALTHY" and not failed_q:
                stat.state = "UNKNOWN"
            # --- record expected-state observations once per declaration (they must appear in the timeline)
            if decl and decl.service == svc and stat.state in ("UNHEALTHY", "UNKNOWN") and (svc, iso(decl.declared_at)) not in self._expected_noted:
                self._expected_noted.add((svc, iso(decl.declared_at)))
                bg.append(BackgroundEvent(now, now, "note", svc, f"{svc} expected {decl.kind}: {decl.reason} (owner {decl.owner}, "
                                          f"until {iso(decl.expires_at)}); no incident opened", True, f"expected/{svc}/{iso(decl.declared_at)}"))
        self.prometheus_ok = any_ok
        return PollResult(now, out, bg, any_ok, {n: replace(st, slis=dict(st.slis), firing=list(st.firing)) for n, st in self.statuses.items()})

    # ---------------------------------------------------------------- helpers for the incident manager
    def firing_services(self, include_suppressed: bool = False) -> set[str]:
        return {k[0] for k, s in self._rs.items() if s.state == "firing" and (include_suppressed or not s.suppressed)}

    def is_active(self, fingerprint: str) -> bool:
        svc, rule, *q = fingerprint.split("/")
        s = self._rs.get((svc, rule, q[0] if q else ""))
        return bool(s and s.state == "firing")
