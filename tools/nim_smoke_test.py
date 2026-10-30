#!/usr/bin/env python3
"""Capability smoke test for an OpenAI-compatible hosted LLM endpoint (default: NVIDIA NIM).

Usage:
    export NVIDIA_API_KEY=...        # set it in your own shell; never paste it into chat or a file
    python3 tools/nim_smoke_test.py [model-id]

What it checks (about 6 requests, spaced out to stay far below typical rate limits):
    1. model listing with the key
    2. plain chat completion (works? latency?)
    3. "JSON-only by prompt" reliability
    4. response_format={"type": "json_object"}: rejected, or accepted?
    5. nvext.guided_json: rejected, accepted-but-ignored, or actually enforced?
    6. tool calling (tools=[...]): does the model return tool_calls?
    7. any rate-limit headers the server returns

The key is read from the environment and is never printed or written anywhere.
Only synthetic prompts are sent. Standard library only.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
MODEL = sys.argv[1] if len(sys.argv) > 1 else "meta/llama-3.3-70b-instruct"
PAUSE_S = 2.0
HEADER_PREFIXES = ("x-ratelimit", "retry-after", "ratelimit")


def call(path, key, body=None, timeout=90):
    req = urllib.request.Request(BASE + path, method="POST" if body is not None else "GET")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Accept", "application/json")
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    started = time.time()
    headers = {}
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items() if k.lower().startswith(HEADER_PREFIXES)}
            payload = json.loads(resp.read().decode() or "{}")
            return resp.status, payload, time.time() - started, headers
    except urllib.error.HTTPError as err:
        headers = {k.lower(): v for k, v in err.headers.items() if k.lower().startswith(HEADER_PREFIXES)}
        try:
            payload = json.loads(err.read().decode())
        except Exception:
            payload = {"error": "non-json error body"}
        return err.code, payload, time.time() - started, headers
    except Exception as err:  # network errors, timeouts
        return 0, {"error": type(err).__name__}, time.time() - started, headers


def chat(key, messages, **extra):
    body = {"model": MODEL, "messages": messages, "temperature": 0, "max_tokens": 200, "stream": False}
    body.update(extra)
    return call("/chat/completions", key, body)


def text_of(payload):
    try:
        return payload["choices"][0]["message"].get("content") or ""
    except Exception:
        return ""


def short_error(payload):
    err = payload.get("error", payload)
    return str(err)[:160]


def main():
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        print("NVIDIA_API_KEY is not set in this shell. Set it yourself (do not paste it into chat) and re-run.")
        return 2

    result = {"base_url": BASE, "model": MODEL}
    seen_headers = {}
    latencies = []

    status, payload, dt, hdr = call("/models", key)
    seen_headers.update(hdr)
    result["models_listing"] = {"status": status, "count": len(payload.get("data", [])) if status == 200 else None}
    if status == 200:
        ids = {m.get("id") for m in payload.get("data", [])}
        result["model_available"] = MODEL in ids
    time.sleep(PAUSE_S)

    status, payload, dt, hdr = chat(key, [{"role": "user", "content": "Reply with the single word: pong"}])
    seen_headers.update(hdr)
    latencies.append(dt)
    result["plain_chat"] = {"status": status, "latency_s": round(dt, 2),
                            "reply_preview": text_of(payload)[:40] if status == 200 else short_error(payload)}
    if status != 200:
        result["note"] = "plain chat failed; later checks skipped"
        print(json.dumps(result, indent=2))
        return 1
    time.sleep(PAUSE_S)

    prompt = ('Return ONLY a JSON object with keys "cause" (string) and "evidence" (array of strings). '
              'Cause is "redis_unavailable"; evidence is ["EV-001"]. No prose, no code fences.')
    status, payload, dt, hdr = chat(key, [{"role": "user", "content": prompt}])
    seen_headers.update(hdr)
    latencies.append(dt)
    try:
        parsed = json.loads(text_of(payload).strip())
        ok = parsed.get("cause") == "redis_unavailable" and parsed.get("evidence") == ["EV-001"]
    except Exception:
        ok = False
    result["json_by_prompt_valid"] = ok
    time.sleep(PAUSE_S)

    status, payload, dt, hdr = chat(key, [{"role": "user", "content": "Say hello."}],
                                    response_format={"type": "json_object"})
    seen_headers.update(hdr)
    result["response_format_json_object"] = (
        {"status": "rejected", "http": status, "detail": short_error(payload)} if status != 200
        else {"status": "accepted", "output_is_json": _is_json(text_of(payload))})
    time.sleep(PAUSE_S)

    schema = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["alpha", "beta"]}},
              "required": ["verdict"]}
    status, payload, dt, hdr = chat(key, [{"role": "user", "content": "What colour is the sky? Answer in one sentence."}],
                                    nvext={"guided_json": schema})
    seen_headers.update(hdr)
    if status != 200:
        result["guided_json"] = {"status": "rejected", "http": status, "detail": short_error(payload)}
    else:
        try:
            enforced = json.loads(text_of(payload)).get("verdict") in ("alpha", "beta")
        except Exception:
            enforced = False
        result["guided_json"] = {"status": "enforced" if enforced else "accepted_but_not_enforced"}
    time.sleep(PAUSE_S)

    tools = [{"type": "function", "function": {
        "name": "get_service_status", "description": "Return the health status of a service by name.",
        "parameters": {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]}}}]
    status, payload, dt, hdr = chat(key, [{"role": "user", "content": "Check the status of the redis service."}], tools=tools)
    seen_headers.update(hdr)
    latencies.append(dt)
    if status != 200:
        result["tool_calling"] = {"status": "rejected", "http": status, "detail": short_error(payload)}
    else:
        calls = payload["choices"][0]["message"].get("tool_calls")
        result["tool_calling"] = {"status": "returned_tool_calls" if calls else "no_tool_calls_returned"}

    result["latency_s_chat_samples"] = [round(x, 2) for x in latencies]
    result["ratelimit_headers_seen"] = seen_headers or "none returned"
    print(json.dumps(result, indent=2))
    return 0


def _is_json(text):
    try:
        json.loads(text)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
