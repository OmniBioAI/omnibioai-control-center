"""Usage Analytics v1 (control-center-local, no separate service).

See the package's own modules for the write/read split:
- consumer.py / aggregator.py: Redis Streams ingestion -> daily/hourly
  Redis aggregates. Never replays a stream on a read path.
- prometheus.py / billing_client.py / tes_client.py: read-only clients
  for the other systems analytics reports on, added in a later PR.
- permissions.py / cache.py / service.py / router.py: the HTTP-facing
  layer, added in a later PR once the pipeline above is proven.

Two real, load-bearing gaps in the actual deployed platform shape this
package deliberately, rather than the reverse:
1. No Prometheus server is deployed anywhere in this workspace today
   (every service's own /metrics endpoint exists but nothing scrapes
   it) -- prometheus.py degrades to "unavailable" until one exists.
2. `interactions:events` (omnibioai-auth's InteractionEvent contract)
   has exactly one real producer today, RAG's /v1/query, and carries no
   team_id/duration_ms/request_id -- see schemas.py::normalize_interaction_event.
"""
