"""Test helpers: drive a Detector over a scenario in virtual time."""
from backend.detector.engine import Detector
from datetime import timedelta


def run_detector(world, catalog, cfg, until_s=None, registry=None, start_s=5, on_poll=None):
    det = Detector(world.prom, catalog, cfg, registry)
    fired = []
    t = start_s
    end = until_s if until_s is not None else world.scenario.duration
    while t <= end:
        res = det.poll(world.scenario.at(t))
        fired.extend((t, a) for a in res.alerts)
        if on_poll:
            on_poll(t, res)
        t += world.scenario.step
    return det, fired


def firing(fired, rule=None, service=None, state="firing"):
    return [(t, a) for t, a in fired if a.state == state and (rule is None or a.rule == rule) and (service is None or a.service == service)]
