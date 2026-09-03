# External log datasets

LogCouncil does not commit third-party raw datasets to Git. Downloaded files are stored below `data/external/`, which is excluded by `.gitignore`.

## Loghub OpenStack 2k

- Source: <https://github.com/logpai/loghub/tree/master/OpenStack>
- Pinned source revision: `dd61d0952749ee7963bde24220d1be5ede023033`
- Collection environment: OpenStack running on CloudLab with normal and injected-failure cases
- Intended use of this 2,000-line sample: raw text-log parsing, template extraction, and correlation smoke tests
- Boundary: it is controlled experimental data, not a naturally occurring production incident

The 2k repository sample contains parser reference outputs but does not by itself provide incident-level anomaly ground truth. Anomaly evaluation will use the separately published full normal/abnormal OpenStack data after its labeling contract is integrated.

Loghub states that its datasets are freely available for research or academic work and asks users to reference the repository and cite the Loghub paper where applicable. See [`manifests/loghub-openstack-2k.json`](manifests/loghub-openstack-2k.json) for pinned URLs and citations.

Download with:

```powershell
python scripts/download_dataset.py loghub-openstack-2k
```

The download command validates maximum size, SHA-256 when present, and expected line count before accepting an artifact.

## RCAEval RE3-OB logs-only case

The first RCAEval integration uses only `re3ob_cartservice_f1_1/logs.parquet`, its incident anchor, and the small `cases.parquet` ground-truth index. Metrics and traces are intentionally excluded.

- Source: <https://huggingface.co/datasets/phamquiluan/RCAEval>
- Pinned dataset revision: `afeacb11bcc94dadfd1c8f483ee4377b2b8b614e`
- Root-cause label: `cartservice`, fault family `f1`, repetition `1`
- Collection environment: Online Boutique with controlled code-level fault injection
- License: MIT

Download with:

```powershell
python scripts/download_dataset.py rcaeval-re3ob-cartservice-f1-1
```

This is real telemetry collected from a running benchmark system under an injected fault. It is not a naturally occurring production incident. LogCouncil uses the ground truth only for evaluation; Agents receive the log records and incident anchor, never the answer label.

The parquet logs provide a timestamp, container name, and message, but no observed log level. The adapter therefore uses `UNKNOWN`; it does not invent a level from message text. Use `case.analysis` as Agent input. `case.ground_truth` and the label-bearing source case ID are evaluation-only.
