# NLP evaluation

Outline for the DistilBERT chapter. Numbers land here after the gold set
is labelled and the first Vertex replay is promoted into `events`.

## 1. Gold set (~300)

- Draw candidates: `nlp/eval/sql/sample_gold.sql` or
  `python -m nlp.eval.sample_gold`.
- Label with `nlp/eval/GUIDELINES.md` (`pos` / `neu` / `neg`).
- Hold out ≥ 80 rows from fine-tuning (`split=holdout`).
- Score a predictions file:

```bash
python -m nlp.eval.evaluate --gold gold.jsonl --pred pred.jsonl --output report.json
```

Report: accuracy, macro-F1, per-class precision/recall/F1, confusion
matrix, then the same sliced by `language` and `source`.

English DistilBERT on FR/ZH/RU/KO is a **measured limit**, not a quality
target. Put those per-language rows in the thesis table as-is.

## 2. Time windows (SQL on `events`)

`nlp/eval/sql/time_windows.sql` — launch `2025-04-24`:

| Window | Interval (UTC, half-open) |
|---|---|
| week before | [launch − 7d, launch) |
| launch day | [launch, launch + 1d) |
| 48 hours | [launch, launch + 48h) |
| week after | [launch, launch + 7d) |

Also group by `event_tag` from `collectors/config/events.yaml` so the
calendar (reveal, trailer, demo, controversy, TGA) is visible next to
the launch spike.

Run only after `dataflow/promote.sh` has merged `events_landing` →
`events`.

## 3. External baselines

Hand-filled CSVs in `nlp/eval/external/`:

- Metacritic metascore / user score
- OpenCritic top critic / percent recommended
- Steam Charts (or Steam Spy) player counts

Join on `date_utc` against the window aggregates (mean polarity vs
critic score vs CCU). Steam collector rows can replace the Charts CSV
later; they do not block YouTube gold.

## 4. Looker (C4, after the first MERGE)

Authorized views over `events` in `terraform/modules/bigquery` — **not
in this change**. Wait until `model_version` on real rows is a Vertex
id (`vertex/…`), not `stub/1`.

## 5. Reproducibility

The gold JSONL, the evaluate report, and the SQL outputs are the
artifacts. Model weights live in MLflow (`gs://co-tf-artifacts-dev/nlp/mlruns`)
and Vertex Model Registry; they are not copied into the Dataflow image.
