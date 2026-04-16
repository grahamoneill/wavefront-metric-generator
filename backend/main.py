"""
Wavefront Synthetic Data Generator & Dashboard Scanner — FastAPI backend.
"""

import re
import json
import math
import time
import random
import socket
import logging
import itertools

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Wavefront Synthetic API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATCH_SIZE          = 1000
REQUEST_TIMEOUT     = 30
INTERVAL_SECONDS    = 60      # one data point per minute
DIRECT_INGEST_LIMIT = 50_000  # hard cap — direct ingestion only
PROXY_PAUSE_EVERY   = 50_000  # pause 1s per N points when using proxy

# ---------------------------------------------------------------------------
# WQL parsing
# ---------------------------------------------------------------------------

# Match quoted:   ts("metric.name", filters...)
# Match histogram: hs("metric.name", filters...)
_TS_RE = re.compile(r'(?:ts|hs)\s*\(\s*"([^"]+)"(?:\s*,\s*([^)]*))?\)')

# Match unquoted: ts(metric.name, ...) or ts(metric.name AND ...)
_TS_UNQUOTED_RE = re.compile(
    r'(?:ts|hs)\s*\(\s*([a-zA-Z][a-zA-Z0-9_.]+)\s*(?:[,)\s]|AND|and)'
)

# Match tag filters: key="value" or key=${var}
_TAG_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\$\{?(\w+)\}?([*]?))')

_WILDCARD   = set('*?[]')
SOURCE_TAGS = {'source', 'host', 'hostname', 'server'}


def _parse_wql_query(query: str, seen: dict) -> None:
    """
    Parse a WQL query string and populate `seen` with metric entries.

    Handles:
    - Quoted:   ts("metric.name", tag="value" and source="${var}")
    - Unquoted: ts(metric.name, source=${var} AND tag="value")
    - Histograms: hs("metric.name", ...)
    - Regex filters: key=/regex/ → treated as variable tag
    - OR groups: (key="a" OR key="b") → separate entries per value
    - NOT filters: stripped before tag extraction
    """
    # Collect (metric_name, filter_string) pairs from both quoted and unquoted forms
    matches: list[tuple[str, str]] = []

    for m in _TS_RE.finditer(query):
        metric   = m.group(1).strip()
        tags_str = m.group(2) or ""
        if metric:
            matches.append((metric, tags_str))

    for m in _TS_UNQUOTED_RE.finditer(query):
        metric = m.group(1).strip()
        if not metric or any(metric == cap[0] for cap in matches):
            continue
        # Extract everything between the opening ( and its matching )
        start       = m.start()
        paren_start = query.index("(", start)
        depth = 0
        paren_end = paren_start
        for i, ch in enumerate(query[paren_start:], paren_start):
            if ch == "(":   depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    paren_end = i
                    break
        inner    = query[paren_start + 1: paren_end]
        tags_str = inner[len(metric):].lstrip(" ,")
        matches.append((metric, tags_str))

    for metric, tags_str in matches:
        if not metric or any(c in metric for c in _WILDCARD) or "${" in metric:
            continue
        # Must look like a real metric name (contains dot or underscore)
        if "." not in metric and "_" not in metric:
            continue

        literal_tags:  dict = {}
        variable_tags: list = []
        use_source          = False

        # Strip NOT filters before processing
        clean = re.sub(r'AND\s+NOT\s*\([^)]+\)?', '', tags_str)
        clean = re.sub(r'NOT\s*\([^)]+\)?',       '', clean)
        clean = re.sub(r'AND\s+NOT\s+\w+="[^"]*"','', clean)
        clean = re.sub(r'NOT\s+\w+="[^"]*"',      '', clean).strip()

        # Detect OR expansion groups: (key="a" OR key="b")
        or_expansions: dict = {}
        for orm in re.finditer(r'\((\w+)="[^"]*"(?:\s+OR\s+\1="[^"]*")+\)?', clean):
            or_key = orm.group(1)
            vals   = re.findall(r'%s="([^"]*)"' % re.escape(or_key), orm.group(0))
            if vals:
                or_expansions[or_key] = vals

        # Detect regex filters: key=/regex/ → variable tag
        for rm in re.finditer(r'(\w+)\s*=\s*/[^/]+/', clean):
            rkey = rm.group(1)
            if rkey.lower() in SOURCE_TAGS or rkey == "source":
                use_source = True
            elif rkey not in variable_tags and rkey not in or_expansions:
                variable_tags.append(rkey)

        # Extract key="value" and key=${var} filters
        for tm in _TAG_RE.finditer(clean):
            key        = tm.group(1)
            quoted_val = tm.group(2)
            var_name   = tm.group(3)
            is_var     = var_name is not None

            if key.lower() in SOURCE_TAGS or key == "source":
                if is_var or (quoted_val and re.search(r'\$\{?\w+\}?', quoted_val)):
                    use_source = True
                continue
            if key in or_expansions or key in variable_tags:
                continue
            if is_var:
                variable_tags.append(key)
            elif quoted_val:
                if quoted_val == '*':
                    if key not in variable_tags:
                        variable_tags.append(key)
                elif re.search(r'\$\{?\w+\}?', quoted_val):
                    # Quoted value is a variable reference e.g. "${instance}"
                    if key not in variable_tags:
                        variable_tags.append(key)
                else:
                    literal_tags[key] = quoted_val

        var_sig = ','.join(sorted(variable_tags))

        if or_expansions:
            or_keys = sorted(or_expansions.keys())
            or_vals = [or_expansions[k] for k in or_keys]
            for combo in itertools.product(*or_vals):
                combo_tags = dict(literal_tags)
                for k, v in zip(or_keys, combo):
                    combo_tags[k] = v
                lit_sig   = ','.join(f'{k}={v}' for k, v in sorted(combo_tags.items()))
                dedup_key = f"{metric}|{lit_sig}|{var_sig}"
                if dedup_key not in seen:
                    seen[dedup_key] = {
                        "name":         metric,
                        "literalTags":  combo_tags,
                        "variableTags": variable_tags,
                        "useSource":    use_source,
                    }
        else:
            lit_sig   = ','.join(f'{k}={v}' for k, v in sorted(literal_tags.items()))
            dedup_key = f"{metric}|{lit_sig}|{var_sig}"
            if dedup_key not in seen:
                seen[dedup_key] = {
                    "name":         metric,
                    "literalTags":  literal_tags,
                    "variableTags": variable_tags,
                    "useSource":    use_source,
                }
            elif use_source:
                seen[dedup_key]["useSource"] = True


