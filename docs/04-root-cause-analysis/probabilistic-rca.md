# Probabilistic and Bayesian RCA

## Abstract

Review of the probabilistic-reasoning sources supplied for the pending RCA gap. The sources are heterogeneous: one survey, two Bayesian anomaly-detection papers on non-microservice data, one benchmark-style repository with self-reported results, and a conceptual paper without results. They support a **design position**, not an accuracy claim.

## Research Findings (RESEARCH FINDING)

### Survey: models and inference cost [S-066, pp. 1–12 read]

- Terminology: an *event* is an exceptional condition; *faults/root causes* cause other events; a *symptom* is an external manifestation (including alarms from anomaly detectors); RCA is also called fault localization, fault isolation or alarm/event correlation. The survey states there is **no consensus on formal definitions of causality and explanation**.
- Dimensions that change the RCA problem: analysis intent (cause only vs. explanation), analysis time (real-time vs. post-mortem), system size, data size, inference length (components to traverse), effect-propagation time, evolution rate, and domain/system knowledge required.
- Model families: deterministic (logic/rule sets, fault trees, codebooks, classifiers, process models) vs. probabilistic (fuzzy/possibilistic logic, Dempster-Shafer, Bayesian networks and variants, sum-product networks, Markov logic, HMMs). Model generation can be manual, assisted, or automated.
- Classifiers (decision trees, neural nets, SVMs) are easy to generate automatically but, per the survey, mostly return only a predicted cause, are hard to explain, hard to combine with domain knowledge, and are suited to single-fault diagnosis; high system evolution rate reduces their usefulness because few labelled instances exist.
- Inference concepts for Bayesian models: marginals, Most Probable Explanation (MPE) and Maximum A Posteriori (MAP). The survey suggests marginals for single-fault diagnosis and MPE/MAP for multiple faults.
- Complexity (stated): general Bayesian-network MPE and MAP are NP-hard; MAP is harder than MPE; learning a Bayesian network is NP-complete; structure-learning algorithms like PC have worst-case exponential cost in neighbourhood size and were historically limited to around a hundred variables, with newer approaches claimed to reach far more. Bipartite (cause→symptom) and naive-Bayes models are much more tractable; the cheapest model class (naive Bayes) assumes independence.
- Approximate/anytime algorithms are the usual response to cost. The survey also says **no single RCA technique dominates**; the trade-off is tractability vs. expressiveness.

### Bayesian anomaly explanation on logs [S-065, full read]

- Setting: error-count logs from company servers (zone, project, procedure, error message), 120+ consecutive days, one real dataset, inference done day by day on past data.
- Method: tree-augmented Bayesian network; Dirichlet-multinomial for counts and Bernoulli naive Bayes over bag-of-words error text. The central idea ("separable" predictive posterior) decomposes a log-likelihood deficiency into per-feature **influences**, so each anomaly is explained by the projects or keywords that lowered the likelihood most.
- Evidence: qualitative case study with plots and tables of explained anomalies (e.g., keywords like "timed out" mapped to procedures). **No quantitative accuracy, precision/recall, or comparison with baselines is reported** in the pages read. The assumption of a diagonal Hessian at the mode (separability) is shown for the base models only.
- Relevance: gives an explainable, cheap way to say *which dimension drove an anomaly*, a candidate for evidence-ranking in log-count features. It does not identify causal direction.

### Uncertainty-aware anomaly detection [S-069, pp. 1–10 of 29]

