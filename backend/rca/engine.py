"""Deterministic RCA: candidate generation (topology + change events + signatures) and evidence-weighted scoring.

Outputs ranked hypotheses with supporting claims, CONTRADICTING claims, alternatives, unknowns and a deterministic
confidence. No LLM, no randomness. Rules enforced here:
  * every claim cites >= 1 existing evidence id (a signal without citable evidence counts as unknown, not support);
  * a restart is never a candidate by itself; restarts only enter via memory exhaustion / unknowns (a restart that
    precedes recovery is a remediation marker, not a cause);
  * temporal order alone caps confidence (0.30) and is flagged in confidence_basis;
  * nothing is ever 'confirmed' here (only the verifier / experiment ground truth may do that);
  * missing or failed telemetry is reported as an unknown, never as absence of a fault.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from backend import ENGINE_VERSION
from backend.domain.catalog import Catalog
from backend.domain.clock import Clock, iso
from backend.domain.models import Claim, Diagnosis, Evidence, Hypothesis, RecommendedAction
from backend.remediation.catalogue import recommend

from .facts import TS, Facts

ERR_THR, LAT_THR, CPU_THR = 0.05, 0.5, 1.0
TEMPORAL_ONLY_CAP, CONF_CAP = 0.30, 0.95


class NoEvidence(ValueError):
    pass


@dataclass
class Sig:
    text: str
    ctype: str
    evs: list[str]
    w: float
    stype: str  # metric | log | event | probe
    direct: bool = True  # observation about the cause itself (not just temporal order)


@dataclass
class Cand:
    cause_id: str
    service: str | None
    description: str
    static_unknowns: list[str] = field(default_factory=list)
    sup: list[Sig] = field(default_factory=list)
    con: list[Sig] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    tot: float = 0.0
    context: dict = field(default_factory=dict)
    cap: float | None = None  # ceiling for explanations by exclusion (no positive signature)

    def need(self, ok: bool | None, w: float, text: str, ctype: str, evs: list[str], stype: str, direct: bool = True,
             miss: str | None = None, bad: str | None = None, bad_evs: list[str] | None = None, bad_w: float | None = None) -> None:
        self.tot += w
        if ok is True and evs:
            self.sup.append(Sig(text, ctype, list(dict.fromkeys(evs)), w, stype, direct))
        elif ok is False and bad and (bad_evs or evs):
            self.con.append(Sig(bad, "observation", list(dict.fromkeys(bad_evs or evs)), bad_w or w, stype, True))
        elif miss:
            self.unknowns.append(miss)

    def against(self, text: str, evs: list[str], w: float, stype: str) -> None:
        if evs:
            self.con.append(Sig(text, "observation", list(dict.fromkeys(evs)), w, stype, True))

    # ------------------------------------------------------------- scoring
    def score(self) -> tuple[float, list[str], float]:
        sat = sum(s.w for s in self.sup)
        bad = sum(s.w for s in self.con)
        coverage = sat / self.tot if self.tot else 0.0
        types = {s.stype for s in self.sup}
        tf = {0: 0.0, 1: 0.6, 2: 0.85}.get(len(types), 1.0)
        contra = bad / (bad + sat) if (bad + sat) else 0.0
        conf = coverage * tf * (1 - contra)
        basis = [f"evidence_coverage={coverage:.2f} ({sat:.1f}/{self.tot:.1f} signal weight)",
                 f"independent_signal_types={len(types)} ({', '.join(sorted(types)) or 'none'}) factor={tf:.2f}",
                 f"contradiction_share={contra:.2f}"]
        if self.sup and not any(s.direct for s in self.sup):
            conf = min(conf, TEMPORAL_ONLY_CAP)
            basis.append(f"penalty: only temporal order supports this (confidence capped at {TEMPORAL_ONLY_CAP})")
        if self.cap is not None and conf > self.cap:
            conf = self.cap
            basis.append(f"cap: generic explanation by exclusion, no specific signature (confidence capped at {self.cap})")
        conf = round(min(conf, CONF_CAP), 2)
        return conf, basis, contra


class RcaEngine:
    def __init__(self, catalog: Catalog, clock: Clock) -> None:
        self.catalog, self.clock = catalog, clock

    # ================================================================= entry point
    def diagnose(self, incident_id: str, evidence: list[Evidence], incident_services: list[str]) -> Diagnosis:
        if not evidence:
            raise NoEvidence("diagnosis needs collected evidence")
        f = Facts(evidence, self.catalog)
        cands = self._candidates(f, incident_services)
        emitted, rejected = [], []
        for c in cands:
            (emitted if c.sup else rejected).append(c)
        if not emitted:
            emitted = [self._undetermined(f, incident_services)]
        scored = []
        for c in emitted:
            conf, basis, contra = c.score()
            scored.append((c, conf, basis, contra))
        scored.sort(key=lambda r: (-r[1], self.catalog.depth(r[0].service) if r[0].service else 99, r[0].cause_id))
        global_unknowns = []
        if f.feed_failed:
            global_unknowns.append("change feed (deploy/container events) unavailable: collection failed, so changes are NOT ruled out")
        hyps: list[Hypothesis] = []
        for rank, (c, conf, basis, contra) in enumerate(scored, 1):
            status = "refuted" if contra >= 0.5 else "supported" if conf >= 0.6 and contra < 0.25 else "candidate"
            alts = [f"{o.cause_id} (confidence {oc:.2f})" for o, oc, _, _ in scored if o is not c]
            if rank == 1:
                alts += [f"{r.cause_id} (rejected: " + ("; ".join(s.text for s in r.con[:1]) or "no supporting evidence") + ")" for r in rejected[:4]]
            if not alts:
                alts = ["no competing candidate had supporting evidence"]
            unknowns = list(dict.fromkeys(c.unknowns + c.static_unknowns + global_unknowns))
            hyps.append(Hypothesis(
                rank=rank, cause_id=c.cause_id, service=c.service, description=c.description[:500], confidence=conf,
                confidence_basis=basis, status=status,
                claims=[Claim(text=s.text[:500], type=s.ctype, evidence=s.evs) for s in c.sup],
                contradicting=[Claim(text=s.text[:500], type=s.ctype, evidence=s.evs) for s in c.con],
                alternatives=alts, unknowns=unknowns))
        top = scored[0][0]
        rec = None
        if top.cause_id != "undetermined_cause" or True:
            r = recommend(top.cause_id, top.service, self.catalog, top.context)
            rec = RecommendedAction(action_id=r["action_id"], params=r["params"])
        return Diagnosis(incident_id=incident_id, generated_at=self.clock.now(), origin="rule", engine_version=ENGINE_VERSION,
                         hypotheses=hyps, recommended_action=rec)

    # ================================================================= helpers
    def _symptomatic(self, f: Facts, services: list[str]) -> dict[str, list[tuple[str, datetime, TS | None]]]:
        out: dict[str, list] = {}
        for s in self.catalog.names():
            sy = []
            d = f.down_info(s)
            if d:
                sy.append(("down", d[0], None))
            if (e := f.elevated(s, "error_ratio", ERR_THR)):
                sy.append(("errors", e[0], e[1]))
            slo = self.catalog.get(s).slo_latency_p95 or LAT_THR
            if (e := f.elevated(s, "latency_p95", slo)):
                sy.append(("latency", e[0], e[1]))
            q = f.queue_state(s)
            if q["growing"] or q["absent"]:
                sy.append(("queue", q["onset"] or q["ts"].window_end, q["ts"]))
            for dep in self.catalog.dependencies(s):
                if (t := f.dep_down(s, dep)):
                    sy.append((f"dep:{dep}", t.suffix_onset(lambda v: v == 0) or t.pts[-1][0], t))
            if sy:
                out[s] = sy
        return out

    @staticmethod
    def _onset(sy: dict, services=None) -> datetime | None:
        times = [t for s, items in sy.items() if services is None or s in services for _, t, _ in items]
        return min(times) if times else None

    @staticmethod
    def _ids(*things) -> list[str]:
        out = []
        for t in things:
            if t is None:
                continue
            if isinstance(t, str):
                out.append(t)
            elif isinstance(t, (list, tuple)):
                out.extend(RcaEngine._ids(*t))
            else:
                out.append(t.eid)
        return list(dict.fromkeys(out))

    def _failed_note(self, f: Facts, svc: str, metric: str) -> str | None:
        e = f.was_collection_failure(svc, metric)
        return f"{svc} {metric} NOT observed (collection {e.status})" if e else None

    # ================================================================= candidates
    def _candidates(self, f: Facts, incident_services: list[str]) -> list[Cand]:
        sy = self._symptomatic(f, incident_services)
        cands: list[Cand] = []
        down_services = {s for s in self.catalog.names() if f.down_info(s)}
        # (1) unavailable: S down, or S's dependents report they cannot reach it
        targets = set(down_services)
        for s in sy:
            for dep in self.catalog.dependencies(s):
                if f.dep_down(s, dep):
                    targets.add(dep)
        for s in sorted(targets):
            cands.append(self._unavailable(f, s, sy, down_services))
        # (2) bad deployment
        for s in sorted({c.service for c in f.change_events(kind="deploy")} | {k for k, v in f.versions.items() if len(v) > 1}):
            cands.append(self._bad_deploy(f, s, sy))
        # (3) memory exhaustion
        for s in self.catalog.names():
            if f.memory_growth(s) or any(c.kind == "oom_kill" for c in f.change_events(s)):
                cands.append(self._memory(f, s, sy))
        # (4) cpu saturation
        for s in self.catalog.names():
            if f.elevated(s, "cpu_cores", CPU_THR):
                cands.append(self._cpu(f, s, sy))
        # (5) database connection exhaustion
        for s in self.catalog.names():
            if self.catalog.kind(s) == "database" and any(sig.kind == "too_many" and sig.target == s
                                                          for d in self.catalog.dependents(s) for sig in f.log_sigs(d)):
                cands.append(self._db_exhaustion(f, s, sy))
        # (6) generic local fault of a symptomatic, non-down service
        for s, items in sorted(sy.items()):
            if s not in down_services and self.catalog.kind(s) in ("app", "queue_worker") and any(k in ("errors", "latency", "queue") for k, _, _ in items):
                cands.append(self._local_fault(f, s, items))
        # (6b) dependencies of symptomatic services that were considered and rejected (recorded as alternatives)
        for s in sorted(sy):
            for dep in self.catalog.dependencies(s):
                if dep not in targets and f.reachable(dep):
                    r = Cand(f"{dep.replace('-', '_')}_unavailable", dep, "")
                    r.against(f"{dep} still answers its availability probe (up/cd_service_up == 1), so it is not the cause of {s}'s symptoms", f.reachable(dep), 3, "metric")
                    cands.append(r)
        # (7) telemetry collection failure
        failed = [e for e in f.failed.values()] + list(f.log_failed.values())
        if failed:
            cands.append(self._telemetry(f, failed))
        return cands

    # ---------------------------------------------------------------- unavailable
    def _unavailable(self, f: Facts, s: str, sy: dict, down: set[str]) -> Cand:
        kind = self.catalog.kind(s)
        c = Cand(f"{s.replace('-', '_')}_unavailable", s, f"{s} ({kind}) is unavailable; services that depend on it show the downstream symptoms.",
                 static_unknowns=[f"why {s} stopped: the trigger is not observable from telemetry (only its container state is)"])
        d = f.down_info(s)
        if d:
            c.need(True, 3, f"{s} is down: its availability signal reads 0 (down since {iso(d[0])[11:19]}Z)", "observation", d[1], "metric")
        else:
            miss = self._failed_note(f, s, "cd_service_up" if kind in ("cache", "database") else "up")
            c.need(False, 3, "", "observation", [], "metric", miss=miss, bad=f"{s} still answers its availability probe/scrape (up/cd_service_up == 1)",
                   bad_evs=f.reachable(s), bad_w=4)
        stops = [x for x in f.change_events(s) if x.kind in ("container_stop", "oom_kill")]
        c.need(bool(stops), 1.5, f"container event: {s} was stopped at {iso(stops[0].time)[11:19]}Z" if stops else "", "observation",
               [x.eid for x in stops], "event", miss=None)
        dependents = [x for x in self.catalog.dependents(s)]
        affected = [x for x in dependents if f.dep_down(x, s)]
        if dependents:
            c.need(bool(affected), 2, "dependents report they cannot reach it: " + ", ".join(f"{x} (cd_dependency_up=0)" for x in affected), "inference",
                   [f.dep_down(x, s).eid for x in affected], "metric",
                   bad="no dependent reports a lost connection to it" if all(f.ts(x, f"dependency_up:{s}") for x in dependents) else None,
                   bad_evs=[f.ts(x, f"dependency_up:{s}").eid for x in dependents if f.ts(x, f"dependency_up:{s}")])
        sym = [(x, items) for x, items in sy.items() if x in dependents and any(k in ("errors", "latency", "queue", "down") for k, _, _ in items)]
        if sym:
            ev = [t.eid for _, items in sym for k, _, t in items if t is not None and k in ("errors", "latency", "queue")]
            c.need(bool(ev), 1.5, "symptoms on dependents (" + ", ".join(f"{x}: {', '.join(k for k, _, _ in it if not k.startswith('dep:'))}" for x, it in sym if any(not k.startswith('dep:') for k, _, _ in it)) + ") are attributed to this dependency", "inference", ev, "metric")
        if kind == "queue_worker":
            q = f.queue_state(s)
            c.need(bool(q["growing"]), 2, f"the job queue backlog grows ({q['ts'].last:.0f} jobs) because nothing consumes it" if q["growing"] else "", "inference",
                   [q["ts"].eid] if q["ts"] else [], "metric", miss=self._failed_note(f, s, "queue_depth"))
            if s in f.logs and d:
                n = f.error_lines_between(s, None, d[0])
                c.need(n > 0, 1, f"{s} logged {n} error-level line(s) just before it went down (abrupt end of logs)", "observation", [f.logs[s][0].evidence_id], "log")
            healthy = [x for x in self.catalog.dependents(s) + [y for y in self.catalog.names() if y not in (s,) and self.catalog.kind(y) == "app"] if f.reachable(x)]
            if healthy and d:
                c.need(True, 1, "user-facing services stay healthy (" + ", ".join(sorted(set(healthy))) + "): the failure is contained to " + s, "observation",
                       self._ids([f.reachable(x) for x in healthy]), "metric")
        sigs = [(sg, x) for x in dependents for sg in f.log_sigs(x) if sg.kind == "conn_fail" and sg.target == s]
        c.need(bool(sigs), 2, "logs of " + ", ".join(sorted({x for _, x in sigs})) + f" show repeated connection failures to {s} ({sum(sg.count for sg, _ in sigs)} error lines)", "observation",
               [sg.eid for sg, _ in sigs], "log",
               miss=("; ".join(f"{x} logs NOT observed (collection {e.status})" for x, e in f.log_failed.items() if x in dependents) or None))
        # temporal order: cause must precede the downstream symptoms
        if d and sym:
            first_sym = min(t for _, items in sym for k, t, _ in items if not k.startswith("dep:") or True)
            c.need(d[0] <= first_sym, 1, f"{s} went down at {iso(d[0])[11:19]}Z, before the first downstream symptom at {iso(first_sym)[11:19]}Z", "temporal_correlation",
                   self._ids(d[1], [t.eid for _, items in sym for _, _, t in items if t is not None]), "metric", direct=False,
                   bad=f"downstream symptoms began before {s} went down", bad_w=2)
        # local cause: none of its own dependencies is down
        deps = self.catalog.dependencies(s)
        bad_deps = [x for x in deps if x in down]
        if deps:
            c.need(not bad_deps, 1, f"none of {s}'s own dependencies is down", "observation", self._ids([f.reachable(x) for x in deps]), "metric",
                   bad=f"{s}'s own dependency {bad_deps[0]} is also down: the upstream cause is more likely" if bad_deps else None,
                   bad_evs=self._ids([f.down_info(x)[1] for x in bad_deps]), bad_w=3)
        pr = f.probes.get(s)
        if pr and pr.payload.get("ok") is True and d:
            c.against(f"the independent synthetic probe of {s} succeeded although its availability signal reads 0", [pr.evidence_id], 3, "probe")
        return c

    # ---------------------------------------------------------------- bad deployment
    def _bad_deploy(self, f: Facts, s: str, sy: dict) -> Cand:
        deploys = f.change_events(s, "deploy")
        dp = deploys[-1] if deploys else None
        c = Cand(f"{s.replace('-', '_')}_bad_deployment", s,
                 f"A deployment of {s} preceded the symptoms; the new version may be defective." if dp else f"The version label of {s} changed.",
                 static_unknowns=["which code or configuration change is defective is not observable from telemetry"])
        if dp:
            c.context["previous_version"] = dp.detail.get("version_from")
            c.need(True, 2, f"deploy event: {s} {dp.detail.get('version_from')} -> {dp.detail.get('version_to')} at {iso(dp.time)[11:19]}Z", "temporal_correlation", [dp.eid], "event", direct=False)
        vers = f.versions.get(s, [])
        vt = f.raw(s, "build_version")
        if vt:
            c.need(len(vers) > 1, 1, f"the build_info version label of {s} changed within the window ({', '.join(vers)})", "observation", [vt.eid], "metric")
        own = [(k, t, ts) for k, t, ts in sy.get(s, []) if k in ("errors", "latency", "down")]
        healthy = f.reachable(s)
        if own:
            ev = self._ids([ts for _, _, ts in own if ts is not None], [f.down_info(s)[1]] if f.down_info(s) else [])
            c.need(True, 3, f"{s} shows its own symptoms ({', '.join(k for k, _, _ in own)})", "observation", ev, "metric")
            onset = min(t for _, t, _ in own)
            if dp:
                c.need(onset >= dp.time, 2, f"{s} symptoms began at {iso(onset)[11:19]}Z, after the change at {iso(dp.time)[11:19]}Z", "temporal_correlation",
                       self._ids(dp.eid, [ts for _, _, ts in own if ts is not None]), "metric", direct=False,
                       bad=f"{s} symptoms began at {iso(onset)[11:19]}Z, BEFORE the change at {iso(dp.time)[11:19]}Z", bad_w=3)
                lo, hi = dp.time, None
                after, before = f.error_lines_between(s, lo, hi), f.error_lines_between(s, None, lo)
                if s in f.logs:
                    c.need(after > 0 and before == 0, 2, f"new error-level log signature on {s} after the deploy ({after} lines, none before)", "observation",
                           [f.logs[s][0].evidence_id], "log")
        else:
            c.need(False, 3, "", "observation", [], "metric", bad=f"{s} shows no symptoms after the change (availability and SLIs normal)",
                   bad_evs=self._ids(healthy, [f.ts(s, m) for m in ("error_ratio", "latency_p95", "queue_depth") if f.ts(s, m)]), bad_w=4,
                   miss=self._failed_note(f, s, "up"))
            others = [x for x in sy if x != s and not set(self.catalog.dependents(s)) & {x} and x not in self.catalog.transitive_dependents(s)]
            reach = self.catalog.transitive_dependents(s)
            if sy and not (set(sy) & reach):
                ev = self._ids([ts for items in sy.values() for _, _, ts in items if ts is not None][:3])
                c.against("the symptomatic services do not depend on " + s + ", so the deploy has no path to the observed impact", ev, 3, "metric")
        causes = [x for x in sy if any(k == "down" for k, _, _ in sy[x]) and x != s and x in self.catalog.dependencies(s)]
        if causes and own:
            c.against(f"{s} has a dependency that is down ({causes[0]}), an alternative explanation for its errors", self._ids(f.down_info(causes[0])[1]), 3, "metric")
        return c

    # ---------------------------------------------------------------- memory exhaustion
    def _memory(self, f: Facts, s: str, sy: dict) -> Cand:
        g = f.memory_growth(s)
        ooms = [x for x in f.change_events(s) if x.kind == "oom_kill"]
        restarts = f.restarts(s)
        c = Cand(f"{s.replace('-', '_')}_memory_exhaustion", s, f"{s} leaks memory until it reaches its limit and is killed; restarting only resets the leak.",
                 static_unknowns=["the leaking code path is not identifiable from telemetry; a restart is a temporary mitigation only"],
                 context={"restarts": max(len(restarts), len(ooms))})
        c.need(bool(g), 3, f"{s} memory grows steadily (+{(g[1] * 100):.0f}% over the observed segment)" if g else "", "observation", [g[0].eid] if g else [], "metric",
               bad=f"no sustained memory growth trend on {s}", bad_evs=[f.ts(s, 'memory_bytes').eid] if f.ts(s, "memory_bytes") else [], miss=self._failed_note(f, s, "memory_bytes"))
        c.need(bool(ooms), 2, f"container event: OOM kill of {s} at {iso(ooms[0].time)[11:19]}Z" + (f" ({len(ooms)} times)" if len(ooms) > 1 else "") if ooms else "", "observation",
               [x.eid for x in ooms], "event")
        st = f.ts(s, "start_time")
        c.need(bool(restarts), 1.5, f"process restarted {len(restarts)} time(s) (process_start_time_seconds changed)" if restarts else "", "observation",
               [st.eid] if st else [], "metric")
        dn = f.down_info(s)
        own_err = [ts for k, _, ts in sy.get(s, []) if k in ("errors", "latency") and ts is not None]
        c.need(bool(own_err) or bool(dn) or bool(restarts), 1, f"availability/error symptoms on {s} coincide with the kills", "inference",
               self._ids(own_err, dn[1] if dn else []) or ([st.eid] if st and restarts else []), "metric")
        if len(ooms) >= 2 or len(restarts) >= 2:
            c.static_unknowns.append("the fault recurred after a restart: restarting again will not remove the cause")
        return c

    # ---------------------------------------------------------------- cpu saturation
    def _cpu(self, f: Facts, s: str, sy: dict) -> Cand:
        cpu = f.elevated(s, "cpu_cores", CPU_THR)
        c = Cand(f"{s.replace('-', '_')}_cpu_saturation", s, f"{s} is CPU-saturated, raising latency without causing errors.",
                 static_unknowns=["the process or workload consuming CPU is not identifiable from telemetry"])
        c.need(True, 3, f"{s} CPU use is {cpu[1].tail_mean():.2f} cores (baseline ~0.2)", "observation", [cpu[1].eid], "metric")
        slo = self.catalog.get(s).slo_latency_p95 or LAT_THR
        lat = f.elevated(s, "latency_p95", slo)
        c.need(bool(lat), 2, f"{s} p95 latency {lat[1].tail_mean():.2f}s is above {slo}s" if lat else "", "observation", [lat[1].eid] if lat else [], "metric",
               bad=f"{s} latency is within SLO", bad_evs=[f.ts(s, 'latency_p95').eid] if f.ts(s, "latency_p95") else [])
        err = f.elevated(s, "error_ratio", ERR_THR)
        et = f.ts(s, "error_ratio")
        c.need(not err and bool(et), 1, f"{s} error ratio stays low: latency without errors", "observation", [et.eid] if et else [], "metric",
               bad=f"{s} also shows an error ratio of {err[1].tail_mean():.2f}, which CPU saturation alone does not explain" if err else None, bad_evs=[err[1].eid] if err else [])
        if lat:
            c.need(cpu[0] <= lat[0], 1.5, f"CPU rose at {iso(cpu[0])[11:19]}Z, no later than the latency rise at {iso(lat[0])[11:19]}Z", "temporal_correlation",
                   [cpu[1].eid, lat[1].eid], "metric", direct=False, bad="latency rose before CPU did", bad_w=2)
        deps_down = [d for d in self.catalog.dependencies(s) if f.down_info(d)]
        if deps_down:
            c.against(f"dependency {deps_down[0]} is down, an alternative explanation", self._ids(f.down_info(deps_down[0])[1]), 3, "metric")
        return c

    # ---------------------------------------------------------------- db connection exhaustion
    def _db_exhaustion(self, f: Facts, s: str, sy: dict) -> Cand:
        c = Cand(f"{s.replace('-', '_')}_connection_exhaustion", s, f"{s} is running but out of connections; clients cannot connect although the process is healthy.",
                 static_unknowns=["connection counts / max_connections are not part of the telemetry contract, so the leaking client is not identified"])
        hits = [(d, sg) for d in self.catalog.dependents(s) for sg in f.log_sigs(d) if sg.kind == "too_many" and sg.target == s]
        c.need(True, 3, "error logs of " + ", ".join(sorted({d for d, _ in hits})) + " report the connection limit being reached", "observation", [sg.eid for _, sg in hits], "log")
        lost = [d for d in self.catalog.dependents(s) if f.dep_down(d, s)]
        c.need(bool(lost), 2, "dependents report they cannot reach it: " + ", ".join(lost), "inference", [f.dep_down(d, s).eid for d in lost], "metric")
        reach = f.reachable(s)
        c.need(bool(reach), 2, f"{s} itself answers its availability probe (up/cd_service_up == 1): it is not down", "observation", reach, "metric",
               bad=f"{s} does not answer its probe", bad_evs=f.down_info(s)[1] if f.down_info(s) else [])
        c.need(len(lost) >= 2, 1, "more than one dependent is affected", "inference", self._ids([f.dep_down(d, s) for d in lost]), "metric")
        return c

    # ---------------------------------------------------------------- local fault
    def _local_fault(self, f: Facts, s: str, items: list) -> Cand:
        c = Cand(f"{s.replace('-', '_')}_local_fault", s, f"A defect or overload local to {s} (not explained by a dependency).", cap=0.35,
                 static_unknowns=[f"no local signature (deploy, memory, CPU) was observed for {s}"])
        ev = self._ids([t for k, _, t in items if t is not None and not k.startswith("dep:")])
        syms = ", ".join(sorted({k for k, _, _ in items if not k.startswith("dep:")}))
        c.need(bool(ev), 2, f"{s} shows symptoms ({syms})", "observation", ev, "metric")
        deps = self.catalog.dependencies(s)
        bad = [d for d in deps if f.dep_down(s, d) or f.down_info(d)]
        okeys = self._ids([f.reachable(d) for d in deps if d not in bad])
        c.need(not bad, 3, f"all dependencies of {s} are reachable", "observation", okeys, "metric",
               bad=f"{s}'s dependency {bad[0]} is down/unreachable, which explains its symptoms" if bad else None,
               bad_evs=self._ids([f.dep_down(s, d) for d in bad], [f.down_info(d)[1] for d in bad if f.down_info(d)]), bad_w=4)
        return c

    # ---------------------------------------------------------------- telemetry
    def _telemetry(self, f: Facts, failed: list[Evidence]) -> Cand:
        svc = sorted({e.service for e in failed})[0]
        c = Cand("telemetry_collection_failed", svc, "Part of the telemetry could not be collected; service state in the affected scope is unknown, not healthy.",
                 static_unknowns=["service health during the collection failure cannot be established; do not remediate from missing data"])
        c.need(True, 3, f"{len(failed)} evidence queries failed (error/timeout) for {', '.join(sorted({e.service for e in failed}))}", "observation",
               [e.evidence_id for e in failed][:20], "metric")
        c.tot += 1
        return c

    def _undetermined(self, f: Facts, services: list[str]) -> Cand:
        ids = [e.evidence_id for e in f.evidence if e.service in services][:3] or [f.evidence[0].evidence_id]
        c = Cand("undetermined_cause", services[0] if services else None, "No candidate cause is supported by the collected evidence.",
                 static_unknowns=["the cause is not determined; escalate to a human"])
        c.sup.append(Sig("an incident was detected but no signature matched the collected evidence", "hypothesis", ids, 1.0, "metric", direct=False))
        c.tot = 4.0
        return c