def _format_shape(entry: dict) -> str:
    """
    Format a metric entry as a WQL-style display string, e.g.:
      tas.rep.ContainerCount, source="${source}" and job="${job}" and task="login"
    """
    parts = []
    if entry.get("useSource"):
        parts.append('source="${source}"')
    for vt in sorted(entry.get("variableTags", [])):
        parts.append(f'{vt}="${{{vt}}}"')
    for k, v in sorted(entry.get("literalTags", {}).items()):
        parts.append(f'{k}="{v}"')
    name = entry["name"]
    return f"{name}, {' and '.join(parts)}" if parts else name


def _get_source_query(src: dict) -> str:
    """
    Extract the WQL query from a chart source dict.

    When querybuilderEnabled=True the `query` field is often empty and the
    metric lives in `querybuilderSerialization` (a JSON blob). We try the
    raw query first, then reconstruct from the builder JSON.
    """
    q = (src.get("query") or "").strip()
    if q:
        return q

    qbs = src.get("querybuilderSerialization") or ""
    if not qbs:
        return ""
    try:
        obj    = json.loads(qbs) if isinstance(qbs, str) else qbs
        metric = (obj.get("metric") or "").strip()
        if not metric:
            return ""

        # Build filter string from [[key, op, val], ...] structure
        filter_parts = []
        raw_filters  = obj.get("filters", [])
        inner        = raw_filters[0] if raw_filters and isinstance(raw_filters[0], list) else raw_filters
        for f in inner:
            if isinstance(f, list) and len(f) >= 3:
                fkey, fop, fval = f[0], f[1], str(f[2])
                is_var = fval.startswith("${") or fval.startswith("$")
                if fop in ("=~", "!=~") or is_var:
                    filter_parts.append(f'{fkey}=${{{fkey}}}')   # unquoted → variable
                elif fop in ("=", "!="):
                    filter_parts.append(f'{fkey}="{fval}"')

        filter_str = ", ".join(filter_parts)
        return f'ts("{metric}", {filter_str})' if filter_str else f'ts("{metric}")'
    except Exception as e:
        logger.debug("querybuilderSerialization parse failed: %s", e)
        return ""


