import { useState, useRef } from "react";

const API = import.meta.env.VITE_API_URL || "";

// Persist auth settings across page refreshes
const _loadAuth = () => {
  try {
    const s = localStorage.getItem("wf_auth");
    if (s) return JSON.parse(s);
  } catch {}
  return null;
};
const _saveAuth = (auth) => {
  try { localStorage.setItem("wf_auth", JSON.stringify(auth)); } catch {}
};

// ── Palette ─────────────────────────────────────────────────────────────────
const C = {
  bg:      "#f0f2f5",
  surface: "#ffffff",
  card:    "#ffffff",
  cardHead: "#c8d0db",
  border:  "#c5cdd8",
  accent:  "#4a7fa5",
  accentD: "#3a6885",
  green:   "#00875a",
  amber:   "#c47d00",
  red:     "#d93025",
  text:    "#1a2332",
  muted:   "#7a8a9e",
  label:   "#4a6080",
};

// ── Shared tiny components ───────────────────────────────────────────────────

function InfoBanner({ children }) {
  return (
    <div style={{
      background: "#eef4fb", border: `1px solid #c2d6ec`,
      borderLeft: "4px solid #4a7fa5", borderRadius: 8,
      padding: "11px 14px", marginBottom: 20, fontSize: 13,
      color: "#2e3f55", lineHeight: 1.6,
    }}>
      {children}
    </div>
  );
}

function Label({ children }) {
  return (
    <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.1em",
      textTransform: "uppercase", color: C.label }}>
      {children}
    </span>
  );
}

function Input({ style, ...props }) {
  return (
    <input
      style={{
        background: "#f8f9fb", border: `1px solid ${C.border}`, borderRadius: 6,
        color: C.text, padding: "8px 12px", fontSize: 13, width: "100%",
        outline: "none", fontFamily: "inherit", boxSizing: "border-box",
        transition: "border-color 0.15s",
        ...style,
      }}
      onFocus={e => (e.target.style.borderColor = C.accent)}
      onBlur={e  => (e.target.style.borderColor = C.border)}
      {...props}
    />
  );
}

function Select({ style, children, ...props }) {
  return (
    <select
      style={{
        background: "#f8f9fb", border: `1px solid ${C.border}`, borderRadius: 6,
        color: C.text, padding: "8px 12px", fontSize: 13, width: "100%",
        outline: "none", fontFamily: "inherit", boxSizing: "border-box",
        cursor: "pointer", appearance: "none",
        backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%235a6a85' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E")`,
        backgroundRepeat: "no-repeat", backgroundPosition: "right 10px center",
        paddingRight: 30,
        ...style,
      }}
      {...props}
    >
      {children}
    </select>
  );
}

function Btn({ children, onClick, disabled, variant = "primary", style }) {
  const bg = variant === "primary" ? C.accent
           : variant === "danger"  ? C.red
           : variant === "ghost"   ? "transparent"
           : C.surface;
  const col = variant === "primary" ? "#ffffff"
            : variant === "ghost"   ? C.muted
            : C.text;
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        background: disabled ? "#e2e6ec" : bg,
        color: disabled ? C.muted : col,
        border: variant === "ghost" ? `1px solid ${C.border}` : "none",
        borderRadius: 7, padding: "9px 20px", fontSize: 13,
        fontWeight: 700, fontFamily: "inherit", cursor: disabled ? "not-allowed" : "pointer",
        letterSpacing: "0.04em", transition: "all 0.15s",
        ...style,
      }}
    >
      {children}
    </button>
  );
}

function Field({ label, hint, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 5 }}>
        <Label>{label}</Label>
        {hint && <span style={{ fontSize: 11, color: C.muted }}>{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function Card({ children, style }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, boxShadow: "0 1px 6px rgba(0,0,0,0.11)",
      padding: "20px 24px", ...style,
    }}>
      {children}
    </div>
  );
}

function SectionTitle({ children }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 800, letterSpacing: "0.12em",
      textTransform: "uppercase", color: "#2e3f55",
      background: C.cardHead,
      margin: "-20px -24px 18px -24px",
      padding: "12px 24px",
      borderBottom: `1px solid #b0bac8`,
      borderRadius: "12px 12px 0 0",
    }}>
      {children}
    </div>
  );
}

function StatusBadge({ status, children }) {
  const col = status === "ok" ? C.green : status === "warn" ? C.amber : C.red;
  return (
    <span style={{
      display: "inline-block", background: col + "22", color: col,
      border: `1px solid ${col}44`, borderRadius: 4, padding: "2px 8px",
      fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
    }}>
      {children}
    </span>
  );
}

function Spinner() {
  return (
    <span style={{
      display: "inline-block", width: 14, height: 14,
      border: `2px solid ${C.border}`, borderTopColor: C.accent,
      borderRadius: "50%", animation: "spin 0.7s linear infinite",
    }} />
  );
}

// ── Tag row builder ──────────────────────────────────────────────────────────

function TagRow({ tag, onChange, onRemove }) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 8,
      alignItems: "center", marginBottom: 8,
    }}>
      <Input
        placeholder="tag key (e.g. namespace)"
        value={tag.key}
        onChange={e => onChange({ ...tag, key: e.target.value })}
      />
      <Select
        value={tag.mode}
        onChange={e => onChange({ ...tag, mode: e.target.value })}
        style={{ width: "100%" }}
      >
        <option value="auto">Auto-generate</option>
        <option value="manual">Manual list</option>
      </Select>
      {tag.mode === "auto" ? (
        <Input
          type="number" min={1} max={100} placeholder="count"
          value={tag.count}
          onChange={e => onChange({ ...tag, count: e.target.value })}
        />
      ) : (
        <Input
          placeholder="val1, val2, val3"
          value={tag.values}
          onChange={e => onChange({ ...tag, values: e.target.value })}
        />
      )}
      <button
        onClick={onRemove}
        style={{
          background: "none", border: "none", color: C.red,
          cursor: "pointer", fontSize: 18, lineHeight: 1, padding: "0 4px",
        }}
      >×</button>
    </div>
  );
}

