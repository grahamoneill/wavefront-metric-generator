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
INTERVAL_SECONDS    = 60
INGEST_HARD_LIMIT   = 50_000
PROXY_PAUSE_EVERY   = 50_000

# ---------------------------------------------------------------------------
# WQL parsing
# ---------------------------------------------------------------------------

# Match: ts("metric", filters...)  or  hs("metric", filters...)
_TS_QUOTED_RE   = re.compile(r'(?:ts|hs)\s*\(\s*"([^"]+)"(?:\s*,\s*([^)]*))?\)')
# Match: ts(metric.name, ...)  or  ts(metric.name AND ...)
_TS_UNQUOTED_RE = re.compile(r'(?:ts|hs)\s*\(\s*([a-zA-Z][a-zA-Z0-9_.]+)\s*(?:[,)\s]|AND|and)')
# Match: key="value"  or  key=${var}
_TAG_RE         = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\$\{?(\w+)\}?)')

_WILDCARD   = set('*?[]')
SOURCE_TAGS = {'source', 'host', 'hostname', 'server'}



def _strip_wildcard(name: str) -> str:
    """cpu.usage.* → cpu.usage,  mem.* → mem,  processes* → processes"""
    return name.rstrip('*?').rstrip('.')


def _has_wildcard(name: str) -> bool:
    return any(c in name for c in _WILDCARD)


def _extract_metric_and_filters(query: str) -> list[tuple[str, str]]:
    """
    Return list of (metric_name, filter_string) pairs from a WQL query string.

    Handles three forms:
      1. ts("metric", filters)                    — standard quoted
      2. ts("metric" and not "other", filters)    — inline AND NOT before comma
      3. ts(metric.name, filters)                 — unquoted metric name
    """
    results: list[tuple[str, str]] = []

    # Form 1 & 2 — look for the opening ts(" and scan to find the metric name,
    # then find the real comma that separates metric from filters.
    for outer in re.finditer(r'(?:ts|hs)\s*\(', query, re.IGNORECASE):
        pos = outer.end()
        if pos >= len(query) or query[pos] != '"':
            continue  # no opening quote → unquoted form, handled below

        # Find the metric name (first quoted string)
        end_quote = query.find('"', pos + 1)
        if end_quote < 0:
            continue
        raw_metric = query[pos + 1: end_quote]

        # Skip wildcard metrics entirely — we cannot infer the real metric names
        # the dashboard expects (e.g. mem.*, cpu.usage.*, processes*)
        # These will be flagged as "wildcard" entries so the user knows to add them manually
        if _has_wildcard(raw_metric):
            continue
        metric = raw_metric
        if not metric or '${' in metric:
            continue
        if '.' not in metric and '_' not in metric:
            continue

        # Now find the comma that separates metric from filters.
        # Skip any "and not ..." clauses that appear before the comma.
        scan = end_quote + 1
        depth = 1  # we're inside the outer ts(
        filters = ""
        while scan < len(query):
            ch = query[scan]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    break
            elif ch == ',' and depth == 1:
                # This comma separates metric expression from filters
                # Find matching ) for the outer ts(
                paren_depth = 1
                fi = scan + 1
                end_fi = fi
                while fi < len(query):
                    if query[fi] == '(':
                        paren_depth += 1
                    elif query[fi] == ')':
                        paren_depth -= 1
                        if paren_depth == 0:
                            end_fi = fi
                            break
                    fi += 1
                filters = query[scan + 1: end_fi].strip()
                break
            scan += 1

        results.append((metric, filters))

    # Form 3 — unquoted metric: ts(metric.name, ...) or ts(metric.name AND ...)
    for m in _TS_UNQUOTED_RE.finditer(query):
        metric = m.group(1).strip()
        if not metric or '${' in metric:
            continue
        if _has_wildcard(metric):
            continue  # skip wildcard unquoted metrics
        if not metric or '.' not in metric and '_' not in metric:
            continue
        # Avoid duplicating what _TS_QUOTED_RE already found
        if any(r[0] == metric or r[0].startswith(metric.split('.')[0]) for r in results):
            # Only skip if this exact unquoted metric was already captured quoted
            already = any(r[0] == metric for r in results)
            if already:
                continue

        # Extract filters from inside the parens
        paren_start = query.index('(', m.start())
        depth = 0
        paren_end = paren_start
        for i, ch in enumerate(query[paren_start:], paren_start):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    paren_end = i
                    break
        inner    = query[paren_start + 1: paren_end]
        filters  = inner[len(metric):].lstrip(' ,').lstrip('AND').lstrip('and').strip()
        results.append((metric, filters))

    return results