def extract_metrics_from_dashboard(dashboard: dict) -> tuple[list[str], list[dict]]:
    """
    Walk all chart sources in a Wavefront dashboard JSON and extract metrics.

    Returns:
        shapes:  sorted list of display strings e.g.
                   'tas.rep.ContainerCount, source="${source}" and job="diego_cell"'
        entries: structured dicts with name, literalTags, variableTags, useSource
    """
    seen: dict = {}

    # Pass 1 — chart queries (skip disabled intermediate sources)
    for section in dashboard.get("sections", []):
        for row in section.get("rows", []):
            for chart in row.get("charts", []):
                for src in chart.get("sources", []):
                    if src.get("disabled", False):
                        continue
                    q = _get_source_query(src)
                    if q:
                        _parse_wql_query(q, seen)

    # Pass 2 — parameterDetails: queryValue metrics populate variable dropdowns
    for var_name, param in dashboard.get("parameterDetails", {}).items():
        if param.get("parameterType", "DYNAMIC") != "DYNAMIC":
            continue
        qv = (param.get("queryValue") or "").strip()
        if qv:
            _parse_wql_query(qv, seen)
        # Ensure the variable's tagKey appears on the relevant metric entries
        tag_key = param.get("tagKey")
        if tag_key:
            m = _TS_RE.search(qv)
            qv_metric = m.group(1).strip() if m else ""
            for entry in seen.values():
                if (entry["name"] == qv_metric
                        and tag_key not in entry["variableTags"]
                        and tag_key not in entry["literalTags"]):
                    entry["variableTags"].append(tag_key)

    shapes:  list[str]  = []
    entries: list[dict] = []
    seen_shapes: set    = set()

    for entry in seen.values():
        name = entry.get("name", "").strip()
        if not name or ("." not in name and "_" not in name):
            continue
        s = _format_shape(entry)
        if s not in seen_shapes:
            seen_shapes.add(s)
            shapes.append(s)
            entries.append({
                "name":         name,
                "shape":        s,
                "literalTags":  entry.get("literalTags", {}),
                "variableTags": entry.get("variableTags", []),
                "useSource":    entry.get("useSource", False),
            })

    paired  = sorted(zip(shapes, entries), key=lambda x: x[0])
    shapes  = [p[0] for p in paired]
    entries = [p[1] for p in paired]
    return shapes, entries


# ---------------------------------------------------------------------------
# Synthetic value generation
# ---------------------------------------------------------------------------

def _base_value(metric_name: str) -> tuple[float, float, float]:
    """Return (base, min, max) appropriate for the metric name."""
    name = metric_name.lower()
    if "uptime" in name:
        return (random.uniform(7200, 86400), 0, 864000)
    if any(k in name for k in ("error_rate", "drop_rate", "ratio")):
        return (random.uniform(0.01, 0.15), 0.0, 1.0)
    if "utilization" in name or ("cpu" in name and "util" in name):
        return (random.uniform(20, 55), 0, 100)
    if "bytes" in name or "memory" in name:
        return (random.uniform(1e8, 5e8), 0, 2e9)
    if any(k in name for k in ("status", "healthy")):
        return (1.0, 0, 1)
    if name.endswith(".info") or name.endswith("_info"):
        return (1.0, 1, 1)
    if any(k in name for k in ("latency", "duration", "seconds")):
        return (random.uniform(0.05, 0.5), 0, 10)
    if any(k in name for k in ("count", "total", "running", "desired")):
        return (random.uniform(50, 500), 0, 10000)
    return (random.uniform(10, 60), 0, 200)


def _random_walk_series(metric_name: str, n_points: int) -> list[float]:
    """Generate a realistic random-walk series for gauge metrics."""
    base, mn, mx = _base_value(metric_name)
    name = metric_name.lower()
    # Boolean/status metrics — stable with very rare flips
    if any(k in name for k in ("status", "healthy", "info", "enabled")):
        return [1.0 if random.random() > 0.02 else 0.0 for _ in range(n_points)]
    step = (mx - mn) * 0.02
    v    = base
    vals = []
    for _ in range(n_points):
        v += random.gauss(0, step)
        v  = max(mn, min(mx, v))
        vals.append(round(v, 6))
    return vals


