"""Evidence -> structured facts for the RCA. Reads only stored evidence (never live telemetry)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.domain.catalog import Catalog
from backend.domain.clock import parse_ts
from backend.domain.models import Evidence


@dataclass
class TS:
    service: str
    metric: str
    pts: list[tuple[datetime, float]]
    ev: Evidence
    window_end: datetime

    @property
    def eid(self) -> str:
        return self.ev.evidence_id

    @property
    def last(self) -> float | None:
        return self.pts[-1][1] if self.pts else None

    def tail_mean(self, n: int = 3) -> float | None:
        v = [p[1] for p in self.pts[-n:]]
        return sum(v) / len(v) if v else None

    def ended_early(self, secs: float = 15) -> bool:
        """Series stopped before the window end (e.g. queue_depth vanishes while redis is unreachable)."""
        return bool(self.pts) and (self.window_end - self.pts[-1][0]) > timedelta(seconds=secs)

    def suffix_onset(self, pred) -> datetime | None:
        """Earliest time from which pred holds for every remaining sample."""
        onset = None
        for t, v in reversed(self.pts):
            if pred(v):
                onset = t
            else:
                break
        return onset

    def first_where(self, pred) -> datetime | None:
        return next((t for t, v in self.pts if pred(v)), None)


@dataclass
class LogSig:
    service: str
    kind: str  # conn_fail | too_many | error
    target: str | None
    count: int
    first: datetime
    last: datetime
    eid: str


@dataclass
class Change:
    kind: str
    service: str
    time: datetime
    detail: dict
    eid: str


_CONN = re.compile(r"(?i)connection (failed|refused)|connect: connection refused|dial tcp")
_MANY = re.compile(r"(?i)too many (clients|connections)")


class Facts:
    def __init__(self, evidence: list[Evidence], catalog: Catalog) -> None:
        self.catalog = catalog
        self.evidence = [e for e in evidence if e.payload.get("phase") != "post_action"]
        self._ts: dict[tuple[str, str], TS] = {}
        self.failed: dict[tuple[str, str], Evidence] = {}
        self.empty: dict[tuple[str, str], Evidence] = {}
        self.changes: list[Change] = []
        self.probes: dict[str, Evidence] = {}
        self.logs: dict[str, tuple[Evidence, list[dict]]] = {}
        self.log_failed: dict[str, Evidence] = {}
        self.feed_failed: Evidence | None = None
        self.versions: dict[str, list[str]] = {}
        self.version_since: dict[str, dict[str, datetime]] = {}
        for e in sorted(self.evidence, key=lambda x: (x.collected_at, x.evidence_id)):
            self._ingest(e)
        self.window_end = max((ts.window_end for ts in self._ts.values()), default=None)

    def _ingest(self, e: Evidence) -> None:
        p = e.payload
        m = p.get("metric")
        key = (e.service, m)
        if e.type == "metric":
            if e.status in ("error", "timeout"):
                self.failed[key] = e
                return
            self.failed.pop(key, None)
            if m == "build_version":
                first_seen: dict[str, str] = {}
                for v in sorted(p.get("versions", []), key=lambda r: r["t"]):
                    first_seen.setdefault(v["version"], v["t"])
                self.versions[e.service] = list(first_seen)  # ordered by first appearance: [..., previous, current]
                self.version_since[e.service] = {k: parse_ts(t) for k, t in first_seen.items()}
                self._ts[key] = TS(e.service, m, [], e, parse_ts(p["window"]["end"]))
                return
            pts = [(parse_ts(s["t"]), float(s["v"])) for s in p.get("series", [])]
            if e.status == "empty" or not pts:
                self.empty[key] = e
            else:
                self.empty.pop(key, None)
            self._ts[key] = TS(e.service, m, pts, e, parse_ts(p["window"]["end"]))
        elif e.type == "log":
            if e.status in ("error", "timeout"):
                self.log_failed[e.service] = e
            else:
                self.logs[e.service] = (e, p.get("lines", []))
                self.log_failed.pop(e.service, None)
        elif e.type == "event":
            if e.status in ("error", "timeout"):
                self.feed_failed = e
            else:
                self.changes.append(Change(p.get("kind", ""), e.service, parse_ts(p["event_time"]), p.get("detail", {}), e.evidence_id))
        elif e.type == "probe":
            self.probes[e.service] = e

    # ----------------------------------------------------------------- accessors
    def ts(self, service: str, metric: str) -> TS | None:
        t = self._ts.get((service, metric))
        return t if t and t.pts else None

    def raw(self, service: str, metric: str) -> TS | None:
        return self._ts.get((service, metric))

    def was_collection_failure(self, service: str, metric: str) -> Evidence | None:
        return self.failed.get((service, metric))

    # ----------------------------------------------------------------- derived
    def down_info(self, svc: str) -> tuple[datetime, list[str]] | None:
        """(onset, evidence ids) if up==0 or cd_service_up==0 at the end of the window."""
        hit: list[tuple[datetime, str]] = []
        for m in ("up", "cd_service_up"):
            t = self.ts(svc, m)
            if t and t.last == 0 and not t.ended_early(30):
                on = t.suffix_onset(lambda v: v == 0)
                hit.append((on, t.eid))
            elif t and t.ended_early(30) and m == "up":
                pass
        if not hit:
            return None
        return min(h[0] for h in hit), [h[1] for h in hit]

    def reachable(self, svc: str) -> list[str]:
        """Evidence ids showing the service is up (up==1 and, when present, cd_service_up==1)."""
        ids = []
        for m in ("up", "cd_service_up"):
            t = self.ts(svc, m)
            if t and t.last == 1:
                ids.append(t.eid)
        return ids if ids and not self.down_info(svc) else []

    def dep_down(self, svc: str, dep: str) -> TS | None:
        t = self.ts(svc, f"dependency_up:{dep}")
        return t if t and t.last == 0 else None

    def elevated(self, svc: str, metric: str, thr: float) -> tuple[datetime, TS] | None:
        t = self.ts(svc, metric)
        if t and (t.tail_mean() or 0) >= thr:
            return (t.suffix_onset(lambda v: v >= thr) or t.pts[-1][0]), t
        return None

    def queue_state(self, svc: str) -> dict:
        t = self.raw(svc, "queue_depth")
        out = {"ts": None, "growing": False, "absent": False, "onset": None}
        if not t:
            return out
        out["ts"] = t
        if not t.pts:
            out["absent"] = True
            return out
        if t.ended_early():
            out["absent"], out["onset"] = True, t.pts[-1][0]
            return out
        vals = [v for _, v in t.pts]
        if len(vals) >= 4 and vals[-1] >= 20 and vals[-1] - vals[0] >= 10 and vals[-1] > vals[-4]:
            out["growing"] = True
            out["onset"] = next((tt for tt, v in t.pts if v >= 20), t.pts[-1][0])
        return out

    def restarts(self, svc: str) -> list[datetime]:
        t = self.ts(svc, "start_time")
        out = []
        if t:
            for (_, a), (tb, b) in zip(t.pts, t.pts[1:]):
                if b > a + 1:
                    out.append(datetime.fromtimestamp(b, tb.tzinfo))
        return out

    def change_events(self, svc: str | None = None, kind: str | None = None) -> list[Change]:
        return [c for c in self.changes if (svc is None or c.service == svc) and (kind is None or c.kind == kind)]

    def memory_growth(self, svc: str) -> tuple[TS, float] | None:
        """Positive linear trend before any restart: (series, growth fraction over the window)."""
        t = self.ts(svc, "memory_bytes")
        if not t or len(t.pts) < 6:
            return None
        pts = t.pts
        # use the segment since the last drop (restart) and require mostly monotone increase
        start = 0
        for i in range(1, len(pts)):
            if pts[i][1] < pts[i - 1][1] - 10e6:
                start = i
        seg = pts[start:]
        if len(seg) < 6:
            seg = pts[:start] if start >= 6 else seg
        if len(seg) < 6:
            return None
        ups = sum(1 for (_, a), (_, b) in zip(seg, seg[1:]) if b >= a - 1e6)
        growth = (seg[-1][1] - seg[0][1]) / max(seg[0][1], 1)
        if ups / (len(seg) - 1) >= 0.9 and growth >= 0.25:
            return t, growth
        return None

    def log_sigs(self, svc: str) -> list[LogSig]:
        """Signature classification of UNTRUSTED log text. Targets come only from catalog names."""
        if svc not in self.logs:
            return []
        e, lines = self.logs[svc]
        names = [n for n in self.catalog.names() if n != svc]
        groups: dict[tuple[str, str | None], list[datetime]] = {}
        for ln in lines:
            text, lvl, t = ln.get("line", ""), ln.get("level", ""), parse_ts(ln["t"])
            if lvl not in ("error", "fatal", "critical", "warn"):
                continue
            if _MANY.search(text):
                dbs = [n for n in self.catalog.dependencies(svc) if self.catalog.kind(n) == "database"]
                groups.setdefault(("too_many", dbs[0] if dbs else None), []).append(t)
            elif _CONN.search(text):
                tgt = next((n for n in names if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text)), None)
                groups.setdefault(("conn_fail", tgt), []).append(t)
            elif lvl in ("error", "fatal", "critical"):
                groups.setdefault(("error", None), []).append(t)
        return [LogSig(svc, k, tgt, len(ts), min(ts), max(ts), e.evidence_id) for (k, tgt), ts in sorted(groups.items(), key=lambda kv: str(kv[0]))]

    def error_lines_between(self, svc: str, lo: datetime | None, hi: datetime | None) -> int:
        if svc not in self.logs:
            return 0
        n = 0
        for ln in self.logs[svc][1]:
            t = parse_ts(ln["t"])
            if ln.get("level") in ("error", "fatal", "critical") and (lo is None or t >= lo) and (hi is None or t < hi):
                n += 1
        return n
