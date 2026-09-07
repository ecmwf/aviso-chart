# aviso-chart

Helm chart for [`aviso-server`](https://github.com/ecmwf/aviso-server), ECMWF's streaming notification service. Publishes to `oci://eccr.ecmwf.int/aviso/aviso-chart`.

## Quick start

```bash
helm install aviso oci://eccr.ecmwf.int/aviso/aviso-chart \
  --version 0.7.4 \
  --namespace aviso \
  --create-namespace
```

The base chart ships a working in-memory `aviso-server` with no ingress, no auth, no metrics, and no bundled subcharts. Enable each feature explicitly via values overrides.

Curated example profiles live under [`examples/`](examples):

| File | Profile |
|---|---|
| `values-inmemory-minimal.yaml` | Smallest possible deployment for local/dev. |
| `values-jetstream-external.yaml` | Use a NATS JetStream cluster already running outside this release. |
| `values-jetstream-internal-nats.yaml` | Enable the bundled official NATS subchart for local/dev JetStream. |
| `values-resource-annotations.yaml` | Apply log-pipeline annotations on aviso, NATS, and auth-o-tron resources. |
| `values-auth-enabled.yaml` | Enable auth-o-tron, JWT auth, metrics, ServiceMonitor. |
| `values-ecpds-enabled.yaml` | Enable the ECPDS destination-authorization plugin. |

## Feature toggles

All operator-facing knobs are documented inline in [`values.yaml`](values.yaml). The high-level surfaces:

### Ingress streaming tuning

`aviso-server`'s watch endpoint keeps SSE connections open for up to `config.watch_endpoint.connection_max_duration_sec` (default `3600s`). The chart's `ingress.streamingTuning` block emits the right proxy-buffering / read-timeout / send-timeout annotations for the chosen controller so SSE clients are not dropped mid-stream:

```yaml
ingress:
  streamingTuning:
    enabled: true
    controller: "nginx-org"      # or "ingress-nginx", or "" to disable auto-emit
    proxyBuffering: false
    proxyReadTimeoutSeconds: 3600
    proxySendTimeoutSeconds: 3600
```

Entries in `ingress.annotations` always win on key collision.

### Historical replay limits

`config.watch_endpoint.max_historical_notifications` defaults to `10000` and caps historical notifications delivered after filtering and rendering. A schema can set a positive `config.notification_schema.<event>.max_historical_notifications` to override it; omission inherits the global default. This key belongs outside `storage_policy`, which controls retention, not replay delivery. `config.watch_endpoint.replay_batch_size` defaults to `100` and controls global internal fetch batches, not the delivered cap. Both settings must be positive integers; `0` is not an unlimited mode.

If one more matching notification exists beyond the cap, the server emits `notification_replay_limit_reached` with `max_allowed`, then closes without `replay_completed` or switching to live delivery. Exhausting history at exactly the cap completes normally. See the commented schema override in [`values.yaml`](values.yaml).

### Auth (bundled auth-o-tron)

```yaml
auth-o-tron:
  enabled: true

extraEnv:
  - name: AVISOSERVER_AUTH__JWT_SECRET
    valueFrom:
      secretKeyRef:
        name: aviso-auth-secret
        key: jwt-secret

config:
  auth:
    enabled: true
    mode: direct
    auth_o_tron_url: "http://RELEASE_NAME-auth-o-tron:8080"
    admin_roles: { localrealm: ["admin"] }
```

The chart can provision `aviso-auth-secret` from values via `authSecret.enabled: true` (handy for test environments); for anywhere else, create the Secret out of band. See [`examples/values-auth-enabled.yaml`](examples/values-auth-enabled.yaml).

### Prometheus metrics

The server-side endpoint lives under `config.metrics`; the Kubernetes plumbing (Service port + ServiceMonitor) lives at the top-level `metrics` key. Both are needed:

```yaml
config:
  metrics:
    enabled: true
    host: "0.0.0.0"
    port: 9090

metrics:
  serviceMonitor:
    enabled: true
    interval: 30s
    labels: { release: prometheus }
```

`config.metrics.host` defaults to `"0.0.0.0"` (server-side default is `127.0.0.1`, which would silently break in-cluster scraping).

### Grafana dashboard

This repo version-controls a ready-made dashboard at [`dashboards/aviso-server.json`](dashboards/aviso-server.json): an on-call overview row (scrape health, pods by version, traffic, 5xx ratio, p99, active SSE), a capacity/bottleneck row (per-pod request rate and p99, HTTP in-flight by method, backend operation latency/error ratio), API RED panels, notifications and SSE delivery, auth/ECPDS, per-pod runtime panels, and a collapsed cluster row (HPA replicas, CPU throttling, memory-vs-limit — requires kube-state-metrics/cAdvisor), with deploy annotations driven by `aviso_build_info`. It is not deployed by the chart: import the JSON into Grafana manually (Dashboards > Import). Panels bind to `datasource`/`namespace`/`job` template variables, so one import serves multiple aviso environments scraped by the same Prometheus. Metric labels use `route` (not `endpoint`) to avoid colliding with the Prometheus Operator target label `endpoint`. The JSON passes [`grafana/dashboard-linter`](https://github.com/grafana/dashboard-linter) with the reasoned exclusions in [`dashboards/.lint`](dashboards/.lint); update it in lockstep with metric changes in new `appVersion`s.

A companion NATS/JetStream dashboard lives at [`dashboards/nats-jetstream.json`](dashboards/nats-jetstream.json) (server, stream, consumer, JetStream API in-flight/errors and storage panels, plus a Resources & Storage row). It is adapted from the [official `nats-io/prometheus-nats-exporter` JetStream dashboard](https://github.com/nats-io/prometheus-nats-exporter/blob/main/walkthrough/grafana-jetstream-dash-helm.json): the upstream export ships with a `${DS__NATS-PROMETHEUS}` `__inputs` datasource constant that does not rebind on import into recent Grafana (variables silently return nothing, and panels — which carry no datasource of their own — fall back to the default datasource and show no data). This copy replaces it with a standard `datasource` template variable and binds every panel/target to it. It adds a `namespace` template variable (queries scoped by `namespace=~"$namespace"`) so one import serves multiple environments. It expects the `nats_` metric prefix (set `nats.promExporter` with `-prefix=nats`, `-jsz=all` in the NATS subchart) — *not* the `gnatsd_` prefix or nats-surveyor naming that most grafana.com NATS dashboards target. The `consumer` variable and consumer panels populate only while consumers exist; aviso uses ephemeral consumers, so they are empty unless a `watch`/`replay` stream is active. The JetStream memory panels were removed because this deployment uses file storage only (`max_memory=0`); the Resources & Storage row (PVC used vs capacity, CPU/memory vs limit, CPU throttling, network I/O, restarts) is sourced from kube-state-metrics, cAdvisor, and kubelet volume stats, scoped to `pod=~"aviso-nats.*"`.

### ECPDS destination-authorization plugin

Opt-in per stream via `auth.plugins: ["ecpds"]` in the schema. Plugin-wide settings (servers, cache, timeouts) live under `config.ecpds`. Credentials are HTTP Basic auth against the ECPDS API. Never put them in the values file; inject them via `extraEnv` from a Kubernetes Secret:

```yaml
extraEnv:
  - name: AVISOSERVER_ECPDS__USERNAME
    valueFrom: { secretKeyRef: { name: aviso-ecpds-secret, key: username } }
  - name: AVISOSERVER_ECPDS__PASSWORD
    valueFrom: { secretKeyRef: { name: aviso-ecpds-secret, key: password } }

config:
  ecpds:
    servers:
      - "https://ecpds-primary.example.int"
    match_key: "destination"
    target_field: "name"
    cache_ttl_seconds: 300
    partial_outage_policy: strict   # or any_success
```

See [`examples/values-ecpds-enabled.yaml`](examples/values-ecpds-enabled.yaml) and the [ECPDS authorization docs](https://github.com/ecmwf/aviso-server/blob/main/docs/src/authentication.md#ecpds-destination-authorization).

### Strict schema enforcement (server 0.6.0+)

`aviso-server` `0.6.0` rejects any `event_type` that is not declared in `config.notification_schema` with `400 UNKNOWN_EVENT_TYPE` on `/notification`, `/watch`, and `/replay`. This is the **default behavior** whenever the schema contains at least one entry; no opt-in is required.

The behavior is controlled by `config.notification_schema_strict`:

| `config.notification_schema` | `config.notification_schema_strict` | Effective behavior |
|---|---|---|
| non-empty               | unset           | **strict**: unknown event types rejected |
| empty / absent          | unset           | permissive generic fallback (dev convenience) |
| any                     | `true`          | strict: with no schema this is deny-all |
| any                     | `false`         | permissive generic fallback (legacy mode; server emits a startup warning when the schema is non-empty) |

The error body lists the allowed event types so callers can self-correct:

```json
{
  "code": "UNKNOWN_EVENT_TYPE",
  "error": "unknown_event_type",
  "message": "unknown event type 'X'",
  "configured_event_types": ["dissemination", "mars", "test_polygon"],
  "request_id": "<uuid>"
}
```

The field is silently ignored by older server versions (`<= 0.5.x`); it is safe to set it in shared overlays.

## Image flavors

The published image normally ships in two flavors:

| Tag | Build |
|---|---|
| `<version>` | core (`notify`, `watch`, `replay`, `auth`, `metrics`) |
| `<version>-ecpds` | core + ECPDS plugin (`--features ecpds`) |

If your operational image is always built with `--features ecpds`, use `<version>` regardless of whether `config.ecpds` is set; otherwise pick `<version>-ecpds` when enabling the plugin.

## Local rendering

```bash
helm repo add nats https://nats-io.github.io/k8s/helm/charts/
helm dependency update .

helm lint .
helm template aviso . --kube-version 1.29
helm template aviso . -f examples/values-auth-enabled.yaml
```

## Related repositories

- [`ecmwf/aviso-server`](https://github.com/ecmwf/aviso-server): server binary, configuration reference, ECPDS runbook.
- [`ecmwf/aviso-config`](https://github.com/ecmwf/aviso-config): production overlays applied on top of this chart.
- [`ecmwf/auth-o-tron-chart`](https://github.com/ecmwf/auth-o-tron-chart): bundled authentication subchart.
