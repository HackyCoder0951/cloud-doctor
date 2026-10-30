# Source Register

Every cited source is logged here before use. **Access date:** 2026-10-31.

**Verification levels**

- **V-page** — page was fetched and read; findings extracted. Extraction was done by a fetch tool that converts pages through a model, so wording may differ slightly from the page. **Verify exact wording against the live page before quoting in a publication.**
- **V-partial** — only part of the page reached verbatim; remainder came as a model summary. Treat claims as *Unverified / requires validation* until re-checked.
- **V-search** — seen only as a search result/snippet. Not citable for claims yet.

| ID | Source | Tier | URL | Level | Used for |
|---|---|---|---|---|---|
| S-001 | Google SRE Book, Ch. 4 "Service Level Objectives" | 1 | https://sre.google/sre-book/service-level-objectives/ | V-page | SLI/SLO/SLA definitions, percentiles, targets, error budget |
| S-002 | Google SRE Book, Ch. 6 "Monitoring Distributed Systems" | 1 | https://sre.google/sre-book/monitoring-distributed-systems/ | V-page | Golden signals, symptoms vs. causes, alerting philosophy, dependency-rule caveat |
| S-003 | Google SRE Workbook, Ch. 5 "Alerting on SLOs" | 1 | https://sre.google/workbook/alerting-on-slos/ | V-page | Alert evaluation criteria, burn-rate strategies, low-traffic services |
| S-004 | Prometheus — Alertmanager | 1 | https://prometheus.io/docs/alerting/latest/alertmanager/ | V-page | Grouping, inhibition, silencing |
| S-005 | Prometheus — Alerting rules | 1 | https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/ | V-page | `for`, `keep_firing_for`, pending/firing |
| S-006 | Prometheus — Metric and label naming | 1 | https://prometheus.io/docs/practices/naming/ | V-page | Label/cardinality guidance |
| S-007 | Prometheus — Overview | 1 | https://prometheus.io/docs/introduction/overview/ | V-page | Pull model, local storage, accuracy limits |
| S-008 | OpenTelemetry — Observability primer | 1 | https://opentelemetry.io/docs/concepts/observability-primer/ | V-page | Observability/telemetry definitions |
| S-009 | OpenTelemetry — Logs signal | 1 | https://opentelemetry.io/docs/concepts/signals/logs/ | V-page | Log–trace correlation fields |
| S-010 | Kubernetes — Liveness, readiness, startup probes | 1 | https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/ | V-partial | Probe semantics (probe content came as summary; recheck) |
| S-011 | Grafana Loki — Cardinality / label best practices | 1 | https://grafana.com/docs/loki/latest/get-started/labels/bp-labels/ | V-search | Label cardinality (not yet read in full) |
| S-012 | OpenTelemetry — Signals | 1 | https://opentelemetry.io/docs/concepts/signals/ | V-search | Signal list (not yet read) |
| S-013 | Google SRE Book, Ch. 14 "Managing Incidents" | 1 | https://sre.google/sre-book/managing-incidents/ | V-page | Incident roles, living document, declare early |
| S-014 | Google SRE Book, Ch. 15 "Postmortem Culture" | 1 | https://sre.google/sre-book/postmortem-culture/ | V-page | Postmortem content, blamelessness |
| S-015 | Google SRE Book, Ch. 12 "Effective Troubleshooting" | 1 | https://sre.google/sre-book/effective-troubleshooting/ | V-page | Hypothesis-driven diagnosis, spurious correlation pitfalls |
| S-016 | Grafana Loki — Overview | 1 | https://grafana.com/docs/loki/latest/get-started/overview/ | V-page | Label-only indexing |
| S-017 | Grafana Loki — Cardinality | 1 | https://grafana.com/docs/loki/latest/get-started/labels/cardinality/ | V-page | Cardinality limits, structured metadata |
| S-018 | Kubernetes — Pod probes (concepts), v1.37 page | 1 | https://kubernetes.io/docs/concepts/workloads/pods/probes/ | V-partial (defaults and liveness warnings verbatim from final slice; start of page via summary) | Probe semantics, defaults |
| S-019 | Kubernetes — Pod lifecycle | 1 | https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/ | V-partial (summary) | restartPolicy, CrashLoopBackOff backoff |
| S-020 | Wang & Qi 2024, "A Comprehensive Survey on Root Cause Analysis in (Micro) Services", arXiv:2408.00803 | 2 | https://arxiv.org/abs/2408.00803 | V-partial (abstract + first ~27% verbatim) | RCA taxonomy, challenges |
| S-021 | Pham, Ha & Zhang 2024, "Root Cause Analysis for Microservices based on Causal Inference: How Far Are We?", arXiv:2408.13729 (ASE'24) | 2 | https://arxiv.org/abs/2408.13729 | V-partial (abstract + first ~35% verbatim; numbers via summary) | Empirical comparison of causal RCA |
| S-022 | Soldani & Brogi 2021, "Anomaly Detection and Failure Root Cause Analysis in (Micro)Service-Based Cloud Applications: A Survey", arXiv:2105.12378 | 2 | https://arxiv.org/abs/2105.12378 | V-page (abstract only) | Scope only |
| S-023 | Zhang et al. 2024, "Automated Root Causing of Cloud Incidents using In-Context Learning with GPT-4", arXiv:2401.13810 | 2 | https://arxiv.org/abs/2401.13810 | V-page (abstract only) | LLM RCA on Microsoft incidents |
| S-024 | Roy et al. 2024, "Exploring LLM-based Agents for Root Cause Analysis", arXiv:2403.04123 | 2 | https://arxiv.org/abs/2403.04123 | V-page (abstract only) | ReAct agents with retrieval tools |
| S-025 | Ahmed et al. 2023, "Recommending Root-Cause and Mitigation Steps for Cloud Incidents using LLMs", arXiv:2301.03797 (ICSE 2023) | 2 | https://arxiv.org/abs/2301.03797 | V-page (abstract only) | LLM RCA and mitigation, fine-tuned GPT-3.x |
| S-026 | Riddell et al. 2026, "Stalled, Biased, and Confused: Uncovering Reasoning Failures in LLMs for Cloud-Based Root Cause Analysis", arXiv:2601.22208 (FORGE 2026) | 2 | https://arxiv.org/abs/2601.22208 | V-page (abstract only) | LLM RCA reasoning failures |
| S-027 | Principles of Chaos Engineering (page last updated 2019-03) | 1 | https://principlesofchaos.org/ | V-page | Steady state, blast radius |
| S-028 | Toxiproxy README (Shopify) | 1 | https://github.com/Shopify/toxiproxy | V-page | Network fault injection, toxics, API auth caveat |
| S-029 | Docker — Resource constraints | 1 | https://docs.docker.com/engine/containers/resource_constraints/ | V-page | Memory/CPU limits, OOM |
| S-030 | Docker — Security | 1 | https://docs.docker.com/engine/security/ | V-page (parts dated) | Daemon attack surface, namespaces, cgroups, capabilities |
| S-031 | Docker — Protect the daemon socket | 1 | https://docs.docker.com/engine/security/protect-access/ | V-page | Daemon access = root on host |
| S-032 | Docker — `docker run` reference page | 1 | https://docs.docker.com/engine/containers/run/ | V-partial | Default capabilities, --privileged |
| S-033 | Docker Compose — Networking | 1 | https://docs.docker.com/compose/how-tos/networking/ | V-page | `internal: true`, network isolation |
| S-034 | Open Policy Agent — Docs | 1 | https://www.openpolicyagent.org/docs | V-page | Decision/enforcement decoupling, Rego, `default` |
| S-035 | Open Policy Agent — Policy language | 1 | https://www.openpolicyagent.org/docs/policy-language | V-partial | Rego semantics |
| S-036 | OWASP Top 10 for LLM Applications 2025 (+ LLM01, LLM02, LLM05, LLM06 pages) | 1 | https://genai.owasp.org/llm-top-10/ | V-page | LLM threat categories |
| S-037 | Anthropic — Tool use overview (platform.claude.com) | 1 | https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview | V-page (model-extracted) | Client-executed tool calls |
| S-038 | Anthropic — Mitigate jailbreaks and prompt injections | 1 | https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks | V-page (model-extracted) | Indirect injection mitigations |
| S-039 | Fowler, "CircuitBreaker" (2014-03-06) | 2 | https://martinfowler.com/bliki/CircuitBreaker.html | V-page | Circuit breaker states |
| S-040 | kind — home and quick start | 1 | https://kind.sigs.k8s.io/ | V-page | Purpose, prerequisites, runtime options |
| S-041 | Kubernetes — RBAC authorization | 1 | https://kubernetes.io/docs/reference/access-authn-authz/rbac/ | V-partial (relevant sections via summary) | Additive permissions, least privilege |
| S-042 | Kubernetes — Network policies | 1 | https://kubernetes.io/docs/concepts/services-networking/network-policies/ | V-partial (relevant sections via summary) | Default non-isolation, CNI enforcement requirement |
| S-043 | Docker — Rootless mode | 1 | https://docs.docker.com/engine/security/rootless/ | V-page | Daemon and containers as non-root; limitations section not on this page |
| S-044 | Prometheus — Query functions | 1 | https://prometheus.io/docs/prometheus/latest/querying/functions/ | V-partial (rate, predict_linear via summary) | absent, increase, deriv, double_exponential_smoothing, histogram_quantile |
| S-045 | OPA — Integrating OPA; Decision Logs (search results; pages not opened) | 1 | https://www.openpolicyagent.org/docs/integration , https://www.openpolicyagent.org/docs/management-decision-logs.md | V-search | Sidecar/external-service deployment, decision logs (search snippets mix doc versions) |
| S-046 | Anthropic — Structured outputs; Strict tool use (search results; pages not opened) | 1 | https://platform.claude.com/docs/en/build-with-claude/structured-outputs , https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use | V-search | `strict: true` constrains tool inputs to schema; `output_config.format`; restrictions on `tool_choice` for some models |
| S-047 | Pham, Ha & Zhang 2024, "BARO", arXiv:2405.09330 (FSE 2024) | 2 | https://arxiv.org/pdf/2405.09330 | V-search | Bayesian online change-point detection + scoring for RCA |
| S-048 | Kalinagac, Soussi & Gür 2022, "GRALAF" (CNSM 2022) | 2 | https://dl.ifip.org/db/conf/cnsm/cnsm2022/64.pdf | V-search | Causal Bayesian network from fault-injection data |
| S-049 | Secondary articles on MTTR/MTTD (keploy, ClickHouse, OpenObserve, Metabase, Hatica — search results) | 3 | (see search results; not individually opened) | V-search | Only to show that definitions vary; not authoritative |
| S-050 | Grafana Loki — Structured metadata | 1 | https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/ | V-page | Querying structured metadata, requirements, limits |
| S-051 | Grafana Loki — Configure (`limits_config`) | 1 | https://grafana.com/docs/loki/latest/configure/ | V-partial (limits_config verbatim; rest summary) | Label limit, sample-age window, unordered writes |
| S-052 | OPA — Integrating OPA | 1 | https://www.openpolicyagent.org/docs/integration | V-page | Deployment modes; no fail-open/closed statement found |
| S-053 | OPA — Decision logs | 1 | https://www.openpolicyagent.org/docs/management-decision-logs | V-page | Log contents, delivery, drops, retry (supersedes S-045) |
| S-054 | Anthropic — Strict tool use | 1 | https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use | V-page | `strict: true`, grammar-constrained sampling (supersedes S-046 for strict tool use) |
| S-055 | Anthropic — Structured outputs | 1 | https://platform.claude.com/docs/en/build-with-claude/structured-outputs | V-partial (first ~38% verbatim; JSON Schema limits via summary) | `output_config.format`, schema limits |
| S-056 | kind — Known issues | 1 | https://kind.sigs.k8s.io/docs/user/known-issues/ | V-page | inotify limits, cgroup namespace, disk/memory |
| S-057 | kind — Configuration | 1 | https://kind.sigs.k8s.io/docs/user/configuration/ | V-page | Default CNI (kindnetd), `disableDefaultCNI` |
| S-058 | Docker — Rootless troubleshooting | 1 | https://docs.docker.com/engine/security/rootless/troubleshoot/ | V-page | Known limitations, cgroup requirements, networking |
| S-059 | Docker — Rootless tips | 1 | https://docs.docker.com/engine/security/rootless/tips/ | V-page | Resource limits, systemd |
| S-060 | Prometheus — Alertmanager configuration | 1 | https://prometheus.io/docs/alerting/latest/configuration/ | V-page | Route timing defaults, inhibit rules, webhook payload |
| S-061 | Prometheus — Alertmanager high availability | 1 | https://prometheus.io/docs/alerting/latest/high_availability/ | V-page | Gossip, dedup, fail-open, at-least-once |
| S-062 | Kim et al. 2022, "Towards a Rigorous Evaluation of Time-Series Anomaly Detection", AAAI 2022 (arXiv:2109.05257) | 2 | https://arxiv.org/abs/2109.05257 | V-search (abstract-level via snippets; not opened) | Point-adjust evaluation inflates results |
| S-063 | Xu et al. 2025, "OpenRCA: Can Large Language Models Locate the Root Cause of Software Failures?", ICLR 2025; critique and follow-ups via search | 2 | https://iclr.cc/virtual/2025/poster/32093 | V-search (not opened; critique source is a vendor blog, Tier 3) | LLM RCA benchmark scope and criticism |
| S-064 | Vendor articles on alert/event correlation (BigPanda, Moogsoft, Datadog, Middleware, etc.) — search results | 3 | (see search results; none opened) | V-search | Practitioner view of correlation techniques; not authoritative |
| S-065 | Skorski 2018, "Simple Root Cause Analysis by Separable Likelihoods", arXiv:1808.04302 (single author, Dell; local PDF, 12 pp.) | 2 | https://arxiv.org/abs/1808.04302 | V-page (full read) | Bayesian anomaly explanation on error-log counts |
| S-066 | Solé, Muntés-Mulero, Rana & Estrada 2017, "Survey on Models and Techniques for Root-Cause Analysis", arXiv:1701.08546 (local PDF, 18 pp.) | 2 | https://arxiv.org/abs/1701.08546 | V-page (pp. 1–12 read; reference pages skimmed) | RCA terminology, model taxonomy, inference complexity |
| S-067 | Liu, Wang, Lin, Tan & Zhou 2021, "RCA: A Deep Collaborative Autoencoder Approach for Anomaly Detection", IJCAI-21 (local PDF `0208.pdf`, 7 pp.). **Note: "RCA" here = Robust Collaborative Autoencoders, not root-cause analysis.** | 2 | local file | V-page (full read) | Robust unsupervised anomaly detection under contaminated training data |
| S-068 | Gunawat & Gupta 2025, "Applying Causal Inference AI Models to Root Cause Analysis (RCA) in DevOps", IJRTI 10(5) (local PDF, 7 pp.) | 3 | local file | V-page (full read). Conceptual framework; **no experiment or results section found in the text read, despite the abstract mentioning experimentation** | Background only |
| S-069 | Roberts, Bassett & Lochner 2019, "Bayesian Anomaly Detection and Classification (BADAC)", arXiv:1902.08627 (local PDF, 29 pp.) | 2 | https://arxiv.org/abs/1902.08627 | V-partial (pp. 1–10 of 29 read) | Uncertainty-aware Bayesian anomaly detection; Rank-Weighted Score |
| S-070 | GitHub repo SanjanaGunalan33/Bayes ("Bayesian Root Cause Analysis using RCAEval telemetry") | 3 | https://github.com/SanjanaGunalan33/Bayes | V-page (repo page only; no code read; **no licence found**; self-reported results) | Example of naive-Bayes RCA on benchmark data |
| S-071 | OneUptime blog, "Understanding MTTR, MTTD, MTBF…" (2025-09-04) | 3 | https://oneuptime.com/blog/post/2025-09-04-what-is-mttr-mttd-mtbf-and-more/view | V-page (vendor marketing) | Metric definitions (note internal inconsistency) |
| S-072 | ClickHouse blog, "What is MTTR? MTTD, MTBF…" (updated 2026-07-29) | 3 | https://clickhouse.com/resources/engineering/mttr-mttd | V-page (vendor marketing) | Metric definitions and caveats |
| S-073 | Prometheus-users thread, "Does AlertManager repeatedly try POST request on web-hook url if web-hook returns 500?" (2019) | 3 | https://groups.google.com/g/prometheus-users/c/9fqrJy-0phI | V-page; replier's project role not stated on page | Webhook retry on 5xx (dated) |
| S-074 | Alertmanager GitHub discussion #4310 (2025; answer by a labelled maintainer) | 3 | https://github.com/prometheus/alertmanager/discussions/4310 | V-page | Notification log file, restart behavior |
| S-075 | Netdata, "Docker socket security" guide | 3 | https://www.netdata.cloud/guides/docker/docker-socket-security/ | V-partial (~68% verbatim; vendor) | Socket access = root-equivalent (vendor claim) |
| S-076 | M. Vysny, "Docker rootless" (personal blog, 2026-06-01) | 3 | https://mvysny.github.io/docker-rootless/ | V-page | Root-equivalence of daemon/group; rootless setup pitfalls |
| S-077 | H. Schmidt, dev.to post on Docker socket permission denials | 3 | https://dev.to/hannah_schmidt/notes-from-a-3-am-on-call-docker-daemon-socket-permission-denials-that-survive-group-membership-1123 | V-page (personal post; unsourced claims) | Not used for claims |
| S-078 | Docker Community Forums thread on mounting docker.sock as non-root | 3 | https://forums.docker.com/t/mounting-using-var-run-docker-sock-in-a-container-not-running-as-root/34390 | V-page | socat relay still runs as root |
| S-079 | minikube handbook — Network policy (official; last modified 2026-05-04) | 1 | https://minikube.sigs.k8s.io/docs/handbook/network_policy/ | V-page | Default CNI (Kindnet) does not enforce NetworkPolicy; `--cni calico` |
| S-080 | Obelinf blog, "Kubernetes network policies explained" (vendor, 2026-10-07) | 3 | https://obelinf.com/blog/kubernetes-network-policies-explained-with-examples/ | V-page | Default-deny gotchas (DNS) |
| S-081 | Cheveo blog, "Network policies cheatsheet" (consultancy, 2026-05-20) | 3 | https://www.cheveo.de/en/blog/network-policies-cheatsheet | V-page | Kindnet "accepted but never enforced" claim; patterns |
| S-082 | KEP-6313 "Network-Isolated Pod Sandboxes" (alpha, v1.38 target) | 1 | https://www.kubernetes.dev/resources/keps/6313/ | V-partial | Not relevant to NetworkPolicy enforcement; noted only |
| S-083 | Anthropic — Pricing (no "last updated" date shown on page; read 2026-10-31) | 1 | https://platform.claude.com/docs/en/about-claude/pricing | V-page (tables verbatim; tail via summary) | Per-token prices, cache multipliers, batch discount |
| S-084 | Anthropic — Token counting | 1 | https://platform.claude.com/docs/en/build-with-claude/token-counting | V-page (code verbatim; tail via summary) | Pre-request token estimates; tokenizer difference |
| S-085 | Anthropic — Prompt caching | 1 | https://platform.claude.com/docs/en/build-with-claude/prompt-caching | V-page | TTLs, minimum lengths, read/write multipliers |
| S-086 | Anthropic — API and data retention | 1 | https://platform.claude.com/docs/en/manage-claude/api-and-data-retention | V-partial (~70% verbatim) | Retention, training use, ZDR, Covered Models |
| S-087 | AWS — Bedrock data protection and data retention | 1 | https://docs.aws.amazon.com/bedrock/latest/userguide/data-retention.html | V-page | Retention modes, provider access |
| S-088 | AWS — Bedrock VPC endpoints / encryption | 1 | https://docs.aws.amazon.com/bedrock/latest/userguide/usingVPC.html | V-page | PrivateLink applicability (inference not named) |
| S-089 | Google Cloud — Data governance / zero data retention (Vertex AI, now "Gemini Enterprise Agent Platform") | 1 | https://docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance | V-page | Training-use statement, caching, ZDR actions |
| S-090 | Ollama — API, structured outputs, tool calling docs | 1 | https://docs.ollama.com/api | V-page | Local serving, `format` JSON schema, tools, OpenAI-compatible base URL |
| S-091 | vLLM — OpenAI-compatible server / online serving | 1 | https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/ | V-page | Endpoints, structured outputs, `--api-key` limits, security warnings |
| S-092 | Docker blog, "Why MicroVMs: The Architecture Behind Docker Sandboxes" (vendor blog, 2026-04-16) | 2 | https://www.docker.com/blog/why-microvms-the-architecture-behind-docker-sandboxes/ | V-page (vendor marketing; model-extracted) | Vendor claims: microVM per session, private daemon, no socket mounting |
| S-093 | Docker Sandboxes docs: overview, architecture, security, install, FAQ, get-started | 1 (vendor docs) | https://docs.docker.com/ai/sandboxes/ (and /architecture/, /security/, /install/, /faq/, /get-started/) | V-page (model-extracted) | Isolation model, host requirements, policy/network/credential handling, limits |
| S-094 | Docker Sandboxes API landing page | 1 (vendor docs) | https://docs.docker.com/ai/sandboxes-api/ | V-partial (landing only; REST reference and SDK not read) | Cloud sandbox API requires a subscription |
| S-095 | Freestyle docs: "Run Docker in a sandbox"; VMs overview | 1 (vendor docs) | https://www.freestyle.sh/docs/guides/run-docker-in-a-sandbox | V-page (model-extracted) | Docker Engine and Compose inside Freestyle microVMs; SDK |
| S-096 | Freestyle VMs product page | 3 (marketing) | https://www.freestyle.sh/products/vms | V-page | Scale and capability claims only |
| S-097 | OPA — WebAssembly | 1 | https://www.openpolicyagent.org/docs/wasm | V-page | Compile to Wasm, built-in limits, undefined-decision handling |
| S-098 | OPA — REST API | 1 | https://www.openpolicyagent.org/docs/rest-api | V-partial (Data API verbatim; Health API via summary) | Undefined decision returns 200 without `result` |
| S-099 | OPA — Bundles | 1 | https://www.openpolicyagent.org/docs/management-bundles | V-partial (~first 39k chars) | Bundle activation, persistence, signing |
| S-100 | OPA ecosystem/Python integration (search results: opa-wasm on PyPI, a2d24/python-opa-wasm, opa-wasmtime) | 3 | https://pypi.org/project/opa-wasm/ | V-search | Python Wasm SDKs are community-maintained; maintenance status unverified |
| S-101 | Next.js — Static Exports guide (page dated 2026-08-09) | 1 | https://nextjs.org/docs/app/guides/static-exports | V-page | `output: 'export'`, supported/unsupported features |
| S-102 | Next.js — Content Security Policy guide (2026-03-20) | 1 | https://nextjs.org/docs/app/guides/content-security-policy | V-page | Nonces need dynamic rendering; SRI experimental |
| S-103 | Next.js — Authentication guide (2026-09-16) | 1 | https://nextjs.org/docs/app/guides/authentication | V-partial (~83% verbatim) | Sessions, server-set cookies, DAL, "defense in depth" |
| S-104 | Next.js — Data Security guide (2026-10-06) | 1 | https://nextjs.org/docs/app/guides/data-security | V-page | Server Actions reachable by direct POST; client-side trust |
| S-105 | Next.js — Route Handlers reference (2026-04-30) | 1 | https://nextjs.org/docs/app/api-reference/file-conventions/route | V-page | Methods, streaming; no SSE statement |
| S-106 | FastAPI — home | 1 | https://fastapi.tiangolo.com/ | V-page | OpenAPI/JSON Schema standards, Pydantic, async |
| S-107 | FastAPI — Server-Sent Events tutorial | 1 | https://fastapi.tiangolo.com/tutorial/server-sent-events/ | V-page | `EventSourceResponse`, added in FastAPI 0.135.0, keep-alive ping |
| S-108 | FastAPI — Security tutorial | 1 | https://fastapi.tiangolo.com/tutorial/security/ | V-page | Security schemes tooling; HTTPS expected |
| S-109 | Pydantic — JSON Schema concepts | 1 | https://pydantic.dev/docs/validation/latest/concepts/json_schema/ | V-page | JSON Schema 2020-12 / OpenAPI 3.1 compliance |
| S-110 | Pydantic — Strict mode | 1 | https://pydantic.dev/docs/validation/latest/concepts/strict_mode/ | V-page | Strict vs lax coercion |
| S-111 | openapi-typescript README | 1 | https://github.com/openapi-ts/openapi-typescript | V-page | Runtime-free TS types from OpenAPI 3.0/3.1 |
| S-112 | pip — Secure installs (pip docs v26.2.2) | 1 | https://pip.pypa.io/en/stable/topics/secure-installs/ | V-page | Hash-checking mode |
| S-113 | Python docs — `subprocess` | 1 | https://docs.python.org/3/library/subprocess.html | V-partial (Security Considerations text via extractor) | Argument sequences, `shell=True` caveats |
| S-114 | mypy docs — command line (`--strict`) | 1 | https://mypy.readthedocs.io/en/stable/command_line.html | V-partial (flag list truncated) | Strict type checking |
| S-115 | Bandit documentation | 1 | https://bandit.readthedocs.io/en/latest/ | V-page (overview only; limitations not stated there) | AST-based security linter |
| S-116 | pip-audit (PyPI page, 2.10.1) | 1 | https://pypi.org/project/pip-audit/ | V-page | Dependency vulnerability audit; security model |
| S-117 | PostgreSQL docs — JSON types (PG 18) | 1 | https://www.postgresql.org/docs/current/datatype-json.html | V-page | json vs jsonb, GIN indexing, jsonb input limits |
| S-118 | PostgreSQL docs — Privileges (PG 18) | 1 | https://www.postgresql.org/docs/current/ddl-priv.html | V-page | GRANT/REVOKE; no insert-only recipe stated |
| S-119 | PostgreSQL — Versioning policy | 1 | https://www.postgresql.org/support/versioning/ | V-page | Supported major versions, 5-year support |
| S-120 | SQLAlchemy 2.0 docs and asyncio extension | 1 | https://docs.sqlalchemy.org/en/20/ | V-partial (asyncio page ~11% verbatim) | ORM/Core, async support |
| S-121 | Alembic documentation | 1 | https://alembic.sqlalchemy.org/en/latest/ | V-page | Migration tool for SQLAlchemy |
| — | **Could not be read (fetch blocked or HTTP 403):** two Stack Overflow questions, three Medium posts, vmheaven.io post. No claim is drawn from them. | — | — | — | — |

**To fetch next (not yet read):** Google SRE Book chapters on incident management, postmortems, and "Embracing Risk"; SRE Workbook "Implementing SLOs"; Loki docs (S-011 in full); Kubernetes probe page re-check; Alertmanager configuration reference; Prometheus HA/long-term storage.

**Known source discrepancies**

- SD-01: In S-003 the prose Prometheus example includes a 24h/2h burn-rate-3 ticket rule that is absent from the chapter's recommended-values table (3d/6h, burn rate 1). Not reconciled by the source.
- SD-02: S-002 states the monitoring ideas are "still aspirational".