- BADAC: hierarchical Bayesian classification plus anomaly ranking that marginalizes over measurement uncertainty; tested on **simulated one-dimensional Gaussian-noise curves** (99% inliers, 1% outliers). Claims (abstract) of superiority to standard algorithms, calibrated class probabilities, online new-class detection, and "significantly increased computational cost".
- Introduces the **Rank-Weighted Score (RWS)**: a rank-weighted fraction of true outliers found among the top-N ranked objects, range [0,1]; linearly weights top ranks more. Pages after 10 (experiments' results, approximations, appendices) were not read.
- Relevance: RWS is an evaluation idea for *ranked* output (matching Cloud Doctor's ranked hypotheses); the method itself is not applied to operations telemetry.

### Robust unsupervised anomaly detection [S-067, full read]

IJCAI-21 *Robust Collaborative Autoencoders* (abbreviated "RCA" by the authors — **not root-cause analysis**): two autoencoders exchange low-reconstruction-error samples to avoid memorizing anomalies in contaminated training data; evaluated by AUC on 18 public ODDS benchmark datasets (not operations telemetry) and a missing-value study; requires the user to specify an anomaly ratio (sensitivity tested at ±5% and ±10% in the pages read). Takeaway: training on contaminated "normal" data is a real concern for learned detectors; relevant if Cloud Doctor's baseline period contains hidden faults. Not evidence about RCA.

### Self-reported repository [S-070, repo page only]

A student-style repository applies discrete naive Bayes to RCAEval cases (README-reported: 643 usable of 645 cases; 514/62/67 split; six fault classes; **top-1 70.1%, top-3 100.0% on a 67-case evaluation split**, MRR 0.841). The README itself cautions that top-3 100% is not 100% classification accuracy, that conditional independence is assumed, and that posteriors are not calibrated probabilities. **No licence found; code and results were not inspected or reproduced; the repository's 2 commits and 0 stars suggest low maturity.** Use only as an illustration of how small the approach can be and how self-reported numbers look; do not cite its figures as evidence.

### Conceptual causal-inference paper [S-068, full read]

IJRTI 2025 paper proposing a "CIRCAF" framework (ingest/harmonize, causal graph via PC/NOTEARS/Granger, do-calculus interventions and counterfactuals, continuous learning with reinforcement learning, explainability layer). The text read is a proposal; the abstract mentions experimental validation, but **no experiment design, dataset, metrics or results appear in the text**. It also cites S-021 and S-020 for context. Treated as Tier 3 background; no performance claim is taken from it. Note the tension with S-021: that empirical study found no causal-inference RCA method generalizes reliably, whereas S-068 asserts benefits without evidence.

## Alternatives for Cloud Doctor

| Approach | Strength | Weakness | Fit (HYPOTHESIS) |
|---|---|---|---|
| Naive-Bayes / bipartite cause→symptom model with expert-set priors | Cheap, explainable per-feature contributions, handles missing symptoms by omission (survey: noisy/unknown symptoms handled by probabilistic models) | Independence assumption; needs priors/labels; calibration unverified | **Candidate scorer** alongside rules |
| Likelihood-deficiency decomposition (S-065) | Explains which feature caused an anomaly | Counts-based; no causal direction | Evidence ranking for log-count features |
| Full Bayesian network with learned structure | Expressive | Learning NP-complete; large data; evolving systems | Not justified at ≤ 10 services with known topology |
| Learned anomaly detectors (autoencoders etc.) | No manual thresholds | Training-data contamination [S-067]; tuning; evaluation pitfalls [S-062] | Not planned for prototype; compare only if time allows |

## Design position (DESIGN DECISION, provisional)

1. Keep the deterministic scorer as the baseline. Add an optional **probabilistic ranking** layer: a bipartite/naive-Bayes style model over a small catalogue of causes (redis down, worker crash, CPU, memory, DB connections, network latency, bad deploy), with priors **set from the experiment design and updated only from labelled training runs, kept separate from test scenarios** to avoid leakage.
2. Output per hypothesis: score, **contributing features**, contradicting features. Present scores as rankings, not calibrated probabilities, until calibration is measured (the survey and S-070 both note the distinction).
3. Evaluate ranking with top-k accuracy and a rank-weighted metric in the spirit of RWS; report variance over repeats.
4. Do not ship causal-discovery learning (PC/NOTEARS) in the prototype: cost and instability [S-066, S-021].

## Limitations

- Bayesian sources here come from other domains (logs of one enterprise, astronomy simulations, benchmark tables) or have no results; none validates the approach on microservice telemetry.
- Only partial reads of S-069 and S-066.

## Open questions

- Whether a naive-Bayes scorer beats the rule scorer on EXP-05/09 (ambiguous cases); to measure.
- How to obtain labelled training runs without contaminating the evaluation set (use disjoint seeds and held-out scenarios).

## References

S-021, S-062, S-065–S-070 in `docs/_sources/register.md`.