def _parse_tags(tags_str: str) -> tuple[dict, list, bool]:
    """
    Parse a WQL filter string into (literal_tags, variable_tags, use_source).

    Handles:
    - key="value"         → literal tag
    - key="${var}"        → variable tag
    - key=/regex/         → variable tag
    - not key="value"     → key becomes variable tag (excluded value not used)
    - not "metric.prefix" → entire clause skipped (metric exclusion, not a tag)
    - (key="a" OR key="b") → OR expansion → separate entries (handled by caller)
    """
    literal_tags:  dict = {}
    variable_tags: list = []
    use_source          = False

    # Extract NOT filter keys — these are tags we still need, just not that exact value
    # e.g. "not cpu=\"cpu-total\"" means cpu IS a tag, just not with that specific value
    # Note: "not \"processes.total*\"" is a METRIC exclusion, not a tag — skip it
    for not_m in re.finditer(r'(?i)\bNOT\s+(\w+)\s*=', tags_str):
        not_key = not_m.group(1)
        if not_key.lower() not in SOURCE_TAGS and not_key != 'source':
            if not_key not in variable_tags:
                variable_tags.append(not_key)

    # Strip all NOT clauses before further parsing
    clean = re.sub(r'(?i)\bAND\s+NOT\s+"[^"]*"',        '', tags_str)   # not "quoted.metric*"
    clean = re.sub(r'(?i)\bNOT\s+"[^"]*"',               '', clean)
    clean = re.sub(r'(?i)\bAND\s+NOT\s+\w+\s*=\s*"[^"]*"','', clean)
    clean = re.sub(r'(?i)\bNOT\s+\w+\s*=\s*"[^"]*"',    '', clean)
    clean = re.sub(r'(?i)\bAND\s+NOT\s+\w+\s*=\s*[^\s,)]+','', clean)
    clean = clean.strip()

    # Regex tag filters: key=/pattern/ → variable tag
    for rm in re.finditer(r'(\w+)\s*=\s*/[^/]+/', clean):
        rkey = rm.group(1)
        if rkey.lower() in SOURCE_TAGS or rkey == 'source':
            use_source = True
        elif rkey not in variable_tags:
            variable_tags.append(rkey)

    # key="value" and key=${var}
    for tm in _TAG_RE.finditer(clean):
        key        = tm.group(1)
        quoted_val = tm.group(2)
        var_name   = tm.group(3)
        is_var     = var_name is not None

        if key.lower() in SOURCE_TAGS or key == 'source':
            use_source = True
            continue
        if key in variable_tags:
            continue

        if is_var:
            variable_tags.append(key)
        elif quoted_val is not None:
            if re.search(r'\$\{?\w+\}?', quoted_val):
                variable_tags.append(key)
            elif quoted_val not in ('', '*', '.*', '.+'):
                literal_tags[key] = quoted_val

    return literal_tags, variable_tags, use_source


def _parse_wql_query(query: str, seen: dict) -> None:
    """Parse a WQL query and populate `seen` with deduplicated metric entries."""

    pairs = _extract_metric_and_filters(query)

    for metric, filters in pairs:
        literal_tags, variable_tags, use_source = _parse_tags(filters)

        # Detect OR groups: (key="a" OR key="b") → separate entries per value
        or_expansions: dict = {}
        for orm in re.finditer(r'\((\w+)="[^"]*"(?:\s+OR\s+\1="[^"]*")+\)', filters):
            or_key = orm.group(1)
            vals   = re.findall(r'%s="([^"]*)"' % re.escape(or_key), orm.group(0))
            if vals:
                or_expansions[or_key] = vals
                literal_tags.pop(or_key, None)

        var_sig = ','.join(sorted(variable_tags))

        def _store(name: str, combo_tags: dict):
            var_sig_local = ','.join(sorted(variable_tags))
            lit_sig       = ','.join(f'{k}={v}' for k, v in sorted(combo_tags.items()))
            dedup_key     = f"{name}|{lit_sig}|{var_sig_local}"
            if dedup_key not in seen:
                seen[dedup_key] = {
                    "name":         name,
                    "literalTags":  combo_tags,
                    "variableTags": list(variable_tags),
                    "useSource":    use_source,
                }
            elif use_source:
                seen[dedup_key]["useSource"] = True

        if or_expansions:
            or_keys = sorted(or_expansions.keys())
            for combo in itertools.product(*[or_expansions[k] for k in or_keys]):
                combo_tags = dict(literal_tags)
                for k, v in zip(or_keys, combo):
                    combo_tags[k] = v
                _store(metric, combo_tags)
        else:
            _store(metric, dict(literal_tags))


