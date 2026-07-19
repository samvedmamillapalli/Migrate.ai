(() => {
  const $ = (id) => document.getElementById(id);

  const apiBaseInput = $("apiBase");
  const eventLogEl = $("eventLog");
  const logStats = $("logStats");

  let selectedId = null;
  let selectedRun = null;
  const events = [];

  function defaultApiBase() {
    if (window.location.origin && !window.location.protocol.startsWith("file")) {
      return window.location.origin;
    }
    return "http://127.0.0.1:8000";
  }

  apiBaseInput.value = defaultApiBase();

  function apiBase() {
    return (apiBaseInput.value || defaultApiBase()).replace(/\/$/, "");
  }

  function nowStamp() {
    return new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function formatError(err) {
    if (err && typeof err === "object") {
      if (typeof err.detail === "string") return err.detail;
      if (Array.isArray(err.detail)) return JSON.stringify(err.detail, null, 2);
      if (err.message) return err.message;
      return JSON.stringify(err, null, 2);
    }
    return String(err);
  }

  function logEvent({ kind, title, detail, error, ms, status }) {
    const entry = {
      kind, // pass | fail | info
      title,
      detail: detail || "",
      error: error || "",
      ms: ms ?? null,
      status: status ?? null,
      time: nowStamp(),
      at: Date.now(),
    };
    events.unshift(entry);
    renderLog();
  }

  function renderLog() {
    const pass = events.filter((e) => e.kind === "pass").length;
    const fail = events.filter((e) => e.kind === "fail").length;
    logStats.querySelector('[data-k="total"]').textContent = `${events.length} events`;
    logStats.querySelector('[data-k="pass"]').textContent = `${pass} pass`;
    logStats.querySelector('[data-k="fail"]').textContent = `${fail} fail`;

    eventLogEl.innerHTML = events
      .map((e) => {
        const meta = [
          e.status != null ? `HTTP ${e.status}` : null,
          e.ms != null ? `${e.ms}ms` : null,
        ]
          .filter(Boolean)
          .join(" · ");
        return `
          <div class="event ${e.kind}">
            <div class="time">${escapeHtml(e.time)}</div>
            <div class="tag">${e.kind}</div>
            <div class="body">
              <div><strong>${escapeHtml(e.title)}</strong>${meta ? ` · ${escapeHtml(meta)}` : ""}</div>
              ${e.detail ? `<div>${escapeHtml(e.detail)}</div>` : ""}
              ${e.error ? `<div class="err">${escapeHtml(e.error)}</div>` : ""}
            </div>
          </div>
        `;
      })
      .join("");
  }

  async function api(path, options = {}, label = path) {
    const started = performance.now();
    logEvent({
      kind: "info",
      title: `→ ${options.method || "GET"} ${label}`,
      detail: "request started",
    });
    try {
      const key = ($("apiKey")?.value || "").trim();
      const { headers: optHeaders, ...rest } = options;
      const res = await fetch(`${apiBase()}${path}`, {
        ...rest,
        headers: {
          "Content-Type": "application/json",
          ...(key ? { "X-API-Key": key } : {}),
          ...(optHeaders || {}),
        },
      });
      const ms = Math.round(performance.now() - started);
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
        const message = formatError(body) || res.statusText;
        logEvent({
          kind: "fail",
          title: `✗ ${options.method || "GET"} ${label}`,
          detail: "request failed",
          error: message,
          ms,
          status: res.status,
        });
        const error = new Error(message);
        error.status = res.status;
        error.body = body;
        throw error;
      }
      logEvent({
        kind: "pass",
        title: `✓ ${options.method || "GET"} ${label}`,
        detail: summarizeSuccess(path, body),
        ms,
        status: res.status,
      });
      return body;
    } catch (err) {
      if (err.status == null) {
        logEvent({
          kind: "fail",
          title: `✗ ${options.method || "GET"} ${label}`,
          detail: "network / client error",
          error: formatError(err),
          ms: Math.round(performance.now() - started),
        });
      }
      throw err;
    }
  }

  function summarizeSuccess(path, body) {
    if (!body || typeof body !== "object") return "ok";
    if (path.startsWith("/health")) {
      return `overall=${body.status}; db=${body.database}; aws=${body.aws?.status}`;
    }
    if (path === "/runs" && body.id) {
      return `created run ${body.id} status=${body.status}`;
    }
    if (path.startsWith("/runs?") && Array.isArray(body.items)) {
      return `listed ${body.items.length}/${body.total} runs`;
    }
    if (body.id && body.status) {
      return `run ${shortId(body.id)} → ${body.status}`;
    }
    return "ok";
  }

  function setOut(el, value, ok) {
    if (!el) return;
    el.textContent =
      typeof value === "string" ? value : JSON.stringify(value, null, 2);
    el.classList.remove("ok", "bad", "muted");
    if (ok === true) el.classList.add("ok");
    else if (ok === false) el.classList.add("bad");
    else el.classList.add("muted");
  }

  function shortId(id) {
    return String(id).slice(0, 8);
  }

  function snippet(sql) {
    const one = (sql || "").replace(/\s+/g, " ").trim();
    return one.length > 72 ? `${one.slice(0, 69)}...` : one;
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function statusTone(status) {
    if (status === "failed") return "fail";
    if (status === "completed" || status === "awaiting_approval") return "pass";
    return "info";
  }

  function highlightLoop(run) {
    const steps = document.querySelectorAll("#loopSteps li");
    steps.forEach((li) => li.classList.remove("active", "done"));
    const status = run?.status;
    const hasGrade = Boolean(run?._grade);
    const hasMemory = Boolean(run?._memory);
    let active = "predict";
    if (status === "awaiting_approval") active = "approve";
    else if (status === "running") active = "verify";
    else if (status === "completed" && !hasGrade) active = "grade";
    else if (status === "completed" && hasGrade && !hasMemory) active = "remember";
    else if (status === "completed" && hasGrade) active = "remember";
    else if (status === "failed") active = "verify";
    else if (status === "predicting" || status === "pending") active = "predict";

    const doneThrough = {
      predict: [],
      approve: ["predict"],
      verify: ["predict", "approve"],
      grade: ["predict", "approve", "verify"],
      remember: ["predict", "approve", "verify", "grade"],
    };
    const done = new Set(doneThrough[active] || []);
    if (hasGrade) done.add("grade");
    if (hasMemory) {
      done.add("grade");
      done.add("remember");
    }
    steps.forEach((li) => {
      const stage = li.getAttribute("data-stage");
      if (done.has(stage)) li.classList.add("done");
      if (stage === active) li.classList.add("active");
    });
  }

  function renderStageStrip(run) {
    const chips = [
      {
        key: "schema",
        label: "Schema snapshot",
        on: Boolean(run.schema_snapshot) || run.schema_discovery_status === "succeeded",
      },
      { key: "policy", label: "Policy analyzed", on: Boolean(run.policy_decision) },
      {
        key: "prediction",
        label: "Prediction stored",
        on: Boolean(run.explainability?.prediction || run.prediction_scale_tier),
      },
      {
        key: "recommendation",
        label: "Recommendation stored",
        on: Boolean(run.recommendation),
      },
      {
        key: "approval",
        label: "Past awaiting_approval",
        on: ["running", "completed", "failed"].includes(run.status) &&
          Boolean(run.policy_decision),
      },
      {
        key: "memory",
        label: "Memory retrieved",
        on: (run.explainability?.memory?.retrieved_count || 0) > 0,
      },
      { key: "grade", label: "Graded", on: Boolean(run._grade) },
      { key: "stored", label: "Memory stored", on: Boolean(run._memory) },
    ];
    $("stageStrip").innerHTML = chips
      .map(
        (c) =>
          `<span class="stage-chip ${c.on ? "on" : "miss"}">${escapeHtml(c.label)}</span>`,
      )
      .join("");
  }

  function renderInspector(run) {
    selectedRun = run;
    $("selectedMeta").textContent = `${run.id} · status=${run.status}`;
    $("selectedMeta").className = `meta ${statusTone(run.status)}`;
    $("runActions").hidden = false;
    highlightLoop(run);
    renderStageStrip(run);

    setOut(
      $("policyOut"),
      {
        policy_decision: run.policy_decision,
        compatibility_risk: run.compatibility_risk,
        requires_manual_review: run.requires_manual_review,
        requires_expand_contract: run.requires_expand_contract,
        parsed_statement_types: run.parsed_statement_types,
        risk_flags: run.risk_flags,
      },
      Boolean(run.policy_decision),
    );

    const pred = run.explainability?.prediction || null;
    const conf = run.explainability?.confidence || null;
    setOut(
      $("predictionOut"),
      pred || conf
        ? {
            scale_tier: run.prediction_scale_tier,
            ...pred,
            confidence: conf,
          }
        : "No prediction yet — click Run prediction.",
      Boolean(pred),
    );

    setOut(
      $("recommendationOut"),
      run.recommendation || "No recommendation yet.",
      Boolean(run.recommendation),
    );

    setOut(
      $("explainOut"),
      run.explainability || "No explainability blob yet.",
      Boolean(run.explainability),
    );

    const memory = run.explainability?.memory;
    const attribution = {
      retrieved_count: memory?.retrieved_count,
      items: memory?.items || memory?.memories || memory?.results,
      factors: memory?.ranking_factors || memory?.factors,
      weak_retrieval: memory?.weak_retrieval,
      note: "Attribution from explainability.memory (hybrid vector + metadata rank)",
    };
    setOut(
      $("gradeOut"),
      run._grade || "No grade yet — complete shadow verify or POST /grade.",
      Boolean(run._grade),
    );
    setOut(
      $("memoryOut"),
      run._memory
        ? run._memory
        : memory
          ? {
              retrieval_at_predict_time: attribution,
              stored_memory: "none yet for this run",
            }
          : "No memory row yet. Retrieval attribution appears after predict when corpus is non-empty.",
      Boolean(run._memory) || (memory ? memory.retrieved_count > 0 : null),
    );

    setOut($("detailOut"), summarizeRun(run), true);
  }

  function summarizeRun(run) {
    return {
      id: run.id,
      status: run.status,
      migration_sql: run.migration_sql,
      schema_discovery_status: run.schema_discovery_status,
      has_schema_snapshot: Boolean(run.schema_snapshot),
      connection_secret_arn: run.connection_secret_arn,
      workflow_status: run.workflow_status,
      sfn_execution_arn: run.sfn_execution_arn,
      policy_decision: run.policy_decision,
      prediction_scale_tier: run.prediction_scale_tier,
      has_grade: Boolean(run._grade),
      has_memory: Boolean(run._memory),
      created_at: run.created_at,
      updated_at: run.updated_at,
    };
  }

  async function checkHealth() {
    try {
      const data = await api("/health", {}, "/health");
      const ok = data.status === "healthy";
      $("healthBadges").innerHTML = `
        <span class="badge ${ok ? "pass" : "fail"}">overall: ${escapeHtml(data.status)}</span>
        <span class="badge ${data.database === "healthy" ? "pass" : "fail"}">db: ${escapeHtml(data.database)}</span>
        <span class="badge ${data.aws?.status === "healthy" ? "pass" : "fail"}">aws: ${escapeHtml(data.aws?.status || "n/a")}</span>
      `;
      setOut($("healthOut"), data, ok);
    } catch (err) {
      $("healthBadges").innerHTML = `<span class="badge fail">probe failed</span>`;
      setOut($("healthOut"), formatError(err), false);
    }
  }

  async function createRun() {
    const sql = $("migrationSql").value.trim();
    if (!sql) {
      logEvent({
        kind: "fail",
        title: "Create run blocked",
        error: "migration_sql is empty",
      });
      return;
    }
    try {
      const run = await api(
        "/runs",
        { method: "POST", body: JSON.stringify({ migration_sql: sql }) },
        "/runs",
      );
      selectedId = run.id;
      await refreshRuns();
      await loadRun(run.id);
    } catch {
      /* logged in api() */
    }
  }

  async function refreshRuns() {
    try {
      const data = await api("/runs?limit=30&offset=0", {}, "/runs?limit=30");
      const list = $("runList");
      list.innerHTML = "";
      if (!data.items?.length) {
        list.textContent = "No migration runs in the database yet.";
        return;
      }
      for (const item of data.items) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "run-item" + (item.id === selectedId ? " active" : "");
        btn.innerHTML = `
          <div class="status">${escapeHtml(item.status)}</div>
          <div class="id">${escapeHtml(item.id)}</div>
          <div class="sql">${escapeHtml(snippet(item.migration_sql))}</div>
          <div class="id">policy=${escapeHtml(item.policy_decision || "—")} · updated ${escapeHtml(item.updated_at || "")}</div>
        `;
        btn.addEventListener("click", () => loadRun(item.id));
        list.appendChild(btn);
      }
    } catch {
      $("runList").textContent = "Failed to load runs (see debug log).";
    }
  }

  async function loadGradeMemory(id, run) {
    try {
      run._grade = await api(`/runs/${id}/grade`, {}, "/runs/{id}/grade");
    } catch {
      run._grade = null;
    }
    try {
      run._memory = await api(`/runs/${id}/memory`, {}, "/runs/{id}/memory");
    } catch {
      run._memory = null;
    }
  }

  async function loadRun(id) {
    selectedId = id;
    try {
      const run = await api(`/runs/${id}`, {}, `/runs/{id}`);
      await loadGradeMemory(id, run);
      renderInspector(run);
      await refreshRuns();
    } catch (err) {
      setOut($("detailOut"), formatError(err), false);
    }
  }

  async function runPredict() {
    if (!selectedId) return;
    $("btnPredict").disabled = true;
    try {
      const run = await api(
        `/runs/${selectedId}/predict`,
        { method: "POST" },
        "/runs/{id}/predict",
      );
      await loadGradeMemory(selectedId, run);
      renderInspector(run);
      await refreshRuns();
    } catch {
      if (selectedId) await loadRun(selectedId).catch(() => {});
    } finally {
      $("btnPredict").disabled = false;
    }
  }

  async function approve(decision) {
    if (!selectedId) return;
    const secret = ($("connectionSecret")?.value || "").trim();
    const payload = {
      decision,
      approver_identity: $("approver").value.trim() || "smoke-tester",
      override_rationale: $("overrideRationale").value.trim() || null,
      connection_secret_arn: secret || null,
      start_workflow: true,
    };
    try {
      const run = await api(
        `/runs/${selectedId}/approve`,
        { method: "POST", body: JSON.stringify(payload) },
        "/runs/{id}/approve",
      );
      await loadGradeMemory(selectedId, run);
      renderInspector(run);
      await refreshRuns();
    } catch {
      /* logged */
    }
  }

  $("btnHealth").addEventListener("click", checkHealth);
  $("btnCreate").addEventListener("click", createRun);
  $("btnRefresh").addEventListener("click", refreshRuns);
  $("btnPredict").addEventListener("click", runPredict);
  $("btnGrade")?.addEventListener("click", async () => {
    if (!selectedId) return;
    await loadRun(selectedId);
  });
  $("btnProceed").addEventListener("click", () => approve("proceed"));
  $("btnAccept").addEventListener("click", () => approve("accept_recommended"));
  $("btnCancel").addEventListener("click", () => approve("cancel"));
  $("btnClearLog").addEventListener("click", () => {
    events.length = 0;
    renderLog();
    logEvent({ kind: "info", title: "Log cleared", detail: "session event log reset" });
  });

  logEvent({
    kind: "info",
    title: "Debug console ready",
    detail: "Probe health, create a run, then predict/approve. Events appear here.",
  });
  checkHealth();
  refreshRuns();
})();