def _sanitize_tag(val: str) -> str:
    if any(c in val for c in (' ', '"', '=', ',', '\\', '\n')):
        return '"' + val.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return val


# ---------------------------------------------------------------------------
# Line builder
# ---------------------------------------------------------------------------

def _build_lines(
    metrics:  list[dict],
    sources:  list[str],
    tags:     dict[str, list[str]],
    start_ts: int,
    end_ts:   int,
) -> list[str]:
    lines    = []
    ts_range = list(range(start_ts, end_ts + 1, INTERVAL_SECONDS)) or [end_ts]

    # Build cartesian product of all tag value combinations
    tag_combos: list = [[]]
    for key in sorted(tags.keys()):
        tag_combos = [combo + [(key, val)] for combo in tag_combos for val in tags[key]]

    is_counter_suffix = ("_total", ".total", "_failures_total", "_count_total")

    for metric in metrics:
        name       = metric["name"]
        is_counter = name.lower().endswith(is_counter_suffix)

        for source in sources:
            for combo in tag_combos:
                tag_str = (" " + " ".join(f"{k}={_sanitize_tag(v)}" for k, v in combo)) if combo else ""
                if is_counter:
                    base = _base_value(name)[0]
                    for i, ts in enumerate(ts_range):
                        val = base + max(50, base * 0.1) * i
                        lines.append(f"{name} {val:.6f} {ts} source={source}{tag_str}")
                else:
                    for ts, val in zip(ts_range, _random_walk_series(name, len(ts_range))):
                        lines.append(f"{name} {val:.6f} {ts} source={source}{tag_str}")

    return lines


# ---------------------------------------------------------------------------
# Ingest helpers
# ---------------------------------------------------------------------------

def _post_batch_http(lines: list[str], url: str, headers: dict) -> None:
    resp = requests.post(
        url, data="\n".join(lines).encode("utf-8"),
        headers=headers, timeout=REQUEST_TIMEOUT
    )
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Wavefront returned HTTP {resp.status_code}: {resp.text[:300]}")


def _post_batch_proxy(lines: list[str], host: str, port: int) -> None:
    body = "\n".join(lines) + "\n"
    with socket.create_connection((host, port), timeout=REQUEST_TIMEOUT) as sock:
        sock.sendall(body.encode("utf-8"))


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/test-connection")
async def test_connection(payload: dict):
    """Test connectivity to a Wavefront tenant (direct) or proxy (TCP)."""
    from concurrent.futures import ThreadPoolExecutor

    mode = (payload.get("ingestion") or "proxy").lower()

    if mode == "direct":
        tenant = (payload.get("tenant") or "").strip().rstrip("/")
        token  = (payload.get("token") or "").strip()
        if not tenant: return {"ok": False, "message": "No tenant URL provided"}
        if not token:  return {"ok": False, "message": "No API token provided"}
        if not tenant.startswith("http"):
            tenant = f"https://{tenant}"
        url     = f"{tenant}/api/v2/dashboard?limit=1"
        headers = {"Authorization": f"Bearer {token}"}
        def _check():
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:  return {"ok": True,  "message": f"Connected to {tenant} — token valid"}
                if resp.status_code == 401:  return {"ok": False, "message": "Authentication failed — check your API token"}
                if resp.status_code == 403:  return {"ok": False, "message": "Permission denied — token lacks read access"}
                return {"ok": False, "message": f"Unexpected response HTTP {resp.status_code}"}
            except requests.exceptions.ConnectionError:
                return {"ok": False, "message": f"Cannot reach {tenant} — check the URL"}
            except requests.exceptions.Timeout:
                return {"ok": False, "message": "Connection timed out"}
        loop = __import__("asyncio").get_event_loop()
        with ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(pool, _check)

    elif mode == "proxy":
        host = (payload.get("proxy_host") or "").strip()
        port = int(payload.get("proxy_port") or 2878)
        if not host: return {"ok": False, "message": "No proxy host provided"}
        def _check():
            try:
                with socket.create_connection((host, port), timeout=5):
                    pass
                return {"ok": True,  "message": f"Proxy reachable at {host}:{port}"}
            except ConnectionRefusedError:
                return {"ok": False, "message": f"Connection refused at {host}:{port} — is the proxy running?"}
            except socket.timeout:
                return {"ok": False, "message": f"Timed out connecting to {host}:{port}"}
            except OSError as e:
                return {"ok": False, "message": f"Cannot reach {host}:{port} — {e}"}
        loop = __import__("asyncio").get_event_loop()
        with ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(pool, _check)

    return {"ok": False, "message": f"Unknown ingestion mode: {mode}"}