def _format_shape(entry: dict) -> str:
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
        filter_parts = []
        raw_filters  = obj.get("filters", [])
        inner        = raw_filters[0] if raw_filters and isinstance(raw_filters[0], list) else raw_filters
        for f in inner:
            if isinstance(f, list) and len(f) >= 3:
                fkey, fop, fval = f[0], f[1], str(f[2])
                is_var = fval.startswith("${") or fval.startswith("$")
                if fop in ("=~", "!=~") or is_var:
                    filter_parts.append(f'{fkey}="${{{fkey}}}"')
                elif fop in ("=", "!="):
                    filter_parts.append(f'{fkey}="{fval}"')
        filter_str = ", ".join(filter_parts)
        return f'ts("{metric}", {filter_str})' if filter_str else f'ts("{metric}")'
    except Exception as e:
        logger.debug("querybuilderSerialization parse failed: %s", e)
        return ""


def extract_metrics_from_dashboard(dashboard: dict) -> tuple[list[str], list[dict]]:
    seen: dict = {}
    source_params: list = []  # SOURCE-type parameters → actual host/source names

    wildcard_patterns: set = set()  # collect ts("mem.*") style patterns

    # Pass 1 — chart queries
    # NOTE: we parse disabled sources too — in Wavefront, sources are often
    # marked disabled=true when they are intermediate named variables used by
    # a formula in another source (e.g. disk.inodes.used / disk.inodes.total * 100
    # where both ts() sources are disabled and the formula is enabled). We still
    # need to generate data for those metrics or the formula will return nothing.
    for section in dashboard.get("sections", []):
        for row in section.get("rows", []):
            for chart in row.get("charts", []):
                for src in chart.get("sources", []):
                    q = _get_source_query(src)
                    if not q:
                        continue
                    # Collect wildcard patterns before parsing
                    for wm in re.finditer(r'(?:ts|hs)\s*\(\s*"([^"]*[*?][^"]*)"', q):
                        pat = wm.group(1).strip()
                        if pat:
                            wildcard_patterns.add(pat)
                    _parse_wql_query(q, seen)

    # Pass 2 — parameterDetails
    for var_name, param in dashboard.get("parameterDetails", {}).items():
        param_type = param.get("parameterType", "DYNAMIC")

        if param_type == "SIMPLE":
            # e.g. ${filter} → "and jolokia_agent_url=\"${env}\""
            for readable_val in param.get("valuesToReadableStrings", {}).values():
                if not readable_val:
                    continue
                for tm in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', readable_val):
                    tag_key = tm.group(1)
                    tag_val = tm.group(2)
                    if tag_key.lower() in SOURCE_TAGS or tag_key == 'source':
                        for entry in seen.values():
                            entry["useSource"] = True
                    elif re.search(r'\$\{?\w+\}?', tag_val):
                        for entry in seen.values():
                            if tag_key not in entry["variableTags"] and tag_key not in entry["literalTags"]:
                                entry["variableTags"].append(tag_key)
                    else:
                        for entry in seen.values():
                            if tag_key not in entry["variableTags"] and tag_key not in entry["literalTags"]:
                                entry["literalTags"][tag_key] = tag_val
            continue

        if param_type != "DYNAMIC":
            continue

        qv = (param.get("queryValue") or "").strip()
        if qv:
            _parse_wql_query(qv, seen)

        field_type = param.get("dynamicFieldType", "")

        # SOURCE params — collect actual source/host names to pre-fill generator
        if field_type == "SOURCE":
            default = (param.get("value") or param.get("defaultValue") or "").strip()
            vals = [k for k in param.get("valuesToReadableStrings", {}).keys()
                    if k and k.lower() not in ("label", "all", "*")]
            if default and default.lower() not in ("label", "all", "*"):
                source_params.append(default)
            elif vals:
                source_params.extend(vals[:3])

        tag_key = param.get("tagKey")
        if tag_key and field_type == "TAG_KEY":
            m = re.search(r'(?:ts|hs)\s*\(\s*"?([^",()\s]+)', qv)
            qv_metric = m.group(1).strip() if m else ""
            for entry in seen.values():
                if (entry["name"] == qv_metric
                        and tag_key not in entry["variableTags"]
                        and tag_key not in entry["literalTags"]):
                    entry["variableTags"].append(tag_key)

    # Deduplicate and sort
    shapes:      list[str]  = []
    entries:     list[dict] = []
    seen_shapes: set        = set()

    for entry in seen.values():
        name = entry.get("name", "").strip()
        if not name or ('.' not in name and '_' not in name):
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
    return shapes, entries, sorted(wildcard_patterns), source_params