// ── Metric row builder ───────────────────────────────────────────────────────

function MetricRow({ metric, onChange, onRemove }) {
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center" }}>
      <Input
        placeholder="metric.name (e.g. vcf.cpu.usage)"
        value={metric.name}
        onChange={e => onChange({ ...metric, name: e.target.value })}
      />
      <button
        onClick={onRemove}
        style={{
          background: "none", border: "none", color: C.red,
          cursor: "pointer", fontSize: 18, lineHeight: 1, padding: "0 4px", flexShrink: 0,
        }}
      >×</button>
    </div>
  );
}

// ── Result display ───────────────────────────────────────────────────────────

function ResultPanel({ result, error, loading }) {
  if (loading) return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, color: C.muted, marginTop: 16 }}>
      <Spinner /> <span style={{ fontSize: 13 }}>Sending data…</span>
    </div>
  );
  if (error) return (
    <div style={{
      marginTop: 16, background: C.red + "15", border: `1px solid ${C.red}44`,
      borderRadius: 8, padding: "12px 16px", color: C.red, fontSize: 13,
    }}>
      ⚠ {error}
    </div>
  );
  if (!result) return null;

  const stats = [
    ["Points Sent",    result.points_sent?.toLocaleString()],
    ["Metrics",        result.metrics],
    ["Sources",        result.sources],
    ["Time Range",     result.time_range_hours != null ? `${result.time_range_hours}h` : undefined],
  ].filter(([, v]) => v != null);

  const sourceNames = result.source_names || [];

  return (
    <div style={{
      marginTop: 16, background: C.green + "10", border: `1px solid ${C.green}44`,
      borderRadius: 8, padding: "14px 16px",
    }}>
      <div style={{ color: C.green, fontWeight: 700, fontSize: 13, marginBottom: 10 }}>
        ✓ Data ingested successfully
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 24px", marginBottom: 12 }}>
        {stats.map(([label, val]) => (
          <div key={label}>
            <span style={{ fontSize: 11, color: C.muted, display: "block", marginBottom: 2 }}>{label}</span>
            <span style={{ fontSize: 15, fontWeight: 700, color: C.text }}>{val}</span>
          </div>
        ))}
      </div>
      {sourceNames.length > 0 && (
        <div style={{
          background: C.accent + "10", border: `1px solid ${C.accent}33`,
          borderRadius: 6, padding: "10px 12px", fontSize: 12, lineHeight: 1.6,
        }}>
          <strong style={{ color: C.accent }}>Next step:</strong> In your dashboard, set the
          <strong> Host / source dropdown</strong> to one of these values to see the data:
          <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 6 }}>
            {sourceNames.map(s => (
              <span key={s} style={{
                fontFamily: "monospace", fontSize: 12, background: C.accent + "18",
                border: `1px solid ${C.accent}44`, borderRadius: 4, padding: "2px 8px",
                color: C.accent,
              }}>{s}</span>
            ))}
          </div>
          <div style={{ marginTop: 6, color: C.muted, fontSize: 11 }}>
            It may take 1–2 minutes for new sources to appear in the dropdown.
          </div>
        </div>
      )}
    </div>
  );
}

const POINT_LIMIT = 50000;
const POINT_WARN  = 25000;

function EstimatePanel({ est }) {
  if (!est) return null;
  const pts      = est.points_total || 0;
  const overLimit = pts > POINT_LIMIT;
  const overWarn  = pts > POINT_WARN && !overLimit;
  const color     = overLimit ? C.red : overWarn ? C.amber : C.text;
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{
        background: overLimit ? C.red + "10" : overWarn ? C.amber + "10" : C.accent + "12",
        border: `1px solid ${overLimit ? C.red + "55" : overWarn ? C.amber + "55" : C.accent + "44"}`,
        borderRadius: 8, padding: "12px 16px",
        marginBottom: (overLimit || overWarn) ? 8 : 0,
      }}>
        <div style={{ color: overLimit ? C.red : overWarn ? C.amber : C.accent, fontSize: 11, fontWeight: 700, marginBottom: 8 }}>
          ESTIMATE PREVIEW
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 24px" }}>
          {[
            ["Series",   est.series_total?.toLocaleString()],
            ["Points",   pts.toLocaleString()],
            ["Window",   est.time_range_hours != null ? `${est.time_range_hours}h` : undefined],
            ["Interval", est.interval_seconds != null ? `${est.interval_seconds}s` : undefined],
          ].filter(([,v]) => v != null).map(([l, v]) => (
            <div key={l}>
              <span style={{ fontSize: 11, color: C.muted, display: "block", marginBottom: 2 }}>{l}</span>
              <span style={{ fontSize: 14, fontWeight: 700, color }}>{v}</span>
            </div>
          ))}
        </div>
      </div>
      {overWarn && (
        <div style={{
          background: C.amber + "15", border: `1px solid ${C.amber}55`, borderRadius: 8,
          padding: "10px 14px", fontSize: 12, color: C.amber, lineHeight: 1.5,
        }}>
          ⚠ <strong>{pts.toLocaleString()} points</strong> — this is a large send, consider reducing
          the backfill window or number of sources.
        </div>
      )}
      {overLimit && (
        <div style={{
          background: C.red + "12", border: `1px solid ${C.red}55`, borderRadius: 8,
          padding: "10px 14px", fontSize: 12, color: C.red, lineHeight: 1.5,
        }}>
          🚨 <strong>{pts.toLocaleString()} points</strong> exceeds the {POINT_LIMIT.toLocaleString()} point limit!
          Reduce metrics, sources, tags or backfill window. You will be asked to confirm twice before sending.
        </div>
      )}
    </div>
  );
}

