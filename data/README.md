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