# ---------------------------------------------------------------------------
# Synthetic value generation
# ---------------------------------------------------------------------------

def _base_value(metric_name: str) -> tuple[float, float, float]:
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
    base, mn, mx = _base_value(metric_name)
    name = metric_name.lower()
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

    # User-supplied tag combos (cartesian product of all tag key→values)
    user_combos: list = [[]]
    for key in sorted(tags.keys()):
        user_combos = [combo + [(key, val)] for combo in user_combos for val in tags[key]]

    is_counter_suffix = ("_total", ".total", "_failures_total", "_count_total")

    # Stable synthetic suffix for variable tags — deterministic per session
    _SYNTH_SUFFIX = str(random.randint(1000, 9999))

    for metric in metrics:
        name       = metric["name"]
        is_counter = name.lower().endswith(is_counter_suffix)

        # Merge metric-level tags: literalTags first, then variableTags with
        # synthetic values. These come from the dashboard scanner — e.g.
        # NOT cpu="cpu-total" → variableTag cpu → send cpu=synthetic-cpu-XXXX
        # so the series has the tag but doesn't match the excluded value.
        metric_tags: list[tuple[str, str]] = []
        for k, v in sorted((metric.get("literalTags") or {}).items()):
            metric_tags.append((k, v))
        for k in sorted(metric.get("variableTags") or []):
            # Only add if not already present as a literal tag
            if not any(mk == k for mk, _ in metric_tags):
                metric_tags.append((k, f"synthetic-{k}-{_SYNTH_SUFFIX}"))

        literal_keys  = set((metric.get("literalTags") or {}).keys())
        variable_keys = set(metric.get("variableTags") or [])
        metric_tag_keys = literal_keys | variable_keys

        for source in sources:
            for user_combo in user_combos:
                # Global tags only apply to this metric if it actually uses that key
                # (i.e. the key appears in literalTags or variableTags for this metric).
                # This prevents cpu/fstype tags from polluting metrics like disk.free.
                # Literal tags always win over the user-supplied value for that key.
                applicable_user = [(k, v) for k, v in user_combo
                                   if k in metric_tag_keys and k not in literal_keys]
                applicable_user_keys = {k for k, _ in applicable_user}
                combined = [(k, v) for k, v in metric_tags if k not in applicable_user_keys] + applicable_user
                tag_str  = (" " + " ".join(f"{k}={_sanitize_tag(v)}" for k, v in combined)) if combined else ""

                if is_counter:
                    base = _base_value(name)[0]
                    for i, ts in enumerate(ts_range):
                        lines.append(f"{name} {base + max(50, base * 0.1) * i:.6f} {ts} source={source}{tag_str}")
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
                if resp.status_code == 200:  return {"ok": True,  "message": f"Connected to {tenant}"}
                if resp.status_code == 401:  return {"ok": False, "message": "Authentication failed — check your API token"}
                if resp.status_code == 403:  return {"ok": False, "message": "Permission denied — token lacks read access"}
                return {"ok": False, "message": f"Unexpected HTTP {resp.status_code}"}
            except requests.exceptions.ConnectionError:
                return {"ok": False, "message": f"Cannot reach {tenant}"}
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
                return {"ok": False, "message": f"Connection refused at {host}:{port}"}
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

    sources: list[str] = payload.get("sources") or []
    source_count       = int(payload.get("source_count") or 0)
    if not sources and source_count > 0:
        sources = [f"synthetic-source-{random.randint(1000, 9999)}" for _ in range(source_count)]
    if not sources:
        return {"error": "Provide 'sources' list or 'source_count'"}

    metrics: list[dict] = payload.get("metrics") or []
    if not metrics:
        return {"error": "Provide at least one metric"}

    raw_tags: dict        = payload.get("tags") or {}
    tags: dict[str, list] = {}
    for key, val in raw_tags.items():
        if key.endswith("_count"):
            tag_key       = key[: -len("_count")]
            tags[tag_key] = [f"synthetic-{tag_key}-{random.randint(100, 999)}" for _ in range(int(val))]
        elif isinstance(val, list):
            tags[key] = val

    end_ts   = int(payload.get("end_ts") or time.time())
    start_ts = int(payload.get("start_ts") or 0)
    if not start_ts:
        start_ts = end_ts - int(float(payload.get("backfill_hours") or 1) * 3600)

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

    force      = bool(payload.get("force", False))
    over_limit = total_points > INGEST_HARD_LIMIT

    if over_limit and not force:
        return {
            "warning":           True,
            "points_would_send": total_points,
            "limit":             INGEST_HARD_LIMIT,
            "message": (
                f"This will send {total_points:,} points which exceeds the "
                f"{INGEST_HARD_LIMIT:,} point limit. Confirm to proceed."
            ),
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
        "source_names":       sources,   # actual names sent, so UI can tell user what to select
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
        "metrics":            len(metrics),
        "sources":            num_sources,
        "tag_combos":         tag_combos,
        "series_total":       series_total,
        "points_per_series":  points_per_series,
        "points_total":       points_total,
        "time_range_hours":   round((end_ts - start_ts) / 3600, 2),
        "interval_seconds":   INTERVAL_SECONDS,
        "limit":              INGEST_HARD_LIMIT,
        "exceeds_limit":      points_total > INGEST_HARD_LIMIT,
    }


