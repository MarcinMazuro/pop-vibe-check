"""Replay publisher for the pop-vibe-check data-source simulation.

Loads the GCS raw archive into BigQuery staging (landing table + dedup
MERGE) and replays the staged records to Pub/Sub in global chronological
order with time compression, simulating a live stream for the downstream
Dataflow pipeline.
"""