@app.post("/api/synthetic")
async def generate_synthetic(payload: dict):
    from concurrent.futures import ThreadPoolExecutor

    # Sources
    sources: list[str] = payload.get("sources") or []
    source_count       = int(payload.get("source_count") or 0)
    if not sources and source_count > 0:
        sources = [f"synthetic-source-{random.randint(1000, 9999)}" for _ in range(source_count)]
    if not sources:
        return {"error": "Provide 'sources' list or 'source_count'"}

    # Metrics
    metrics: list[dict] = payload.get("metrics") or []
    if not metrics:
        return {"error": "Provide at least one metric"}

    # Tags
    raw_tags: dict        = payload.get("tags") or {}
    tags: dict[str, list] = {}
    for key, val in raw_tags.items():
        if key.endswith("_count"):
            tag_key       = key[: -len("_count")]
            tags[tag_key] = [f"synthetic-{tag_key}-{random.randint(100, 999)}" for _ in range(int(val))]
        elif isinstance(val, list):
            tags[key] = val

    # Time window
    end_ts   = int(payload.get("end_ts") or time.time())
    start_ts = int(payload.get("start_ts") or 0)
    if not start_ts:
        start_ts = end_ts - int(float(payload.get("backfill_hours") or 1) * 3600)

    # Ingestion mode
    mode = (payload.get("ingestion") or "direct").lower()
    if mode == "direct":
        tenant = (payload.get("tenant") or "").strip().rstrip("/")
        token  = (payload.get("token") or "").strip()
        if not tenant: return {"error": "Missing 'tenant'"}
        if not token:  return {"error": "Missing 'token'"}
        if not tenant.startswith("http"):
            tenant = f"https://{tenant}"
        url     = f"{tenant}/report?f=wavefront"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "text/plain; charset=utf-8"}
    elif mode == "proxy":
        proxy_host = (payload.get("proxy_host") or "").strip()
        proxy_port = int(payload.get("proxy_port") or 2878)
        if not proxy_host: return {"error": "Missing 'proxy_host'"}
    else:
        return {"error": f"Unknown ingestion mode '{mode}'"}

    all_lines    = _build_lines(metrics, sources, tags, start_ts, end_ts)
    total_points = len(all_lines)

    if not all_lines:
        return {"error": "No data points generated"}

    if mode == "direct" and total_points > DIRECT_INGEST_LIMIT:
        return {
            "error": (
                f"Direct ingestion is capped at {DIRECT_INGEST_LIMIT:,} points. "
                f"Your configuration would generate {total_points:,} points. "
                f"Reduce metrics, sources, tags, or backfill window — or switch to proxy ingestion."
            ),
            "points_would_send": total_points,
            "limit": DIRECT_INGEST_LIMIT,
        }

    points_sent = batches = skipped = 0

    def _send():
        import time as _t
        nonlocal points_sent, batches, skipped
        for i in range(0, len(all_lines), BATCH_SIZE):
            batch = all_lines[i: i + BATCH_SIZE]
            try:
                if mode == "direct":
                    _post_batch_http(batch, url, headers)
                else:
                    _post_batch_proxy(batch, proxy_host, proxy_port)
                points_sent += len(batch)
                batches     += 1
                # Pace proxy ingestion for large volumes
                if mode == "proxy" and points_sent % PROXY_PAUSE_EVERY < BATCH_SIZE and points_sent > 0:
                    logger.info("Proxy pause after %d points", points_sent)
                    _t.sleep(1.0)
            except Exception as exc:
                skipped += len(batch)
                logger.error("Batch %d failed: %s", batches + 1, exc)
                raise

    loop = __import__("asyncio").get_event_loop()
    try:
        with ThreadPoolExecutor() as pool:
            await loop.run_in_executor(pool, _send)
    except Exception as exc:
        return {"error": str(exc)}

    return {
        "points_sent":        points_sent,
        "points_skipped":     skipped,
        "batches":            batches,
        "metrics":            len(metrics),
        "sources":            len(sources),
        "tag_combos":         max(1, math.prod(len(v) for v in tags.values()) if tags else 1),
        "time_range_hours":   round((end_ts - start_ts) / 3600, 2),
        "total_points_built": total_points,
    }