@app.post("/api/dashboard/scan")
async def scan_dashboard(payload: dict):
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

    shapes, entries, wildcard_patterns, source_params = extract_metrics_from_dashboard(dashboard)

    # Resolve wildcard patterns by querying the Wavefront metrics API
    # e.g. mem.* → [mem.used, mem.free, mem.cached, ...]
    resolved_wildcard_entries: list[dict] = []
    if wildcard_patterns:
        metrics_url = f"{tenant}/api/v2/chart/api"
        auth_headers = {"Authorization": f"Bearer {token}"}

        def _resolve_wildcards():
            resolved = []
            for pattern in wildcard_patterns:
                # Strip trailing wildcards to get the prefix, e.g. "mem.*" → "mem."
                # Use the Wavefront metrics list API to find matching metric names
                prefix = pattern.rstrip('*').rstrip('.')
                try:
                    resp = requests.get(
                        f"{tenant}/api/v2/metrics",
                        params={"q": prefix, "limit": 100},
                        headers=auth_headers,
                        timeout=REQUEST_TIMEOUT,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data if isinstance(data, list) else data.get("items", data.get("response", {}).get("items", []))
                        for item in items:
                            name = item if isinstance(item, str) else item.get("name", "")
                            if name and name.startswith(prefix) and '.' in name:
                                resolved.append({
                                    "name":         name,
                                    "shape":        f'{name}, source="${{source}}"',
                                    "literalTags":  {},
                                    "variableTags": [],
                                    "useSource":    True,
                                    "fromWildcard": pattern,
                                })
                except Exception as e:
                    logger.debug("Wildcard resolve failed for %s: %s", pattern, e)
            return resolved

        try:
            with ThreadPoolExecutor() as pool:
                resolved_wildcard_entries = await loop.run_in_executor(pool, _resolve_wildcards)
        except Exception as e:
            logger.debug("Wildcard resolution error: %s", e)

    # Merge resolved wildcard metrics into entries (deduplicate against already-known metrics)
    known_names = {e["name"] for e in entries}
    for we in resolved_wildcard_entries:
        if we["name"] not in known_names:
            entries.append(we)
            shapes.append(we["shape"])
            known_names.add(we["name"])

    # Re-sort
    paired  = sorted(zip(shapes, entries), key=lambda x: x[0])
    shapes  = [p[0] for p in paired]
    entries = [p[1] for p in paired]

    return {
        "dashboard_name":       dashboard.get("name", slug),
        "dashboard_slug":       slug,
        "metrics_found":        len(shapes),
        "metrics":              shapes,
        "entries":              entries,
        "wildcard_patterns":    wildcard_patterns,
        "wildcard_resolved":    len(resolved_wildcard_entries),
        "suggested_sources":    source_params,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)