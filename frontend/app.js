(() => {
  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------------------
  // Auto-approve is OFF by default so Fake → Predict → Approve → Shadow are
  // separate clicks. Check the header box only if you want to skip Approve.
  // ---------------------------------------------------------------------------
  const DEV_AUTO_APPROVE_DEFAULT = false;

  let runId = null;
  let run = null;
  let pollTimer = null;
  let pollStarted = null;
  let health = null;

  function autoApproveEnabled() {
    const el = $("autoApprove");
    return el ? Boolean(el.checked) : DEV_AUTO_APPROVE_DEFAULT;
  }

  function sfnReady(integ) {
    const i = integ || health?.integrations || {};
    if (typeof i.sfn_ready === "boolean") return i.sfn_ready;
    return Boolean(i.migration_workflow_arn_set && i.run_artifacts_bucket_set);
  }

  function apiBase() {
    const v = ($("apiBase").value || "").trim();
    if (v) return v.replace(/\/$/, "");
    if (window.location.origin && !window.location.protocol.startsWith("file")) {
      return window.location.origin;
    }
    return "http://127.0.0.1:8000";
  }

  $("apiBase").value = apiBase();
  $("autoApprove").checked = DEV_AUTO_APPROVE_DEFAULT;

  function log(msg, kind = "info") {
    const el = $("console");
    const line = document.createElement("div");
    line.className = `clog ${kind}`;
    const t = new Date().toLocaleTimeString([], { hour12: false });
    line.textContent = `[${t}] ${msg}`;
    el.prepend(line);
  }

  function step(msg, kind = "info") {
    log(`→ ${msg}`, kind);
  }

  function setStatus(text) {
    $("statusLine").textContent = text;
  }

  function showLoadBar(percent, label) {
    const bar = $("loadBar");
    if (!bar) return;
    bar.hidden = false;
    const pct = Math.max(0, Math.min(100, Number(percent) || 0));
    $("loadBarFill").style.width = `${pct}%`;
    $("loadBarPct").textContent = `${Math.round(pct)}%`;
    if (label) $("loadBarLabel").textContent = label;
  }

  function hideLoadBar() {
    const bar = $("loadBar");
    if (!bar) return;
    bar.hidden = true;
    $("loadBarFill").style.width = "0%";
    $("loadBarPct").textContent = "0%";
    $("loadBarLabel").textContent = "Working…";
  }

  async function watchPipelineProgress(rid, workPromise) {
    let lastKey = "";
    const seen = new Set();
    const tick = async () => {
      try {
        const p = await api(`/runs/${rid}/pipeline-progress`, { quiet: true });
        if (!p || p.stage === "idle") return;
        showLoadBar(p.percent || 0, p.message || p.stage);
        setStatus(p.message || "Working…");
        for (const h of p.history || []) {
          const hk = `${h.stage}|${h.message}`;
          if (seen.has(hk)) continue;
          seen.add(hk);
          const kind =
            h.stage === "failed" ? "fail" : h.stage === "done" ? "pass" : "info";
          step(h.message || h.stage, kind);
        }
        const key = `${p.stage}|${p.message}`;
        if (!seen.has(key)) {
          seen.add(key);
          lastKey = key;
        }
      } catch {
        /* ignore poll errors while work runs */
      }
    };

    await tick();
    const timer = setInterval(tick, 400);
    try {
      const result = await workPromise;
      await tick();
      return result;
    } finally {
      clearInterval(timer);
    }
  }

  function setSteps(active) {
    const order = ["create", "predict", "approve", "verify", "grade", "remember"];
    const idx = order.indexOf(active);
    document.querySelectorAll("#steps li").forEach((li) => {
      const s = li.getAttribute("data-s");
      const i = order.indexOf(s);
      li.classList.remove("active", "done");
      if (i < idx) li.classList.add("done");
      if (i === idx) li.classList.add("active");
      if (active === "remember" && s === "remember") li.classList.add("done");
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function highlightSql(sql) {
    // Tokenize plain text first — never run identifier regex over HTML tags.
    const escaped = escapeHtml(sql || "");
    const kw =
      /^(ALTER|TABLE|ADD|COLUMN|CREATE|UNIQUE|INDEX|DROP|NOT|NULL|DEFAULT|ON|TYPE|BOOL|STRING|UUID|TIMESTAMPTZ|INT|INTEGER|BIGINT|TEXT|TRUE|FALSE)$/i;
    return escaped.replace(
      /('[^']*'|\b[A-Za-z_][A-Za-z0-9_]*\b)/g,
      (tok) => {
        if (tok.startsWith("'")) return `<span class="str">${tok}</span>`;
        if (kw.test(tok)) return `<span class="kw">${tok}</span>`;
        return `<span class="id">${tok}</span>`;
      },
    );
  }

  function hasRealSfnArn(r) {
    const arn = (r && r.sfn_execution_arn) || "";
    return Boolean(arn) && !String(arn).startsWith("local://");
  }

  async function api(path, options = {}) {
    const key = ($("apiKey").value || "").trim();
    const method = options.method || "GET";
    const quiet = Boolean(options.quiet);
    if (!quiet) log(`${method} ${path}…`);
    const res = await fetch(`${apiBase()}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(key ? { "X-API-Key": key } : {}),
        ...(options.headers || {}),
      },
    });
    let body = null;
    const text = await res.text();
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
    if (!res.ok) {
      const detail =
        (body &&
          body.detail &&
          (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail))) ||
        res.statusText;
      if (!quiet) log(`Failed ${method} ${path}: ${detail}`, "fail");
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    if (!quiet) log(`OK ${method} ${path}`, "pass");
    return body;
  }

  function setHealthItem(key, label, state, title) {
    const el = document.querySelector(`#healthStrip [data-k="${key}"]`);
    if (!el) return;
    el.className = `health-item ${state}`;
    el.textContent = label;
    el.title = title || label;
  }

  async function refreshHealth() {
    try {
      const h = await api("/health", { quiet: true });
      health = h;
      const integ = h.integrations || {};
      const aws = h.aws || {};

      setHealthItem(
        "api",
        "API ok",
        h.status === "unhealthy" && h.database !== "healthy" ? "bad" : "ok",
        "Control-plane HTTP API",
      );
      setHealthItem(
        "database",
        h.database === "healthy" ? "DB ok" : "DB down",
        h.database === "healthy" ? "ok" : "bad",
        h.cockroachdb_version || "CockroachDB",
      );
      setHealthItem(
        "aws",
        aws.status === "healthy" ? "AWS ok" : aws.status === "disabled" ? "AWS off" : "AWS issue",
        aws.status === "healthy" ? "ok" : aws.status === "disabled" ? "warn" : "bad",
        `region=${aws.region || "?"} account=${aws.account || "?"} ${aws.detail || ""}`,
      );
      setHealthItem(
        "bedrock",
        integ.bedrock_configured ? "Bedrock ok" : "Bedrock unset",
        integ.bedrock_configured ? "ok" : "warn",
        integ.bedrock_prediction_model_id || "Set BEDROCK_PREDICTION_MODEL_ID",
      );
      setHealthItem(
        "workflow",
        sfnReady(integ) ? "SFN ready" : "Local verify",
        sfnReady(integ) ? "ok" : "warn",
        sfnReady(integ)
          ? "MIGRATION_WORKFLOW_ARN + RUN_ARTIFACTS_BUCKET set — durable AWS shadow"
          : "No SFN ARN/bucket — step 3 uses POST /verify-local (mock shadow)",
      );
      step(
        `Health: api=${h.status} db=${h.database} aws=${aws.status} bedrock=${integ.bedrock_configured ? "configured" : "missing"} sfn=${sfnReady(integ) ? "ready" : "unset"}`,
        h.database === "healthy" ? "pass" : "fail",
      );
    } catch (e) {
      setHealthItem("api", "API down", "bad", e.message || "unreachable");
      setHealthItem("database", "DB ?", "bad", "Could not reach /health");
      setHealthItem("aws", "AWS ?", "bad", "");
      setHealthItem("bedrock", "Bedrock ?", "bad", "");
      setHealthItem("workflow", "Workflow ?", "bad", "");
      log(`Health check failed: ${e.message || e}`, "fail");
    }
  }

  function showMigrationVisual(r, extra = {}) {
    const card = $("migrationCard");
    const sql = (r && r.migration_sql) || ($("migrationSql").value || "").trim();
    if (!sql) {
      card.hidden = true;
      return;
    }
    card.hidden = false;
    $("migrationVisual").innerHTML = highlightSql(sql);
    const kind =
      extra.kind ||
      (r && r.schema_snapshot && r.schema_snapshot.debug_kind) ||
      (r && r.schema_snapshot && r.schema_snapshot.debug_synthetic ? "debug_synthetic" : "");
    const kindEl = $("migrationKind");
    if (kind) {
      kindEl.hidden = false;
      kindEl.textContent = String(kind).replaceAll("_", " ");
    } else {
      kindEl.hidden = true;
    }
    const note =
      extra.note ||
      (r && r.schema_snapshot && r.schema_snapshot.debug_note) ||
      (r && r.schema_snapshot && r.schema_snapshot.debug_synthetic
        ? "Synthetic debug migration (not graded history)."
        : "This is the SQL that will be predicted and optionally shadow-tested.");
    $("migrationNote").textContent = note;
  }

  function sumTokens(attempts) {
    let input = 0;
    let output = 0;
    let seen = false;
    for (const a of attempts || []) {
      if (a.input_tokens != null) {
        input += Number(a.input_tokens) || 0;
        seen = true;
      }
      if (a.output_tokens != null) {
        output += Number(a.output_tokens) || 0;
        seen = true;
      }
    }
    return seen ? { input, output, total: input + output } : null;
  }

  function logPredictionPipeline(r) {
    const x = r.explainability || {};
    step("Predict pipeline finished — breaking down stages…");

    const policy = x.policy || {};
    step(
      `Policy: decision=${policy.policy_decision || r.policy_decision || "?"} · ` +
        `review=${policy.requires_manual_review ?? r.requires_manual_review} · ` +
        `statements=${JSON.stringify(policy.parsed_statement_types || r.parsed_statement_types || [])}`,
    );
    for (const f of policy.driving_findings || r.risk_flags || []) {
      step(
        `  risk flag: ${f.rule_id || f} · ${f.severity || ""} · ${f.explanation || ""}`.trim(),
      );
    }

    const mem = x.memory || {};
    if (mem.retrieval_attempted === false) {
      step("Memory: retrieval was not attempted");
    } else if ((mem.retrieved_count || 0) === 0) {
      step(
        `Memory: empty corpus / no similar past runs (mode=${mem.retrieval_mode || "?"})`,
        "info",
      );
    } else {
      step(
        `Memory: retrieved ${mem.retrieved_count} similar run(s) via ${mem.retrieval_mode || "hybrid"}`,
        "pass",
      );
    }

    const pred = x.prediction || {};
    step(
      `Bedrock prediction: duration≈${pred.estimated_duration_seconds}s · ` +
        `storage≈${pred.estimated_storage_mb}MB · risk=${pred.rollback_risk} · ` +
        `tier=${pred.shadow_scale_tier || r.prediction_scale_tier || "?"}`,
      "pass",
    );
    if (pred.repair_retried) step("Prediction JSON needed one repair retry", "warn");

    const conf = x.confidence || {};
    step(
      `Confidence: raw=${conf.raw_confidence_score ?? "?"} → adjusted=${conf.confidence_score ?? "?"}`,
    );
    for (const a of conf.adjustments || []) {
      step(`  adjust: ${a.reason_code || a.reason || JSON.stringify(a)} (${a.delta ?? a})`);
    }

    const rec = x.recommendation || r.recommendation;
    if (rec) {
      step(`Recommendation: strategy=${rec.recommended_strategy}`, "pass");
      if (rec.rationale) step(`  rationale: ${String(rec.rationale).slice(0, 160)}…`);
    } else {
      step("Recommendation: skipped / not produced");
    }

    const traces = x.bedrock_traces || {};
    for (const kind of ["prediction", "recommendation"]) {
      const t = traces[kind];
      if (!t) continue;
      const tok = sumTokens(t.attempts);
      step(
        `Bedrock ${kind}: model=${t.model_id} · ` +
          `tokens in/out=${tok ? `${tok.input}/${tok.output}` : "n/a"} · ` +
          `latency=${t.latency_ms_total ?? "?"}ms`,
        String(t.model_id || "").includes("mock") ? "warn" : "pass",
      );
    }
  }

  function showAiPlan(r) {
    const card = $("aiPlanCard");
    const rec = r.recommendation || r.explainability?.recommendation;
    if (!rec) {
      card.hidden = true;
      return;
    }
    card.hidden = false;
    const steps = (rec.rollout_steps || [])
      .map((s) => `<li>${escapeHtml(s)}</li>`)
      .join("");
    $("aiPlanBox").innerHTML = `
      <div><strong>Strategy:</strong> ${escapeHtml(rec.recommended_strategy || "—")}</div>
      <div><strong>Window:</strong> ${escapeHtml(rec.suggested_deployment_window || "—")}</div>
      ${steps ? `<ol class="tiny-note">${steps}</ol>` : ""}
      ${
        rec.safer_alternative_plan
          ? `<p class="tiny-note"><strong>Safer alternative:</strong> ${escapeHtml(rec.safer_alternative_plan)}</p>`
          : ""
      }
      <p class="tiny-note">${escapeHtml(rec.rationale || "")}</p>
    `;
  }

  async function showBedrockUsage(rid) {
    const card = $("bedrockCard");
    const box = $("bedrockBox");
    try {
      const data = await api(`/runs/${rid}/model-traces`, { quiet: true });
      const traces = data.traces || {};
      const pred = traces.prediction || {};
      const rec = traces.recommendation || {};
      const predTok = sumTokens(pred.attempts);
      const recTok = sumTokens(rec.attempts);
      const input = (predTok?.input || 0) + (recTok?.input || 0);
      const output = (predTok?.output || 0) + (recTok?.output || 0);
      const total = input + output;
      const modelId = pred.model_id || rec.model_id || "unknown";
      const isMock =
        String(modelId).toLowerCase().includes("mock") || String(modelId) === "mock-model";
      const latency =
        (Number(pred.latency_ms_total) || 0) + (Number(rec.latency_ms_total) || 0);

      card.hidden = false;
      box.innerHTML = `
        <div><strong>Model:</strong> ${escapeHtml(modelId)}</div>
        <span class="bedrock-badge ${isMock ? "mock" : ""}">
          ${isMock ? "Mock client (not live Bedrock)" : "AWS Bedrock (live)"}
        </span>
        <div class="token-grid">
          <div class="token-pill"><span class="n">${input || "—"}</span><span class="l">Input tokens</span></div>
          <div class="token-pill"><span class="n">${output || "—"}</span><span class="l">Output tokens</span></div>
          <div class="token-pill"><span class="n">${total || "—"}</span><span class="l">Total tokens</span></div>
        </div>
        <p class="tiny-note">
          Prediction ${predTok ? `${predTok.total} tokens` : "n/a"} ·
          Recommendation ${recTok ? `${recTok.total} tokens` : "n/a"} ·
          Latency ${latency ? Math.round(latency) + " ms" : "—"}
        </p>
      `;
    } catch (e) {
      card.hidden = false;
      box.innerHTML = `<div class="err">${escapeHtml(e.message || "No Bedrock traces yet")}</div>`;
    }
  }

  function showRunMeta(r) {
    $("runMeta").textContent = `Run ${r.id} · status: ${r.status}`;
    $("runMeta").className = "meta";
    $("migrationSql").value = r.migration_sql || "";
    showMigrationVisual(r);
  }

  function showPrediction(r) {
    $("results").hidden = false;
    const p = r.explainability?.prediction;
    const c = r.explainability?.confidence;
    if (!p) {
      $("predBox").textContent = "No prediction yet";
      return;
    }
    $("predBox").innerHTML = `
      <div><strong>Duration:</strong> ${escapeHtml(String(p.estimated_duration_seconds))} seconds</div>
      <div><strong>Storage:</strong> ${escapeHtml(String(p.estimated_storage_mb))} MB</div>
      <div><strong>Rollback risk:</strong> ${escapeHtml(String(p.rollback_risk))}</div>
      <div><strong>Confidence:</strong> ${c ? Math.round((c.confidence_score || 0) * 100) + "%" : "—"}</div>
      <p class="tiny-note">${escapeHtml(p.risk_explanation || "")}</p>
    `;

    const mem = r.explainability?.memory;
    const hint = $("memoryHint");
    if (mem && mem.retrieved_count > 0) {
      hint.hidden = false;
      const top = (mem.attribution?.memories || mem.memories || [])[0];
      hint.innerHTML = `
        <strong>Used past memory</strong> (CockroachDB vector index)<br/>
        ${escapeHtml(top?.migration_summary || "similar past migration")}
      `;
    } else if (mem) {
      hint.hidden = false;
      hint.textContent =
        mem.empty_vs_never_attempted === "empty" || mem.retrieved_count === 0
          ? "No similar past migrations in memory yet (empty corpus is OK)."
          : "Memory retrieval info available.";
    } else {
      hint.hidden = true;
    }
  }

  async function loadExtras(r, { onlyIfPresent = true } = {}) {
    // Never spam the console: always quiet. 404 before verify is normal.
    const tryGet = async (path) => {
      try {
        return await api(path, { quiet: true });
      } catch {
        return null;
      }
    };
    if (!onlyIfPresent || r.status === "completed" || r.status === "failed" || r._forceExtras) {
      r._grade = await tryGet(`/runs/${r.id}/grade`);
      r._memory = await tryGet(`/runs/${r.id}/memory`);
      r._execution = await tryGet(`/runs/${r.id}/execution-result`);
      r._shadow = await tryGet(`/runs/${r.id}/shadow-cluster`);
      return;
    }
    // Mid-flight: skip optional endpoints entirely (avoids expected 404 noise).
    r._grade = null;
    r._memory = null;
    r._execution = null;
    r._shadow = null;
  }

  function showShadowEvidence(r) {
    const card = $("shadowCard");
    const box = $("shadowBox");
    if (!card || !box) return;
    const sh = r._shadow;
    const local = r.explainability?.local_verify;
    const arn = r.sfn_execution_arn || "";

    if (!sh && !local && !arn) {
      card.hidden = true;
      return;
    }

    card.hidden = false;
    if (!sh) {
      box.innerHTML = `
        <div><strong>Mode:</strong> ${
          String(arn).startsWith("local://")
            ? "Local mock shadow (in-process)"
            : arn
              ? "AWS Step Functions"
              : "Unknown"
        }</div>
        <p class="tiny-note">
          ${
            local?.note ||
            "No shadow_cluster row yet — verify may still be running, or cleanup already removed timings."
          }
        </p>
        <p class="tiny-note">ARN: ${escapeHtml(arn || "—")}</p>
      `;
      return;
    }

    const timings = sh.stage_timings || {};
    const timingKeys = Object.keys(timings);
    const timingHtml = timingKeys.length
      ? `<div class="shadow-timings">${timingKeys
          .map((k) => {
            const v = timings[k];
            const label = escapeHtml(k);
            const num =
              typeof v === "number"
                ? v > 50
                  ? `${Math.round(v)} ms`
                  : `${v}s`
                : escapeHtml(String(v));
            return `<div class="shadow-timing"><span class="n">${num}</span><span class="l">${label}</span></div>`;
          })
          .join("")}</div>`
      : `<p class="tiny-note">No stage_timings recorded on this row.</p>`;

    const isMock =
      String(sh.provider || "").toLowerCase().includes("mock") ||
      String(arn).startsWith("local://");

    box.innerHTML = `
      <div><strong>Provider:</strong> ${escapeHtml(sh.provider || "—")}
        <span class="bedrock-badge ${isMock ? "mock" : ""}">
          ${isMock ? "Mock scratch DB (local)" : "Real shadow cluster"}
        </span>
      </div>
      <div><strong>Status:</strong> ${escapeHtml(sh.status || "—")}</div>
      <div><strong>Cluster name:</strong> ${escapeHtml(sh.cluster_name || "—")}</div>
      <div><strong>Cluster id:</strong> ${escapeHtml(sh.cluster_id || "—")}</div>
      <div><strong>Region:</strong> ${escapeHtml(sh.region || "—")}</div>
      <div><strong>Scale tier:</strong> ${escapeHtml(sh.scale_tier || "—")}</div>
      <div><strong>Destroyed:</strong> ${sh.destroyed_at ? escapeHtml(String(sh.destroyed_at)) : "not yet"}</div>
      ${sh.error_message ? `<div class="err">${escapeHtml(sh.error_message)}</div>` : ""}
      <p class="tiny-note">ARN: ${escapeHtml(arn || "—")}</p>
      ${timingHtml}
    `;

    step(
      `Shadow evidence: provider=${sh.provider} status=${sh.status} name=${sh.cluster_name || sh.cluster_id || "?"}`,
      isMock ? "warn" : "pass",
    );
  }

  function showActual(r) {
    const exe = r._execution;
    const g = r._grade;
    const wf = (r.explainability && r.explainability.workflow) || {};
    $("results").hidden = false;

    if (exe) {
      $("actualBox").innerHTML = `
        <div><strong>Duration:</strong> ${escapeHtml(String(exe.actual_duration_seconds))} seconds</div>
        <div><strong>Storage:</strong> ${escapeHtml(String(exe.actual_storage_mb))} MB</div>
        <div><strong>Success:</strong> ${exe.success}</div>
        ${exe.error_message ? `<div class="err">${escapeHtml(exe.error_message)}</div>` : ""}
      `;
    } else if (r.status === "failed" || r.workflow_status === "failed") {
      const cause = wf.cause || wf.error || r._shadow?.error_message || "";
      $("actualBox").innerHTML = `
        <div class="err"><strong>Shadow workflow failed</strong></div>
        <div><strong>Run status:</strong> ${escapeHtml(r.status || "?")}</div>
        <div><strong>Workflow:</strong> ${escapeHtml(r.workflow_status || "?")}</div>
        ${
          cause
            ? `<div class="err">${escapeHtml(String(cause).slice(0, 800))}</div>`
            : `<div class="tiny-note">No execution metrics — the workflow failed before PersistResults.</div>`
        }
        ${
          r.sfn_execution_arn
            ? `<p class="tiny-note">SFN: ${escapeHtml(r.sfn_execution_arn)}</p>`
            : ""
        }
      `;
    } else if (hasRealSfnArn(r) && (r.status === "running" || r.workflow_status === "running")) {
      $("actualBox").innerHTML = `
        <div><strong>Shadow test in progress…</strong></div>
        <div>Run: ${escapeHtml(r.status || "?")} · Workflow: ${escapeHtml(r.workflow_status || "?")}</div>
        <p class="tiny-note">Waiting for Step Functions to finish (provision → migrate → grade).</p>
      `;
    } else if (r.status === "awaiting_approval") {
      $("actualBox").textContent =
        "Prediction done. Click 3. Approve, then 4. Run shadow test.";
    } else if (r.status === "running" && !hasRealSfnArn(r)) {
      $("actualBox").textContent =
        "Approved. Click 4. Run shadow test to start AWS Step Functions.";
    } else {
      $("actualBox").textContent =
        "Not tested yet — click 3. Approve, then 4. Run shadow test.";
    }

    if (g) {
      $("gradeBox").hidden = false;
      $("gradeBox").innerHTML = `
        <strong>Grade</strong> · accuracy ${escapeHtml(String(g.scalar_accuracy_score))}
        · outcome ${escapeHtml(g.outcome_class)}
      `;
    } else if (!exe) {
      $("gradeBox").hidden = true;
    }
  }

  function updateVerifyGraphic(r) {
    const track = $("verifyGraphic");
    if (r.status !== "running" && r.workflow_status === "not_started" && !r.explainability?.local_verify) {
      track.hidden = true;
      return;
    }
    track.hidden = false;
    const timings = r._shadow?.stage_timings || {};
    const status = (r._shadow?.status || "").toLowerCase();
    const map = {
      provision: ["provision", "provisioning", "ready"],
      seed: ["seed", "seeding"],
      migrate: ["migrate", "migrating"],
      measure: ["measure", "collect"],
      cleanup: ["teardown", "destroy", "destroyed", "cleanup"],
    };
    document.querySelectorAll(".verify-step").forEach((el) => {
      const key = el.getAttribute("data-v");
      el.classList.remove("on", "done");
      const keys = map[key] || [];
      const hasTiming = keys.some((k) => timings[k] != null || timings[`${k}_ms`] != null);
      if (hasTiming) el.classList.add("done");
      if (keys.some((k) => status.includes(k))) el.classList.add("on");
    });
    if (r.status === "running") {
      document.querySelector('[data-v="migrate"]')?.classList.add("on");
    }
    if (r.status === "completed" || r.explainability?.local_verify) {
      document.querySelectorAll(".verify-step").forEach((el) => el.classList.add("done"));
    }
  }

  function stopPoll() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
  }

  function startPoll() {
    stopPoll();
    pollStarted = Date.now();
    $("verifyGraphic").hidden = false;
    step("Watching AWS Step Functions execution…");
    const tick = async () => {
      if (!runId) return;
      if (Date.now() - pollStarted > 20 * 60 * 1000) {
        setStatus("Stopped watching (timeout).");
        return;
      }
      try {
        if (hasRealSfnArn(run)) {
          try {
            await api(`/runs/${runId}/sync-workflow`, { method: "POST", quiet: true });
          } catch {
            /* ignore transient */
          }
        }
        run = await api(`/runs/${runId}`, { quiet: true });
        const done = run.status === "completed" || run.status === "failed";
        await loadExtras(run, { onlyIfPresent: !done });
        if (done) {
          run._forceExtras = true;
          await loadExtras(run, { onlyIfPresent: false });
        }
        showRunMeta(run);
        updateVerifyGraphic(run);
        showActual(run);
        showShadowEvidence(run);
        setStatus(`Shadow status: ${run.status} / workflow ${run.workflow_status}`);
        if (run.status === "running") setSteps("verify");
        if (run.status === "completed") {
          setSteps(run._memory ? "remember" : "grade");
          step("AWS shadow finished — grade/memory available", "pass");
          setStatus("Done. Prediction vs actual is above.");
          stopPoll();
          return;
        }
        if (run.status === "failed") {
          setSteps("verify");
          setStatus(
            `Failed: ${run._shadow?.error_message || run._execution?.error_message || "see console"}`,
          );
          stopPoll();
          return;
        }
      } catch (e) {
        log(String(e.message || e), "fail");
      }
      pollTimer = setTimeout(tick, 3000);
    };
    pollTimer = setTimeout(tick, 800);
  }

  function markVerifySteps(phase) {
    $("verifyGraphic").hidden = false;
    const order = ["provision", "seed", "migrate", "measure", "cleanup"];
    const idx = order.indexOf(phase);
    document.querySelectorAll(".verify-step").forEach((el) => {
      const key = el.getAttribute("data-v");
      const i = order.indexOf(key);
      el.classList.remove("on", "done");
      if (i < idx) el.classList.add("done");
      if (i === idx) el.classList.add("on");
      if (phase === "done") el.classList.add("done");
    });
  }

  async function runLocalVerify() {
    setSteps("verify");
    markVerifySteps("provision");
    setStatus("Running local mock shadow verify…");
    showLoadBar(5, "Starting local verify…");
    step("Local verify started — progress bar tracks each handler");
    try {
      run = await watchPipelineProgress(
        runId,
        api(`/runs/${runId}/verify-local`, { method: "POST", quiet: true }),
      );
    } finally {
      showLoadBar(100, "Local verify finished");
    }
    markVerifySteps("done");
    showRunMeta(run);
    run._forceExtras = true;
    await loadExtras(run, { onlyIfPresent: false });
    showPrediction(run);
    showActual(run);
    showShadowEvidence(run);
    updateVerifyGraphic(run);
    if (run._grade) {
      step(
        `Grade: accuracy=${run._grade.scalar_accuracy_score} outcome=${run._grade.outcome_class}`,
        "pass",
      );
      setSteps("grade");
    }
    if (run._memory) {
      step(`Memory written: ${run._memory.id}`, "pass");
      setSteps("remember");
    }
    if (run._execution) {
      step(
        `Actuals: success=${run._execution.success} duration=${run._execution.actual_duration_seconds}s`,
        "pass",
      );
    }
    setStatus(
      run._grade
        ? "Local shadow verify done — prediction vs actual above."
        : "Local verify finished.",
    );
    log(
      run.explainability?.local_verify?.note || "Local mock shadow verify completed.",
      "pass",
    );
    setTimeout(hideLoadBar, 1500);
  }

  async function approveOnly() {
    if (!runId) return;
    $("btnApprove").disabled = true;
    try {
      setSteps("approve");
      setStatus("Recording proceed approval…");
      step("Recording human proceed approval (workflow not started yet)");

      if (run && (run.status === "running" || run.status === "completed")) {
        step("Already approved — ready for shadow test", "info");
        $("btnRunShadow").disabled = false;
        setStatus("Approved. Click 4. Run shadow test.");
        return;
      }

      run = await api(`/runs/${runId}/approve`, {
        method: "POST",
        body: JSON.stringify({
          decision: "proceed",
          approver_identity: "debug-ui",
          start_workflow: false,
          connection_secret_arn: run?.connection_secret_arn || null,
        }),
      });
      showRunMeta(run);
      step(`Approved: decision=proceed · status=${run.status}`, "pass");
      $("btnRunShadow").disabled = false;
      showActual(run);
      setStatus(
        sfnReady()
          ? "Approved. Click 4. Run shadow test to start AWS Step Functions."
          : "Approved. Click 4. Run shadow test (local mock — SFN not ready).",
      );
    } catch (e) {
      const msg = e.message || "";
      if (/already has an approval/i.test(msg)) {
        run = await api(`/runs/${runId}`, { quiet: true });
        showRunMeta(run);
        $("btnRunShadow").disabled = false;
        setStatus("Already approved. Click 4. Run shadow test.");
        return;
      }
      setStatus(msg || "Approve failed");
      $("btnApprove").disabled = false;
    }
  }

  async function runShadow() {
    if (!runId) return;
    $("btnRunShadow").disabled = true;
    stopPoll();
    try {
      // Require prediction first
      if (!run || run.status === "pending" || run.status === "predicting") {
        throw new Error("Run prediction first (button 2), then Approve (button 3).");
      }

      // Auto-approve path only when checkbox is on and still awaiting approval
      if (run.status === "awaiting_approval") {
        if (!autoApproveEnabled()) {
          $("btnRunShadow").disabled = false;
          $("btnApprove").disabled = false;
          throw new Error("Click 3. Approve first, then Run shadow test.");
        }
        step("Auto-approve on — recording proceed, then starting shadow");
        run = await api(`/runs/${runId}/approve`, {
          method: "POST",
          body: JSON.stringify({
            decision: "proceed",
            approver_identity: "dev-auto-approve",
            start_workflow: false,
            connection_secret_arn: run?.connection_secret_arn || null,
          }),
        });
        showRunMeta(run);
      }

      setSteps("verify");
      $("results").hidden = false;
      $("actualBox").textContent = sfnReady()
        ? "Shadow test starting on AWS Step Functions…"
        : "Starting local mock shadow verify…";

      if (sfnReady()) {
        setStatus("Starting AWS Step Functions shadow workflow…");
        step("POST /start-workflow — real CockroachDB Cloud shadow via SFN");
        if (!hasRealSfnArn(run)) {
          run = await api(`/runs/${runId}/start-workflow`, {
            method: "POST",
            body: JSON.stringify({
              connection_secret_arn: run?.connection_secret_arn || null,
            }),
          });
          showRunMeta(run);
        }
        if (!hasRealSfnArn(run)) {
          throw new Error(
            "Step Functions is configured but no execution ARN was returned. " +
              "Check connection_secret_arn on the run and API logs.",
          );
        }
        step(`SFN started: ${run.sfn_execution_arn}`, "pass");
        setStatus("Shadow test running on AWS — watching…");
        startPoll();
        return;
      }

      if (run.status === "completed") {
        run._forceExtras = true;
        await loadExtras(run, { onlyIfPresent: false });
        showActual(run);
        showShadowEvidence(run);
        setStatus("Already completed.");
        $("btnRunShadow").disabled = false;
        return;
      }

      step("No Step Functions ARN — falling back to POST /verify-local", "warn");
      await runLocalVerify();
      $("btnRunShadow").disabled = false;
    } catch (e) {
      const msg = e.message || "";
      if (
        !sfnReady() &&
        /MIGRATION_WORKFLOW_ARN|connection_secret_arn|workflow|RUN_ARTIFACTS_BUCKET/i.test(
          msg,
        )
      ) {
        try {
          step(`Workflow start blocked (${msg}) — using local verify`, "warn");
          await runLocalVerify();
          $("btnRunShadow").disabled = false;
          return;
        } catch (e2) {
          setStatus(e2.message || "Local verify failed");
          $("btnRunShadow").disabled = false;
          return;
        }
      }
      setStatus(e.message || "Could not start shadow test");
      $("btnRunShadow").disabled = false;
    }
  }

  async function makeFake() {
    $("btnFake").disabled = true;
    stopPoll();
    try {
      setSteps("create");
      setStatus("Creating a fake migration…");
      step("Creating debug fake migration (random SQL + synthetic schema)");
      run = await api("/runs/debug/fake-migration?owner_identity=debug", { method: "POST" });
      runId = run.id;
      showRunMeta(run);
      const kind =
        (run.schema_snapshot && run.schema_snapshot.debug_kind) || "fake migration";
      showMigrationVisual(run, {
        kind,
        note:
          (run.schema_snapshot && run.schema_snapshot.debug_note) ||
          "Synthetic debug migration only — shown so you can inspect the SQL before predicting.",
      });
      $("btnAnalyze").disabled = false;
      $("btnApprove").disabled = true;
      $("btnRunShadow").disabled = true;
      $("results").hidden = true;
      $("aiPlanCard").hidden = true;
      $("bedrockCard").hidden = true;
      $("shadowCard").hidden = true;
      $("actualBox").textContent =
        "Not tested yet — click 3. Approve, then 4. Run shadow test.";
      step(`Fake migration ready · kind=${kind}`, "pass");
      setStatus("Fake migration ready. Click 2. Read schema & predict.");
    } catch (e) {
      setStatus(e.message || "Could not create fake migration");
    } finally {
      $("btnFake").disabled = false;
    }
  }

  async function analyze() {
    $("btnAnalyze").disabled = true;
    try {
      const sql = ($("migrationSql").value || "").trim();
      if (!runId) {
        if (!sql) {
          setStatus("Make a fake migration first, or paste SQL.");
          return;
        }
        setSteps("create");
        step("Creating run from pasted SQL");
        run = await api("/runs", {
          method: "POST",
          body: JSON.stringify({ migration_sql: sql, owner_identity: "debug" }),
        });
        runId = run.id;
        showRunMeta(run);
      }

      setSteps("predict");
      setStatus("Running prediction pipeline…");
      showLoadBar(3, "Starting prediction pipeline…");
      step(
        "Predict started — console + bar update live. Bedrock calls often take 30–90s each.",
      );
      try {
        run = await watchPipelineProgress(
          runId,
          api(`/runs/${runId}/predict`, { method: "POST", quiet: true }),
        );
      } finally {
        showLoadBar(100, "Prediction complete");
      }
      showRunMeta(run);
      showPrediction(run);
      showAiPlan(run);
      showActual(run);
      logPredictionPipeline(run);
      await showBedrockUsage(runId);
      $("btnApprove").disabled = false;
      $("btnRunShadow").disabled = true;
      setSteps("approve");
      setTimeout(hideLoadBar, 1200);
      setStatus("Prediction ready. Click 3. Approve (right side).");
    } catch (e) {
      setStatus(e.message || "Prediction failed");
    } finally {
      $("btnAnalyze").disabled = false;
    }
  }

  $("btnFake").addEventListener("click", makeFake);
  $("btnAnalyze").addEventListener("click", analyze);
  $("btnApprove").addEventListener("click", approveOnly);
  $("btnRunShadow").addEventListener("click", runShadow);
  $("autoApprove").addEventListener("change", () => {
    step(
      `Auto-approve (dev) ${autoApproveEnabled() ? "ON" : "OFF"}`,
      "info",
    );
  });

  $("migrationSql").addEventListener("input", () => {
    const sql = ($("migrationSql").value || "").trim();
    if (sql) {
      $("btnAnalyze").disabled = false;
      showMigrationVisual(
        { migration_sql: sql },
        { note: "Paste preview — create/analyze to persist." },
      );
    }
  });

  log("Ready. Hard-refresh once (Ctrl+Shift+R) so UI v16 loads.");
  setStatus("Checking integrations…");
  refreshHealth().then(() => setStatus("Waiting for a migration…"));
})();