@app.post("/api/synthetic/estimate")
async def estimate_synthetic(payload: dict):
    sources: list[str] = payload.get("sources") or []
    source_count       = int(payload.get("source_count") or 0)
    num_sources        = len(sources) if sources else source_count

    metrics: list[dict] = payload.get("metrics") or []

    raw_tags: dict = payload.get("tags") or {}
    tag_counts     = []
    for key, val in raw_tags.items():
        if key.endswith("_count"):
            tag_counts.append(int(val))
        elif isinstance(val, list):
            tag_counts.append(len(val))

    tag_combos = math.prod(tag_counts) if tag_counts else 1

    end_ts   = int(payload.get("end_ts") or time.time())
    start_ts = int(payload.get("start_ts") or 0)
    if not start_ts:
        start_ts = end_ts - int(float(payload.get("backfill_hours") or 1) * 3600)

    points_per_series = max(1, (end_ts - start_ts) // INTERVAL_SECONDS)
    series_total      = len(metrics) * num_sources * tag_combos
    points_total      = series_total * points_per_series

    return {
        "metrics":                 len(metrics),
        "sources":                 num_sources,
        "tag_combos":              tag_combos,
        "series_total":            series_total,
        "points_per_series":       points_per_series,
        "points_total":            points_total,
        "time_range_hours":        round((end_ts - start_ts) / 3600, 2),
        "interval_seconds":        INTERVAL_SECONDS,
        "direct_limit":            DIRECT_INGEST_LIMIT,
        "exceeds_direct_limit":    points_total > DIRECT_INGEST_LIMIT,
        "exceeds_proxy_threshold": points_total > PROXY_PAUSE_EVERY,
    }


@app.post("/api/dashboard/scan")
async def scan_dashboard(payload: dict):
    """
    Fetch a Wavefront dashboard by URL slug and extract all metrics with tag shapes.
    Always uses direct HTTPS + Bearer token (dashboard API doesn't go via proxy).
    """
    from concurrent.futures import ThreadPoolExecutor

    tenant = (payload.get("tenant") or "").strip().rstrip("/")
    token  = (payload.get("token") or "").strip()
    slug   = (payload.get("dashboard_slug") or "").strip()

    if not tenant: return {"error": "Missing 'tenant'"}
    if not token:  return {"error": "Missing 'token'"}
    if not slug:   return {"error": "Missing 'dashboard_slug'"}

    if not tenant.startswith("http"):
        tenant = f"https://{tenant}"

    url     = f"{tenant}/api/v2/dashboard/{slug}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _fetch():
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 401: raise RuntimeError("Authentication failed — check your API token")
        if resp.status_code == 403: raise RuntimeError("Permission denied — token lacks read access")
        if resp.status_code == 404: raise RuntimeError(f"Dashboard '{slug}' not found on {tenant}")
        if resp.status_code != 200: raise RuntimeError(f"API returned HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        # Wavefront wraps the dashboard in a "response" envelope
        return body["response"] if isinstance(body, dict) and "response" in body else body

    loop = __import__("asyncio").get_event_loop()
    try:
        with ThreadPoolExecutor() as pool:
            dashboard = await loop.run_in_executor(pool, _fetch)
    except RuntimeError as exc:
        return {"error": str(exc)}
    except requests.exceptions.ConnectionError:
        return {"error": f"Cannot connect to '{tenant}' — check the tenant URL"}
    except requests.exceptions.Timeout:
        return {"error": "Request timed out"}
    except Exception as exc:
        return {"error": f"Unexpected error: {str(exc)}"}

    shapes, entries = extract_metrics_from_dashboard(dashboard)

    return {
        "dashboard_name": dashboard.get("name", slug),
        "dashboard_slug": slug,
        "metrics_found":  len(shapes),
        "metrics":        shapes,
        "entries":        entries,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
