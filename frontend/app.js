(() => {
  const $ = (id) => document.getElementById(id);

  let runId = null;
  let run = null;
  let pollTimer = null;
  let pollStarted = null;

  const TERMINAL = new Set(["completed", "failed"]);

  function apiBase() {
    const v = ($("apiBase").value || "").trim();
    if (v) return v.replace(/\/$/, "");
    if (window.location.origin && !window.location.protocol.startsWith("file")) {
      return window.location.origin;
    }
    return "http://127.0.0.1:8000";
  }

  $("apiBase").value = apiBase();

  function log(msg, kind = "info") {
    const el = $("console");
    const line = document.createElement("div");
    line.className = `clog ${kind}`;
    const t = new Date().toLocaleTimeString([], { hour12: false });
    line.textContent = `[${t}] ${msg}`;
    el.prepend(line);
  }

  function setStatus(text) {
    $("statusLine").textContent = text;
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
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  async function api(path, options = {}) {
    const key = ($("apiKey").value || "").trim();
    const method = options.method || "GET";
    log(`${method} ${path}…`);
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
        (body && body.detail && (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail))) ||
        res.statusText;
      log(`Failed ${method} ${path}: ${detail}`, "fail");
      throw new Error(detail);
    }
    log(`OK ${method} ${path}`, "pass");
    return body;
  }

  function showRunMeta(r) {
    $("runMeta").textContent = `Run ${r.id} · status: ${r.status}`;
    $("runMeta").className = "meta";
    $("migrationSql").value = r.migration_sql || "";
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

  async function loadExtras(r) {
    const tryGet = async (path) => {
      try {
        return await api(path);
      } catch {
        return null;
      }
    };
    r._grade = await tryGet(`/runs/${r.id}/grade`);
    r._memory = await tryGet(`/runs/${r.id}/memory`);
    r._execution = await tryGet(`/runs/${r.id}/execution-result`);
    r._shadow = await tryGet(`/runs/${r.id}/shadow-cluster`);
  }

  function showActual(r) {
    const exe = r._execution;
    const g = r._grade;
    if (!exe && !g) {
      $("actualBox").textContent = "Not tested yet (shadow run needs AWS workflow deployed).";
      $("gradeBox").hidden = true;
      return;
    }
    if (exe) {
      $("actualBox").innerHTML = `
        <div><strong>Duration:</strong> ${escapeHtml(String(exe.actual_duration_seconds))} seconds</div>
        <div><strong>Storage:</strong> ${escapeHtml(String(exe.actual_storage_mb))} MB</div>
        <div><strong>Success:</strong> ${exe.success}</div>
        ${exe.error_message ? `<div class="err">${escapeHtml(exe.error_message)}</div>` : ""}
      `;
    }
    if (g) {
      $("gradeBox").hidden = false;
      $("gradeBox").innerHTML = `
        <strong>Grade</strong> · accuracy ${escapeHtml(String(g.scalar_accuracy_score))}
        · outcome ${escapeHtml(g.outcome_class)}
      `;
    }
  }

  function updateVerifyGraphic(r) {
    const track = $("verifyGraphic");
    if (r.status !== "running" && r.workflow_status === "not_started") {
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
    if (r.status === "completed") {
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
    const tick = async () => {
      if (!runId) return;
      if (Date.now() - pollStarted > 20 * 60 * 1000) {
        setStatus("Stopped watching (timeout).");
        return;
      }
      try {
        try {
          await api(`/runs/${runId}/sync-workflow`, { method: "POST" });
        } catch {
          /* ok if SFN missing */
        }
        run = await api(`/runs/${runId}`);
        await loadExtras(run);
        showRunMeta(run);
        updateVerifyGraphic(run);
        showActual(run);
        setStatus(`Shadow status: ${run.status} / workflow ${run.workflow_status}`);
        if (run.status === "running") setSteps("verify");
        if (run.status === "completed") {
          setSteps(run._memory ? "remember" : "grade");
          setStatus("Done. Prediction vs actual is above.");
          stopPoll();
          return;
        }
        if (run.status === "failed") {
          setSteps("verify");
          setStatus(`Failed: ${run._shadow?.error_message || run._execution?.error_message || "see console"}`);
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

  async function makeFake() {
    $("btnFake").disabled = true;
    try {
      setSteps("create");
      setStatus("Creating a fake migration…");
      run = await api("/runs/debug/fake-migration?owner_identity=debug", { method: "POST" });
      runId = run.id;
      showRunMeta(run);
      $("btnAnalyze").disabled = false;
      $("btnRunShadow").disabled = true;
      $("results").hidden = true;
      setStatus("Fake migration ready. Next: analyze.");
      log(`Fake migration kind ready · ${run.migration_sql.slice(0, 80)}…`, "pass");
    } catch (e) {
      setStatus(e.message || "Could not create fake migration");
    } finally {
      $("btnFake").disabled = false;
    }
  }

  async function analyze() {
    // Allow paste-your-own: create run first if needed
    $("btnAnalyze").disabled = true;
    try {
      const sql = ($("migrationSql").value || "").trim();
      if (!runId) {
        if (!sql) {
          setStatus("Make a fake migration first, or paste SQL.");
          return;
        }
        setSteps("create");
        run = await api("/runs", {
          method: "POST",
          body: JSON.stringify({ migration_sql: sql, owner_identity: "debug" }),
        });
        runId = run.id;
        showRunMeta(run);
      }

      setSteps("predict");
      setStatus("Reading schema context and asking the model…");
      run = await api(`/runs/${runId}/predict`, { method: "POST" });
      showRunMeta(run);
      showPrediction(run);
      $("btnRunShadow").disabled = false;
      setSteps("approve");
      setStatus("Prediction ready. You can run a shadow test if AWS is set up.");
    } catch (e) {
      setStatus(e.message || "Prediction failed");
    } finally {
      $("btnAnalyze").disabled = false;
    }
  }

  async function runShadow() {
    if (!runId) return;
    $("btnRunShadow").disabled = true;
    try {
      setSteps("approve");
      setStatus("Approving and starting shadow test…");
      run = await api(`/runs/${runId}/approve`, {
        method: "POST",
        body: JSON.stringify({
          decision: "proceed",
          approver_identity: "debug-ui",
          start_workflow: true,
          connection_secret_arn: run?.connection_secret_arn || null,
        }),
      });
      showRunMeta(run);
      if (run.status === "running") {
        setSteps("verify");
        setStatus("Shadow test running — watching…");
        startPoll();
      } else if (run.status === "completed") {
        setStatus("Finished without shadow (accepted recommended path).");
        await loadExtras(run);
        showActual(run);
      } else {
        setStatus(
          `Status is ${run.status}. If shadow did not start, deploy AWS Step Functions (MIGRATION_WORKFLOW_ARN is empty).`,
        );
        log(
          "Shadow test needs MIGRATION_WORKFLOW_ARN. Prediction still works without it.",
          "fail",
        );
      }
    } catch (e) {
      setStatus(e.message || "Could not start shadow test");
      $("btnRunShadow").disabled = false;
    }
  }

  $("btnFake").addEventListener("click", makeFake);
  $("btnAnalyze").addEventListener("click", analyze);
  $("btnRunShadow").addEventListener("click", runShadow);

  // If user pastes SQL manually, allow analyze without fake button
  $("migrationSql").addEventListener("input", () => {
    if (($("migrationSql").value || "").trim()) {
      $("btnAnalyze").disabled = false;
    }
  });

  log("Ready. Click “Make a fake migration” to start.");
  setStatus("Waiting for a migration…");
})();