// ── Tab 1: Synthetic Generator ───────────────────────────────────────────────

function uid() { return Math.random().toString(36).slice(2, 8); }

function SyntheticTab({ sharedAuth, setSharedAuth, sharedMetrics, setSharedMetrics, sharedTags, setSharedTags,
                        sharedSrcMode, setSharedSrcMode, sharedSrcList, setSharedSrcList }) {
  // Metrics + tags — driven by lifted state so Scanner can populate them
  const metrics    = sharedMetrics;
  const setMetrics = setSharedMetrics;

  // Sources
  // srcMode and srcList are lifted to App so Scanner can pre-fill them
  const srcMode    = sharedSrcMode;
  const setSrcMode = setSharedSrcMode;
  const [srcCount, setSrcCount] = useState(1);
  const srcList    = sharedSrcList;
  const setSrcList = setSharedSrcList;

  // Tags — driven by lifted state
  const tags    = sharedTags;
  const setTags = setSharedTags;

  // Time
  const [backfillH, setBackfillH] = useState(0);
  const [backfillM, setBackfillM] = useState(5);

  // State
  const [loading,   setLoading]   = useState(false);
  const [result,    setResult]    = useState(null);
  const [error,     setError]     = useState(null);
  const [estimate,  setEstimate]  = useState(null);
  const [preview,        setPreview]        = useState(null);
  const [overLimitWarn,  setOverLimitWarn]  = useState(false); // first confirm for large sends
  const estTimerRef                         = useRef(null);

  // Generate preview: resolve what sources/tags will actually be created
  const buildPreview = () => {
    const p = buildPayload();
    if (!p.metrics?.length) return null;

    // Sources
    let sources = [];
    if (p.sources?.length) {
      sources = p.sources;
    } else {
      const n = p.source_count || 0;
      sources = Array.from({ length: n }, (_, i) => `synthetic-source-${String(1000 + i).padStart(4,"0")}`);
    }

    // Tags
    const tagPreviews = {};
    for (const [key, val] of Object.entries(p.tags || {})) {
      if (key.endsWith("_count")) {
        const tagKey = key.slice(0, -"_count".length);
        const n = Number(val);
        tagPreviews[tagKey] = Array.from({ length: n }, (_, i) => `synthetic-${tagKey}-${100 + i}`);
      } else if (Array.isArray(val)) {
        tagPreviews[key] = val;
      }
    }

    return { sources, tagPreviews, metrics: p.metrics, estimate };
  };

  // ---- Helpers ----

  const addMetric = () => setMetrics(m => [...m, { id: uid(), name: "" }]);
  const removeMetric = id => setMetrics(m => m.filter(x => x.id !== id));
  const updateMetric = (id, next) => setMetrics(m => m.map(x => x.id === id ? { ...x, ...next } : x));

  const addTag    = () => setTags(t => [...t, { id: uid(), key: "", mode: "auto", count: 2, values: "" }]);
  const removeTag = id => setTags(t => t.filter(x => x.id !== id));
  const updateTag = (id, next) => setTags(t => t.map(x => x.id === id ? { ...x, ...next } : x));

  const buildPayload = () => {
    const payload = {};

    // Metrics
    payload.metrics = metrics
      .map(m => ({
        name:         m.name.trim(),
        literalTags:  m.literalTags  || {},
        variableTags: m.variableTags || [],
      }))
      .filter(m => m.name);

    // Sources
    if (srcMode === "auto") {
      payload.source_count = Number(srcCount);
    } else {
      payload.sources = srcList.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
    }

    // Tags
    const tagsObj = {};
    for (const tag of tags) {
      if (!tag.key.trim()) continue;
      if (tag.mode === "auto") {
        tagsObj[`${tag.key}_count`] = Number(tag.count);
      } else {
        tagsObj[tag.key] = tag.values.split(/[\n,]+/).map(v => v.trim()).filter(Boolean);
      }
    }
    if (Object.keys(tagsObj).length) payload.tags = tagsObj;

    // Time — convert hours + minutes to fractional hours
    payload.backfill_hours = Number(backfillH) + Number(backfillM) / 60;

    // Auth
    payload.ingestion  = sharedAuth.ingestion;
    payload.tenant     = sharedAuth.tenant;
    payload.token      = sharedAuth.token;
    payload.proxy_host = sharedAuth.proxyHost;
    payload.proxy_port = Number(sharedAuth.proxyPort) || 2878;

    return payload;
  };

  // Live estimate (debounced) — accepts optional time overrides so stepper
  // buttons can pass the new value before React state has settled
  const triggerEstimate = (overrides = {}) => {
    clearTimeout(estTimerRef.current);
    estTimerRef.current = setTimeout(async () => {
      try {
        const p = buildPayload();
        // Apply any in-flight overrides (e.g. from stepper buttons)
        if (overrides.backfill_hours != null) p.backfill_hours = overrides.backfill_hours;
        if (!p.metrics?.length) return;
        const r = await fetch(`${API}/api/synthetic/estimate`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(p),
        });
        const d = await r.json();
        if (!d.error) setEstimate(d);
      } catch {}
    }, 300);
  };

  const handlePreview = async () => {
    const p = buildPayload();
    if (!p.metrics?.length) { setError("Add at least one metric name."); return; }
    setError(null);
    setResult(null);
    // Fetch a fresh estimate so the preview always shows accurate point count
    let freshEstimate = estimate;
    try {
      const r = await fetch(`${API}/api/synthetic/estimate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(p),
      });
      const d = await r.json();
      if (!d.error) { freshEstimate = d; setEstimate(d); }
    } catch {}
    setPreview({ ...buildPreview(), estimate: freshEstimate });
  };

  const handleConfirm = async (force = false) => {
    setLoading(true); setResult(null); setError(null); setPreview(null); setOverLimitWarn(false);
    try {
      const p = { ...buildPayload(), force };

      const r = await fetch(`${API}/api/synthetic`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(p),
      });
      const d = await r.json();
      if (d.warning) {
        // Backend flagged over-limit — show second confirmation
        setLoading(false);
        setOverLimitWarn(d);
        return;
      }
      if (d.error) setError(d.error);
      else setResult(d);
    } catch (e) { setError(e.message); }
    setLoading(false);
  };

  return (
    <div>
      <InfoBanner>
        <strong>Synthetic Generator</strong> — Define one or more metric names, set how many sources
        and point tag values to generate, choose how far back the metrics will be backfilled for, then
        hit <em>Preview</em> to review exactly what will be sent before committing. Data will be sent
        to the proxy or directly to tenant depending on selection. Use this to populate a dashboard with
        realistic-looking data before real metrics arrive.
      </InfoBanner>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>

      {/* LEFT: Metrics + Sources */}
      <div>
        <Card style={{ marginBottom: 16 }}>
          <SectionTitle>Metrics</SectionTitle>
          {metrics.map(m => (
            <MetricRow
              key={m.id} metric={m}
              onChange={next => { updateMetric(m.id, next); triggerEstimate(); }}
              onRemove={() => { removeMetric(m.id); triggerEstimate(); }}
            />
          ))}
          <div style={{ display: "flex", gap: 8 }}>
            <Btn variant="ghost" onClick={addMetric} style={{ fontSize: 12, padding: "6px 14px" }}>
              + Add metric
            </Btn>
            {metrics.length > 1 && (
              <Btn variant="ghost" onClick={() => setMetrics([{ id: uid(), name: "" }])}
                style={{ fontSize: 12, padding: "6px 14px", color: C.red, borderColor: C.red + "66" }}>
                Clear all
              </Btn>
            )}
          </div>
        </Card>

        <Card style={{ marginBottom: 16 }}>
          <SectionTitle>Sources</SectionTitle>
          <Field label="Mode">
            <div style={{ display: "flex", gap: 8 }}>
              {["auto", "manual"].map(m => (
                <button
                  key={m} onClick={() => { setSrcMode(m); triggerEstimate(); }}
                  style={{
                    flex: 1, padding: "7px 0", border: `1px solid ${srcMode === m ? C.accent : C.border}`,
                    borderRadius: 6, background: srcMode === m ? C.accent + "20" : "transparent",
                    color: srcMode === m ? C.accent : C.muted, cursor: "pointer",
                    fontSize: 12, fontWeight: 600, fontFamily: "inherit",
                  }}
                >
                  {m === "auto" ? "Auto-generate" : "Manual entry"}
                </button>
              ))}
            </div>
          </Field>
          {srcMode === "auto" ? (
            <Field label="Number of sources">
              <Input type="number" min={1} max={1000} value={srcCount}
                onChange={e => { setSrcCount(e.target.value); triggerEstimate(); }} />
            </Field>
          ) : (
            <Field label="Source names" hint="one per line or comma-separated">
              <textarea
                value={srcList}
                onChange={e => { setSrcList(e.target.value); triggerEstimate(); }}
                placeholder={"esxi-prod-01\nesxi-prod-02\nvcenter-mgmt-01"}
                rows={4}
                style={{
                  width: "100%", background: "#f8f9fb", border: `1px solid ${C.border}`,
                  borderRadius: 6, color: C.text, padding: "8px 12px", fontSize: 13,
                  fontFamily: "inherit", boxSizing: "border-box", resize: "vertical", outline: "none",
                }}
              />
            </Field>
          )}
        </Card>

        <Card>
          <SectionTitle>Point Tags</SectionTitle>

          {tags.length === 0 && (
            <div style={{ fontSize: 13, color: C.muted, marginBottom: 12 }}>
              No tags defined — data will be sent with only source= tag.
            </div>
          )}
          {tags.length > 0 && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto",
              gap: 8, marginBottom: 8 }}>
              <Label>Key</Label><Label>Mode</Label><Label>Values / Count</Label><span/>
            </div>
          )}
          {tags.map(tag => (
            <TagRow key={tag.id} tag={tag}
              onChange={next => { updateTag(tag.id, next); triggerEstimate(); }}
              onRemove={() => { removeTag(tag.id); triggerEstimate(); }}
            />
          ))}
          <Btn variant="ghost" onClick={addTag} style={{ fontSize: 12, padding: "6px 14px" }}>
            + Add tag
          </Btn>
        </Card>
      </div>

      {/* RIGHT: Time + Auth + Send */}
      <div>
        <Card style={{ marginBottom: 16 }}>
          <SectionTitle>Backfill Window</SectionTitle>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 14 }}>
            Data generated from <strong>now − window</strong> to <strong>now</strong>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="Hours">
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <button onClick={() => { const v = Math.max(0, backfillH - 1); setBackfillH(v); triggerEstimate({ backfill_hours: v + backfillM/60 }); }}
                  style={{ background: "#f0f2f5", border: `1px solid ${C.border}`, borderRadius: 5,
                    width: 30, height: 36, cursor: "pointer", fontSize: 16, color: C.text, flexShrink: 0 }}>−</button>
                <Input type="number" min={0} max={8760} value={backfillH}
                  onChange={e => { const v = Math.max(0, parseInt(e.target.value) || 0); setBackfillH(v); triggerEstimate({ backfill_hours: v + backfillM/60 }); }}
                  style={{ textAlign: "center" }} />
                <button onClick={() => { const v = backfillH + 1; setBackfillH(v); triggerEstimate({ backfill_hours: v + backfillM/60 }); }}
                  style={{ background: "#f0f2f5", border: `1px solid ${C.border}`, borderRadius: 5,
                    width: 30, height: 36, cursor: "pointer", fontSize: 16, color: C.text, flexShrink: 0 }}>+</button>
              </div>
            </Field>
            <Field label="Minutes">
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <button onClick={() => { const v = Math.max(0, backfillM - 5); setBackfillM(v); triggerEstimate({ backfill_hours: backfillH + v/60 }); }}
                  style={{ background: "#f0f2f5", border: `1px solid ${C.border}`, borderRadius: 5,
                    width: 30, height: 36, cursor: "pointer", fontSize: 16, color: C.text, flexShrink: 0 }}>−</button>
                <Input type="number" min={0} max={59} value={backfillM}
                  onChange={e => { const v = Math.min(59, Math.max(0, parseInt(e.target.value) || 0)); setBackfillM(v); triggerEstimate({ backfill_hours: backfillH + v/60 }); }}
                  style={{ textAlign: "center" }} />
                <button onClick={() => { const v = Math.min(55, backfillM + 5); setBackfillM(v); triggerEstimate({ backfill_hours: backfillH + v/60 }); }}
                  style={{ background: "#f0f2f5", border: `1px solid ${C.border}`, borderRadius: 5,
                    width: 30, height: 36, cursor: "pointer", fontSize: 16, color: C.text, flexShrink: 0 }}>+</button>
              </div>
            </Field>
          </div>
          {(backfillH > 0 || backfillM > 0) && (
            <div style={{ fontSize: 12, color: C.accent, fontWeight: 600, marginBottom: 8 }}>
              Window: {backfillH}h {backfillM}m
              {backfillH >= 24 ? ` (${(backfillH / 24).toFixed(1)} days)` : ""}
            </div>
          )}
          <EstimatePanel est={estimate} />
        </Card>

        <AuthCard auth={sharedAuth} setAuth={setSharedAuth} />

        <div style={{ marginTop: 16 }}>
          {!preview ? (
            <Btn onClick={handlePreview}
              disabled={loading || (sharedAuth.ingestion === "direct" && estimate?.points_total > 50000)}
              style={{ width: "100%", padding: "12px 0", fontSize: 14 }}>
              Preview →
            </Btn>
          ) : (
            <div style={{
              background: "#fff", border: `1px solid ${C.border}`, borderRadius: 10,
              padding: "16px 18px", boxShadow: "0 1px 6px rgba(0,0,0,0.11)",
            }}>
              <div style={{ fontWeight: 800, fontSize: 13, color: C.text, marginBottom: 12 }}>
                Preview — confirm before sending
              </div>

              {/* Metrics */}
              <div style={{ marginBottom: 10 }}>
                <Label>Metrics ({preview.metrics.length})</Label>
                <div style={{ marginTop: 5, display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {preview.metrics.slice(0, 12).map((m, i) => (
                    <span key={i} style={{
                      background: C.accent + "15", color: C.accent, border: `1px solid ${C.accent}33`,
                      borderRadius: 4, padding: "2px 7px", fontSize: 11,
                      fontFamily: "monospace",
                    }}>{m.name}</span>
                  ))}
                  {preview.metrics.length > 12 && (
                    <span style={{ fontSize: 11, color: C.muted, alignSelf: "center" }}>
                      +{preview.metrics.length - 12} more
                    </span>
                  )}
                </div>
              </div>

              {/* Sources */}
              <div style={{ marginBottom: 10 }}>
                <Label>Sources ({preview.sources.length})</Label>
                <div style={{ marginTop: 5, display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {preview.sources.slice(0, 8).map((s, i) => (
                    <span key={i} style={{
                      background: "#f4f6f9", border: `1px solid ${C.border}`,
                      borderRadius: 4, padding: "2px 7px", fontSize: 11,
                      fontFamily: "monospace", color: C.text,
                    }}>{s}</span>
                  ))}
                  {preview.sources.length > 8 && (
                    <span style={{ fontSize: 11, color: C.muted, alignSelf: "center" }}>
                      +{preview.sources.length - 8} more
                    </span>
                  )}
                </div>
              </div>

              {/* Tags */}
              {Object.keys(preview.tagPreviews).length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <Label>Point Tags</Label>
                  {Object.entries(preview.tagPreviews).map(([key, vals]) => (
                    <div key={key} style={{ marginTop: 6 }}>
                      <span style={{ fontSize: 11, color: C.muted, fontWeight: 600 }}>{key}: </span>
                      {vals.slice(0, 6).map((v, i) => (
                        <span key={i} style={{
                          background: "#f4f6f9", border: `1px solid ${C.border}`,
                          borderRadius: 4, padding: "2px 7px", fontSize: 11,
                          fontFamily: "monospace", color: C.text, marginRight: 4,
                        }}>{v}</span>
                      ))}
                      {vals.length > 6 && <span style={{ fontSize: 11, color: C.muted }}>+{vals.length - 6} more</span>}
                    </div>
                  ))}
                </div>
              )}

              {/* Estimate */}
              {preview.estimate && (
                <div style={{
                  background: C.accent + "10", border: `1px solid ${C.accent}30`,
                  borderRadius: 6, padding: "8px 12px", marginBottom: 12, marginTop: 4,
                }}>
                  <span style={{ fontSize: 11, color: C.accent, fontWeight: 700 }}>
                    {preview.estimate.points_total?.toLocaleString()} points
                    &nbsp;·&nbsp; {preview.estimate.series_total?.toLocaleString()} series
                    &nbsp;·&nbsp; {preview.estimate.time_range_hours}h window
                  </span>
                </div>
              )}

              <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                <Btn onClick={() => handleConfirm(false)} disabled={loading}
                  style={{ flex: 1, padding: "10px 0", fontSize: 13 }}>
                  {loading ? "Sending…" : "⚡  Confirm & Send"}
                </Btn>
                <Btn variant="ghost" onClick={() => setPreview(null)}
                  style={{ padding: "10px 18px", fontSize: 13 }}>
                  Cancel
                </Btn>
              </div>
            </div>
          )}

          {/* Over-limit double-confirmation dialog */}
          {overLimitWarn && !preview && (
            <div style={{
              background: "#fff", border: `2px solid ${C.amber}`,
              borderRadius: 10, padding: "18px 20px",
              boxShadow: "0 2px 12px rgba(0,0,0,0.15)",
            }}>
              <div style={{ fontSize: 15, fontWeight: 800, color: C.amber, marginBottom: 8 }}>
                ⚠ Large send — are you sure?
              </div>
              <div style={{ fontSize: 13, color: C.text, lineHeight: 1.6, marginBottom: 14 }}>
                You are about to send{" "}
                <strong style={{ color: C.amber }}>
                  {overLimitWarn.points_would_send?.toLocaleString()} points
                </strong>
                {" "}which exceeds the {(overLimitWarn.limit || 50000).toLocaleString()} point guideline.
                <br/>This may take some time and put load on your environment.
                <br/><strong>Click "Yes, send anyway" to proceed.</strong>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <Btn
                  variant="danger"
                  onClick={() => handleConfirm(true)}
                  disabled={loading}
                  style={{ flex: 1, padding: "10px 0", fontSize: 13 }}
                >
                  {loading ? "Sending…" : "Yes, send anyway"}
                </Btn>
                <Btn variant="ghost" onClick={() => setOverLimitWarn(false)}
                  style={{ padding: "10px 18px", fontSize: 13 }}>
                  Cancel
                </Btn>
              </div>
            </div>
          )}
        </div>

        <ResultPanel result={result} error={error} loading={loading} />
      </div>
    </div>
    </div>
  );
}

// ── Shared Auth Card ─────────────────────────────────────────────────────────

function AuthCard({ auth, setAuth }) {
  const up = (k, v) => setAuth(a => ({ ...a, [k]: v }));
  const [testing,   setTesting]   = useState(false);
  const [testResult, setTestResult] = useState(null);

  const handleTest = async () => {
    setTesting(true); setTestResult(null);
    try {
      const r = await fetch(`${API}/api/test-connection`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ingestion:  auth.ingestion,
          tenant:     auth.tenant,
          token:      auth.token,
          proxy_host: auth.proxyHost,
          proxy_port: Number(auth.proxyPort) || 2878,
        }),
      });
      const d = await r.json();
      setTestResult(d);
    } catch (e) {
      setTestResult({ ok: false, message: e.message });
    }
    setTesting(false);
  };

  return (
    <Card>
      <SectionTitle>Connection</SectionTitle>
      <Field label="Ingestion method">
        <Select value={auth.ingestion} onChange={e => up("ingestion", e.target.value)}>
          <option value="direct">Direct ingestion (HTTPS → tenant)</option>
          <option value="proxy">Proxy (TCP → Wavefront proxy)</option>
        </Select>
      </Field>

      {auth.ingestion === "direct" ? (
        <>
          <Field label="Tenant URL" hint="e.g. https://example.wavefront.com">
            <Input placeholder="https://your-tenant.wavefront.com"
              value={auth.tenant} onChange={e => up("tenant", e.target.value)} />
          </Field>
          <Field label="API Token">
            <Input type="password" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              value={auth.token} onChange={e => up("token", e.target.value)} />
          </Field>
        </>
      ) : (
        <>
          <Field label="Proxy host">
            <Input placeholder="wavefront-proxy.internal"
              value={auth.proxyHost} onChange={e => up("proxyHost", e.target.value)} />
          </Field>
          <Field label="Proxy port" hint="default 2878">
            <Input type="number" placeholder="2878"
              value={auth.proxyPort} onChange={e => up("proxyPort", e.target.value)} />
          </Field>
        </>
      )}
      <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 10 }}>
        <Btn variant="ghost" onClick={handleTest} disabled={testing}
          style={{ fontSize: 12, padding: "7px 16px" }}>
          {testing ? "Testing…" : "🔌 Test Connection"}
        </Btn>
        {testResult && (
          <span style={{
            fontSize: 12, fontWeight: 600,
            color: testResult.ok ? C.green : C.red,
          }}>
            {testResult.ok ? "✓" : "✗"} {testResult.message}
          </span>
        )}
      </div>
    </Card>
  );
}

// ── Tab 2: Dashboard Scanner ─────────────────────────────────────────────────

function ScanTab({ sharedAuth, setSharedAuth, setSharedMetrics, setSharedTags,
                  setSharedSrcMode, setSharedSrcList, setTab }) {
  const [slug,      setSlug]      = useState("");
  const [loading,   setLoading]   = useState(false);
  const [result,    setResult]    = useState(null);
  const [error,     setError]     = useState(null);
  const [confirmed, setConfirmed] = useState(false);

  const up = (k, v) => setSharedAuth(a => ({ ...a, [k]: v }));

  // Build deduplicated metric list and extract literal point tags for the generator
  const buildTransferData = (entries) => {
    const metrics = (entries || [])
      .filter(e => e.name)
      .map(e => ({
        id:           uid(),
        name:         e.name,
        literalTags:  e.literalTags  || {},
        variableTags: e.variableTags || [],
      }));

    // Collect tag keys from all metric entries so user can see/edit them.
    // These are sent per-metric by the backend, not applied globally to all metrics.
    const varKeys = new Set();
    const litMap  = {};

    for (const e of (entries || [])) {
      for (const k of (e.variableTags || [])) varKeys.add(k);
      for (const [k, v] of Object.entries(e.literalTags || {})) {
        if (!varKeys.has(k)) {
          if (!litMap[k]) litMap[k] = new Set();
          litMap[k].add(v);
        }
      }
    }
    for (const k of varKeys) delete litMap[k];

    const tags = [
      ...[...varKeys].map(k => ({ id: uid(), key: k, mode: "auto", count: 2, values: "" })),
      ...Object.entries(litMap).map(([k, valSet]) => ({
        id: uid(), key: k, mode: "manual", count: 2, values: [...valSet].join(", "),
      })),
    ];

    return { metrics, tags };
  };

  const handleTransfer = () => {
    if (!result) return;
    const { metrics, tags } = buildTransferData(result.entries || []);
    setSharedMetrics(metrics);
    setSharedTags(tags);
    // Pre-fill sources from the dashboard's SOURCE parameter defaults
    // so synthetic data lands on the right source name (e.g. "lx" not "synthetic-source-1234")
    const suggested = result.suggested_sources || [];
    if (suggested.length > 0) {
      setSharedSrcMode("manual");
      setSharedSrcList(suggested.join(", "));
    }
    setTab("synthetic");
  };

  const canScan = slug.trim() && sharedAuth.tenant && sharedAuth.token;

  const handleScan = async () => {
    setLoading(true); setResult(null); setError(null);
    try {
      const r = await fetch(`${API}/api/dashboard/scan`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant:         sharedAuth.tenant,
          token:          sharedAuth.token,
          dashboard_slug: slug.trim(),
        }),
      });
      const d = await r.json();
      if (d.error) setError(d.error);
      else setResult(d);
    } catch (e) { setError(e.message); }
    setLoading(false);
  };

  return (
    <div>
      <InfoBanner>
        <strong>Dashboard Scanner</strong> — Enter a dashboard's URL slug (the ID shown in the browser
        address bar after <em>/dashboards/</em>) and your API token. The scanner fetches the dashboard
        definition from your tenant and extracts every metric name and tag filter used across all charts.
        Use the <strong>⚡ Send to Generator</strong> button to transfer those metrics straight into the
        Synthetic Generator tab, with point tags pre-populated, ready to send data in one click.
      </InfoBanner>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
      <div>
        {/* Connection — direct only, no proxy option for dashboard scan */}
        <Card style={{ marginBottom: 16 }}>
          <SectionTitle>Connection</SectionTitle>
          <Field label="Tenant URL" hint="e.g. https://example.wavefront.com">
            <Input
              placeholder="https://your-tenant.wavefront.com"
              value={sharedAuth.tenant}
              onChange={e => up("tenant", e.target.value)}
            />
          </Field>
          <Field label="API Token">
            <Input
              type="password"
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              value={sharedAuth.token}
              onChange={e => up("token", e.target.value)}
            />
          </Field>
        </Card>

        <Card>
          <SectionTitle>Dashboard</SectionTitle>
          <Field label="Dashboard slug / URL ID" hint='the ID in the dashboard URL, e.g. "vcf-alerts"'>
            <Input
              placeholder="my-dashboard-url-slug"
              value={slug}
              onChange={e => setSlug(e.target.value)}
              onKeyDown={e => e.key === "Enter" && canScan && handleScan()}
            />
          </Field>
          <Btn
            onClick={handleScan}
            disabled={loading || !canScan}
            style={{ width: "100%", padding: "11px 0", marginTop: 4 }}
          >
            {loading ? "Scanning…" : "🔍  Scan Dashboard"}
          </Btn>
          {loading && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, color: C.muted, marginTop: 12, fontSize: 13 }}>
              <Spinner /> Fetching dashboard from tenant…
            </div>
          )}
          {error && (
            <div style={{
              marginTop: 14, background: C.red + "15", border: `1px solid ${C.red}44`,
              borderRadius: 8, padding: "12px 16px", color: C.red, fontSize: 13,
            }}>
              ⚠ {error}
            </div>
          )}
          {result && (
            <div style={{
              marginTop: 14, background: C.green + "10", border: `1px solid ${C.green}44`,
              borderRadius: 8, padding: "14px 16px",
            }}>
              <div style={{ color: C.green, fontWeight: 700, fontSize: 13, marginBottom: 6 }}>
                ✓ {result.dashboard_name}
              </div>
              <div style={{ fontSize: 12, color: C.muted }}>
                {result.metrics_found} metric{result.metrics_found !== 1 ? "s" : ""} found
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* Metric list */}
      <div>
        {result ? (
          <Card style={{ boxSizing: "border-box" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <SectionTitle>Metrics in dashboard</SectionTitle>
            </div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
              <StatusBadge status="ok">{result.metrics_found} found</StatusBadge>
              {result.metrics.length > 0 && (
                <Btn
                  onClick={handleTransfer}
                  style={{ fontSize: 12, padding: "7px 16px" }}
                >
                  ⚡ Send to Generator
                </Btn>
              )}
            </div>
            <div style={{ overflowY: "auto", maxHeight: 520 }}>
              {result.metrics.length === 0 ? (
                <div style={{ color: C.muted, fontSize: 13 }}>
                  No metrics could be extracted from this dashboard's queries.
                </div>
              ) : (
                result.metrics.map((m, i) => (
                  <div key={i}
                    onClick={() => navigator.clipboard?.writeText(m)}
                    title="Click to copy"
                    style={{
                      padding: "7px 10px", marginBottom: 4, borderRadius: 6,
                      background: "#f4f6f9", border: `1px solid ${C.border}`,
                      fontFamily: "'JetBrains Mono', 'Fira Code', monospace", fontSize: 12,
                      color: C.text, wordBreak: "break-all", cursor: "pointer",
                      transition: "background 0.1s",
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = "#e8edf4"}
                    onMouseLeave={e => e.currentTarget.style.background = "#f4f6f9"}
                  >
                    {m}
                  </div>
                ))
              )}
            </div>

            {/* Wildcard patterns warning */}
            {result.wildcard_patterns?.length > 0 && (
              <div style={{
                marginTop: 12,
                background: C.amber + "12", border: `1px solid ${C.amber}55`,
                borderRadius: 8, padding: "12px 14px",
              }}>
                <div style={{ fontWeight: 700, fontSize: 12, color: C.amber, marginBottom: 6 }}>
                  ⚠ {result.wildcard_patterns.length} wildcard pattern{result.wildcard_patterns.length !== 1 ? "s" : ""} skipped
                </div>
                <div style={{ fontSize: 11, color: C.muted, lineHeight: 1.6, marginBottom: 8 }}>
                  These charts use wildcard queries like <code>ts("mem.*")</code>. The exact metric names
                  depend on your Telegraf/agent config and cannot be inferred automatically.
                  Add the specific metrics you need to the Generator manually.
                </div>
                {result.wildcard_patterns.map((p, i) => (
                  <div key={i} style={{
                    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                    fontSize: 11, color: C.amber,
                    padding: "3px 8px", marginBottom: 3,
                    background: C.amber + "10", borderRadius: 4,
                    display: "inline-block", marginRight: 6,
                  }}>
                    {p}
                  </div>
                ))}
              </div>
            )}
          </Card>
        ) : (
          <Card style={{ display: "flex", alignItems: "center", justifyContent: "center",
            minHeight: 200, borderStyle: "dashed" }}>
            <div style={{ textAlign: "center", color: C.muted }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>📊</div>
              <div style={{ fontSize: 13 }}>Scan a dashboard to see its metrics</div>
            </div>
          </Card>
        )}
      </div>
    </div>
    </div>
  );
}

// ── App shell ────────────────────────────────────────────────────────────────

const LS_KEY = "wf_synth_auth";

function loadAuth() {
  try {
    const saved = localStorage.getItem(LS_KEY);
    if (saved) return { ingestion:"proxy", tenant:"", token:"", proxyHost:"", proxyPort:"2878", ...JSON.parse(saved) };
  } catch {}
  return { ingestion:"proxy", tenant:"", token:"", proxyHost:"", proxyPort:"2878" };
}

export default function App() {
  const [tab, setTab] = useState("synthetic");

  // Shared auth state — persisted to localStorage
  const [sharedAuth, setSharedAuth] = useState(loadAuth);

  const updateAuth = (updater) => {
    setSharedAuth(prev => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      try { localStorage.setItem(LS_KEY, JSON.stringify(next)); } catch {}
      return next;
    });
  };

  // Shared metrics, tags, and source settings — lifted so Scanner can pre-fill Generator
  const [sharedMetrics, setSharedMetrics] = useState([{ id: uid(), name: "" }]);
  const [sharedSrcMode, setSharedSrcMode] = useState("auto");
  const [sharedSrcList, setSharedSrcList] = useState("");
  const [sharedTags,    setSharedTags]    = useState([]);

  const tabs = [
    { id: "synthetic", label: "⚡  Synthetic Generator" },
    { id: "scan",      label: "🔍  Dashboard Scanner"   },
  ];

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;700;800&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: ${C.bg}; color: ${C.text}; font-family: 'Syne', sans-serif; min-height: 100vh; }
        @keyframes spin { to { transform: rotate(360deg); } }
        input[type=number]::-webkit-inner-spin-button { opacity: 0.3; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: ${C.border}; border-radius: 3px; }
        select option { background: #ffffff; color: #1a2332; }
      `}</style>

      {/* Header */}
      <div style={{
        background: "#d8dde6", borderBottom: `1px solid ${C.border}`,
        padding: "0 32px", minHeight: 80,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "20px 0" }}>
          <div style={{
            width: 52, height: 52, borderRadius: 12,
            background: `linear-gradient(135deg, ${C.accent}, ${C.green})`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 26, flexShrink: 0,
            boxShadow: "0 2px 8px rgba(74,127,165,0.3)",
          }}>〜</div>
          <div>
            <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-0.01em", color: C.text, lineHeight: 1.15 }}>
              Wavefront Synthetic Metric Generator
            </div>
            <div style={{ fontSize: 12, color: "#4a5a70", letterSpacing: "0.04em", marginTop: 4 }}>
              DX OpenExplore / Aria Operations for Applications
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", gap: 4 }}>
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                padding: "12px 22px", border: "none", cursor: "pointer",
                background: "transparent", fontFamily: "inherit",
                fontSize: 13, fontWeight: 700,
                color: tab === t.id ? C.accent : C.muted,
                borderBottom: `2px solid ${tab === t.id ? C.accent : "transparent"}`,
                transition: "all 0.15s", letterSpacing: "0.02em",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "28px 32px" }}>
        {tab === "synthetic"
          ? <SyntheticTab sharedAuth={sharedAuth} setSharedAuth={updateAuth}
                          sharedMetrics={sharedMetrics} setSharedMetrics={setSharedMetrics}
                          sharedTags={sharedTags} setSharedTags={setSharedTags}
                          sharedSrcMode={sharedSrcMode} setSharedSrcMode={setSharedSrcMode}
                          sharedSrcList={sharedSrcList} setSharedSrcList={setSharedSrcList} />
          : <ScanTab      sharedAuth={sharedAuth} setSharedAuth={updateAuth}
                          setSharedMetrics={setSharedMetrics} setSharedTags={setSharedTags}
                          setSharedSrcMode={setSharedSrcMode} setSharedSrcList={setSharedSrcList}
                          setTab={setTab} />
        }
      </div>
    </>
  );
}