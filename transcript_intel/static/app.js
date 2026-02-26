const $ = (id) => document.getElementById(id);

const state = {
  students: [],
  studentId: null,
  viewMode: "tutor",
  dashboard: null,
};

function todayIsoDate() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function setStatus(el, msg, kind = "muted") {
  el.textContent = msg || "";
  el.className = kind === "error" ? "muted" : "muted";
}

async function apiGet(path) {
  const res = await fetch(path, { headers: { "Accept": "application/json" } });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

function renderStudents() {
  const sel = $("studentSelect");
  sel.innerHTML = "";
  const opt0 = document.createElement("option");
  opt0.value = "";
  opt0.textContent = "Select a student…";
  sel.appendChild(opt0);

  for (const s of state.students) {
    const opt = document.createElement("option");
    opt.value = String(s.id);
    opt.textContent = `${s.name}${s.grade ? ` (Grade ${s.grade})` : ""}`;
    sel.appendChild(opt);
  }

  sel.value = state.studentId ? String(state.studentId) : "";
  const selected = state.students.find((x) => x.id === state.studentId);
  $("selectedStudentLabel").textContent = selected ? selected.name : "None";
}

function pctColor(p) {
  const v = Math.max(0, Math.min(100, Number(p) || 0));
  if (v >= 80) return "rgba(34,197,94,0.18)";
  if (v >= 60) return "rgba(245,158,11,0.18)";
  return "rgba(239,68,68,0.16)";
}

function severityDot(sev) {
  const v = Math.max(0, Math.min(100, Number(sev) || 0));
  if (v >= 70) return "dot bad";
  if (v >= 45) return "dot warn";
  return "dot";
}

function renderGoals(goals, viewMode) {
  const root = $("goals");
  if (!goals || !goals.length) {
    root.innerHTML = `<div class="muted">No goals yet. Process a trial transcript to seed the goal tree.</div>`;
    return;
  }

  const items = goals.map((g) => {
    const status = String(g.status || "not started");
    const pct = status === "achieved" ? 100 : status === "in progress" ? 55 : 12;
    const outcome = g.measurable_outcome ? `<div class="muted">${escapeHtml(g.measurable_outcome)}</div>` : "";
    const deadline = g.deadline ? `<div class="muted">Deadline: ${escapeHtml(g.deadline)}</div>` : "";
    const statusLine = viewMode === "tutor" ? `<div class="muted">Status: ${escapeHtml(status)}</div>` : "";
    return `
      <div class="list-item">
        <div class="list-item-title">
          <strong>${escapeHtml(g.description)}</strong>
          <span class="pill">${escapeHtml(status)}</span>
        </div>
        <div class="bar"><div style="width:${pct}%"></div></div>
        ${statusLine}
        ${outcome}
        ${deadline}
      </div>
    `;
  });

  root.innerHTML = `<div class="list">${items.join("")}</div>`;
}

function renderNextTargets(sessions, viewMode) {
  const root = $("nextTargets");
  const latest = (sessions || [])[0];
  const targets = (latest && latest.recommended_next_targets) ? latest.recommended_next_targets : [];
  if (!targets.length) {
    root.innerHTML = `<div class="muted">No next targets yet. Process a session transcript to generate suggestions.</div>`;
    return;
  }
  const intro = viewMode === "parent"
    ? "Next milestone focus (simple):"
    : "Next session focus (actionable):";
  root.innerHTML = `
    <div class="muted">${intro}</div>
    <div class="list">${targets.map((t) => `<div class="list-item"><strong>${escapeHtml(t)}</strong></div>`).join("")}</div>
  `;
}

function renderTopics(topics, viewMode) {
  const root = $("topics");
  if (!topics || !topics.length) {
    root.innerHTML = `<div class="muted">No topics yet. Process a trial transcript to seed the topic map.</div>`;
    return;
  }

  const byParent = new Map();
  for (const t of topics) {
    const p = t.parent_topic || "Other";
    if (!byParent.has(p)) byParent.set(p, []);
    byParent.get(p).push(t);
  }

  const parents = Array.from(byParent.keys()).sort();
  const sections = parents.map((p) => {
    const cells = byParent.get(p)
      .slice()
      .sort((a, b) => String(a.topic_name).localeCompare(String(b.topic_name)))
      .map((t) => {
        const m = Number(t.mastery_score) || 0;
        const c = Number(t.confidence_score) || 0;
        const meta = viewMode === "parent"
          ? `<div class="meta"><span>Mastery</span><span>${m}</span></div>`
          : `<div class="meta"><span>M ${m}</span><span>C ${c}</span></div>`;
        return `
          <div class="cell" data-topic="${escapeHtml(t.topic_name)}" data-mastery="${m}" data-confidence="${c}" style="background:${pctColor(m)}">
            <div class="name">${escapeHtml(t.topic_name)}</div>
            ${meta}
          </div>
        `;
      })
      .join("");
    return `
      <div class="heatmap">
        <div class="parent">${escapeHtml(p)}</div>
        <div class="cells">${cells}</div>
      </div>
    `;
  });

  root.innerHTML = sections.join('<div style="height:10px"></div>');
}

function renderMentalBlocks(blocks, viewMode) {
  const root = $("mentalBlocks");
  if (!blocks || !blocks.length) {
    root.innerHTML = `<div class="muted">No mental blocks detected yet.</div>`;
    return;
  }
  const items = blocks.slice(0, 8).map((b) => {
    const sev = Number(b.severity_score) || 0;
    const body = viewMode === "parent"
      ? `We’re watching for this pattern so it becomes easier and less stressful over time.`
      : `Detected ${b.frequency_count}× (first ${escapeHtml(b.first_detected)}).`;
    return `
      <div class="list-item" data-mental-block="${escapeHtml(b.description)}" data-severity="${sev}">
        <div class="list-item-title">
          <div class="severity"><span class="${severityDot(sev)}"></span><strong>${escapeHtml(b.description)}</strong></div>
          <span class="pill">Severity ${sev}</span>
        </div>
        <div class="muted">${escapeHtml(body)}</div>
      </div>
    `;
  });
  root.innerHTML = `<div class="list">${items.join("")}</div>`;
}

function renderSessions(sessions, viewMode) {
  const root = $("sessions");
  if (!sessions || !sessions.length) {
    root.innerHTML = `<div class="muted">No sessions yet.</div>`;
    return;
  }
  const items = sessions.slice(0, 12).map((s) => {
    const title = `${escapeHtml(s.session_date)} — ${escapeHtml(s.extracted_summary || "Session")}`;
    const body = viewMode === "parent"
      ? escapeHtml(s.parent_summary || "")
      : escapeHtml(s.tutor_insight || s.parent_summary || "");
    const topics = (s.detected_topics || []).slice(0, 4).map(escapeHtml).join(", ");
    return `
      <div class="list-item" data-session-id="${escapeHtml(s.id)}" data-session-date="${escapeHtml(s.session_date)}">
        <div class="list-item-title">
          <strong>${title}</strong>
          <span class="pill">${topics || "—"}</span>
        </div>
        <div class="muted">${body || "—"}</div>
      </div>
    `;
  });
  root.innerHTML = `<div class="list">${items.join("")}</div>`;
}

function renderTimeline(topicEvents) {
  const root = $("timelineChart");
  if (!topicEvents || !topicEvents.length) {
    root.innerHTML = `<div class="muted">No mastery events yet. Process a session transcript to start the timeline.</div>`;
    return;
  }

  // Build an overall trend by session date: average mastery across events on that date.
  const byDate = new Map();
  for (const e of topicEvents) {
    const d = String(e.event_date || "").slice(0, 10);
    if (!byDate.has(d)) byDate.set(d, { mastery: [], confidence: [] });
    byDate.get(d).mastery.push(Number(e.new_mastery) || 0);
    byDate.get(d).confidence.push(Number(e.new_confidence) || 0);
  }
  const dates = Array.from(byDate.keys()).sort();
  const points = dates.map((d) => {
    const m = byDate.get(d).mastery;
    const c = byDate.get(d).confidence;
    const avg = (arr) => arr.reduce((a, b) => a + b, 0) / Math.max(1, arr.length);
    return { date: d, mastery: avg(m), confidence: avg(c) };
  });

  const w = 820, h = 120, pad = 10;
  const x = (i) => pad + (i * (w - pad * 2)) / Math.max(1, points.length - 1);
  const y = (v) => pad + (1 - Math.max(0, Math.min(100, v)) / 100) * (h - pad * 2);

  const mkPath = (key) => points.map((p, i) => `${x(i).toFixed(2)},${y(p[key]).toFixed(2)}`).join(" ");
  const masteryPts = mkPath("mastery");
  const confPts = mkPath("confidence");
  const last = points[points.length - 1];

  root.innerHTML = `
    <div class="sparkline">
      <svg viewBox="0 0 ${w} ${h}" width="100%" height="100%" aria-label="Overall mastery/confidence trend">
        <polyline fill="none" stroke="rgba(124,58,237,0.95)" stroke-width="3" points="${masteryPts}" />
        <polyline fill="none" stroke="rgba(6,182,212,0.95)" stroke-width="3" points="${confPts}" />
        <line x1="${pad}" y1="${h - pad}" x2="${w - pad}" y2="${h - pad}" stroke="rgba(255,255,255,0.12)" />
        <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${h - pad}" stroke="rgba(255,255,255,0.12)" />
      </svg>
    </div>
    <div class="muted" style="margin-top:8px">
      Latest (${escapeHtml(last.date)}): mastery ${Math.round(last.mastery)} • confidence ${Math.round(last.confidence)}
    </div>
  `;
}

function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadStudents() {
  const data = await apiGet("/api/students");
  state.students = data.students || [];
  renderStudents();
}

async function loadDashboard() {
  if (!state.studentId) {
    $("dashboardMeta").textContent = "Select a student to view their dashboard.";
    $("goals").innerHTML = `<div class="muted">—</div>`;
    $("topics").innerHTML = `<div class="muted">—</div>`;
    $("sessions").innerHTML = `<div class="muted">—</div>`;
    $("mentalBlocks").innerHTML = `<div class="muted">—</div>`;
    $("nextTargets").innerHTML = `<div class="muted">—</div>`;
    $("timelineChart").innerHTML = `<div class="muted">—</div>`;
    return;
  }
  const data = await apiGet(`/api/students/${state.studentId}/dashboard?view=${encodeURIComponent(state.viewMode)}`);
  state.dashboard = data;
  const s = data.student || {};
  $("dashboardMeta").textContent = `${s.name}${s.grade ? ` • Grade ${s.grade}` : ""}${s.target_exam ? ` • ${s.target_exam}` : ""}`;

  renderGoals(data.goals || [], state.viewMode);
  renderNextTargets(data.sessions || [], state.viewMode);
  renderTopics(data.topics || [], state.viewMode);
  renderMentalBlocks(data.mental_blocks || [], state.viewMode);
  renderTimeline(data.topic_events || []);
  renderSessions(data.sessions || [], state.viewMode);
}

function bind() {
  $("trialDate").value = todayIsoDate();
  $("sessionDate").value = todayIsoDate();

  $("btnRefresh").addEventListener("click", async () => {
    await loadStudents();
    await loadDashboard();
  });

  $("studentSelect").addEventListener("change", async (e) => {
    const v = String(e.target.value || "").trim();
    state.studentId = v ? Number(v) : null;
    renderStudents();
    await loadDashboard();
  });

  for (const input of document.querySelectorAll('input[name="viewMode"]')) {
    input.addEventListener("change", async (e) => {
      state.viewMode = e.target.value;
      await loadDashboard();
    });
  }

  $("btnCreateStudent").addEventListener("click", async () => {
    const status = $("createStudentStatus");
    setStatus(status, "Creating…");
    try {
      const name = $("newName").value.trim();
      const out = await apiPost("/api/students", {
        name,
        grade: $("newGrade").value.trim() || null,
        curriculum: $("newCurriculum").value.trim() || null,
        target_exam: $("newExam").value.trim() || null,
      });
      setStatus(status, `Created student #${out.student_id}`);
      await loadStudents();
      state.studentId = out.student_id;
      renderStudents();
      await loadDashboard();
    } catch (err) {
      setStatus(status, `Error: ${err.message || err}`, "error");
    }
  });

  $("btnProcessTrial").addEventListener("click", async () => {
    const status = $("trialStatus");
    setStatus(status, "Processing trial…");
    try {
      const out = await apiPost("/api/trial", {
        student: {
          name: $("trialName").value.trim(),
          grade: $("trialGrade").value.trim() || null,
          curriculum: $("trialCurriculum").value.trim() || null,
          target_exam: $("trialExam").value.trim() || null,
        },
        session_date: $("trialDate").value,
        transcript_text: $("trialTranscript").value,
      });
      setStatus(status, `Created student #${out.student_id} and seeded goals/topics.`);
      await loadStudents();
      state.studentId = out.student_id;
      renderStudents();
      await loadDashboard();
    } catch (err) {
      setStatus(status, `Error: ${err.message || err}`, "error");
    }
  });

  $("btnProcessSession").addEventListener("click", async () => {
    const status = $("sessionStatus");
    if (!state.studentId) {
      setStatus(status, "Select a student first.", "error");
      return;
    }
    setStatus(status, "Processing session…");
    try {
      const out = await apiPost("/api/session", {
        student_id: state.studentId,
        session_date: $("sessionDate").value,
        transcript_text: $("sessionTranscript").value,
      });
      setStatus(status, `Session #${out.session_id} processed. Mastery updated.`);
      $("sessionTranscript").value = "";
      await loadDashboard();
    } catch (err) {
      setStatus(status, `Error: ${err.message || err}`, "error");
    }
  });
}

async function main() {
  bind();
  await loadStudents();
  await loadDashboard();
}

main().catch((e) => {
  console.error(e);
});
