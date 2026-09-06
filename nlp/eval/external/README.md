# External baselines

Hand-collected reference series for the thesis chapter that sits *next
to* the gold-set metrics, not inside Beam.

Nothing here is scraped automatically. Fill the CSVs by hand from the
public pages, then join them in a notebook / Looker against the
`time_windows.sql` aggregates (mean polarity per window vs critic score
vs Steam players).

| File | What to put there |
|---|---|
| `metacritic.csv` | Metacritic metascore + user score, with the date you captured them and a URL. |
| `opencritic.csv` | OpenCritic top critic / percent recommended, same idea. |
| `steam_charts.csv` | Daily (or hourly around launch) player counts from Steam Charts / Steam Spy. |

`date_utc` is the observation date, not the game's launch date.
Launch itself is `2025-04-24` (`collectors/config/events.yaml`).

Steam collector data from Oskar can replace or extend `steam_charts.csv`
once those rows exist; this folder is the fallback so gold-YouTube eval
is not blocked on that collector.

Do not commit a full scrape dump — keep these files small (dozens of
rows). The headers and one commented example row document the schema.
