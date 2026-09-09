// M11 dashboard wiring: REST polling only (no WebSocket -- 개발계획서 1.1절 #8).
// Talks to the same-origin FastAPI app mounted by main.py, so plain fetch()
// with relative paths needs no CORS setup.
import {
  summarizeOccupancy,
  buildForecastChart,
  formatAblation,
  formatSavingsCard,
  projectSeriesToPoints,
  computeSharedRange,
  formatTimestamp,
} from "./format.js";

const POLL_MS = 5000;

const el = (id) => document.getElementById(id);

async function getJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

function setConnStatus(ok) {
  const pill = el("connStatus");
  if (ok) {
    pill.textContent = "서버 연결됨";
    pill.className = "pill pill-ok";
  } else {
    pill.textContent = "서버 연결 실패";
    pill.className = "pill pill-error";
  }
  el("lastUpdated").textContent = `마지막 갱신: ${new Date().toLocaleTimeString("ko-KR")}`;
}

// ---- 1. 실시간 점유율 ----

async function refreshOccupancy() {
  try {
    const data = await getJSON("/api/v1/occupancy/live");
    const summary = summarizeOccupancy(data);
    if (!summary.hasData) {
      el("occupancyTotal").textContent = "-";
      el("occupancyState").textContent = "데이터 없음 (아직 수신된 점유율 데이터가 없습니다)";
      el("zoneList").innerHTML = "";
      return;
    }
    el("occupancyTotal").textContent = summary.total;
    el("occupancyState").textContent = `${summary.zones.length}개 zone`;
    el("zoneList").innerHTML = summary.zones
      .map((z) => `<li><span>${z.zone_id}</span><span>${z.count}</span></li>`)
      .join("");
    return true;
  } catch (err) {
    el("occupancyState").textContent = `조회 실패: ${err.message}`;
    throw err;
  }
}

// ---- 2. 예측 vs 실제 그래프 ----

function drawForecastChart(chart) {
  const canvas = el("forecastChart");
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);

  if (!chart.hasData) return;

  const series = [
    { values: chart.actual, color: "#111827" },
    { values: chart.withOcc, color: "#2563eb" },
    { values: chart.withoutOcc, color: "#d97706" },
  ];
  // Scale all three lines together so their actual distance apart is
  // visible instead of each independently stretching to fill the chart.
  const range = computeSharedRange(series.map((s) => s.values));

  for (const { values, color } of series) {
    const points = projectSeriesToPoints(values, width, height, 20, range);
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    let started = false;
    for (const p of points) {
      if (p == null) {
        started = false;
        continue;
      }
      if (!started) {
        ctx.moveTo(p.x, p.y);
        started = true;
      } else {
        ctx.lineTo(p.x, p.y);
      }
    }
    ctx.stroke();
  }
}

async function refreshForecast() {
  const buildingId = el("buildingSelect").value;
  const horizon = el("horizonInput").value || undefined;
  try {
    const params = new URLSearchParams({ building_id: buildingId });
    if (horizon) params.set("horizon", horizon);
    const rows = await getJSON(`/api/v1/forecast?${params}`);
    const chart = buildForecastChart(rows);
    drawForecastChart(chart);
    el("forecastState").textContent = chart.hasData
      ? `${buildingId} - ${rows.length}개 지점`
      : "데이터 없음 (아직 계산된 예측이 없습니다)";

    const ablationParams = new URLSearchParams({ building_id: buildingId });
    const ablation = await getJSON(`/api/v1/forecast/ablation?${ablationParams}`);
    el("ablationText").textContent = formatAblation(ablation);
    return true;
  } catch (err) {
    el("forecastState").textContent = `조회 실패: ${err.message}`;
    throw err;
  }
}

// ---- 3. 이상알림 리스트 ----

function severityClass(severity) {
  const known = ["low", "medium", "high", "critical"];
  const s = (severity || "").toLowerCase();
  return known.includes(s) ? `severity-${s}` : "severity-unknown";
}

async function ackAnomaly(eventId, button) {
  button.disabled = true;
  button.textContent = "처리 중...";
  try {
    const res = await fetch(`/api/v1/anomaly/${encodeURIComponent(eventId)}/ack`, { method: "POST" });
    if (!res.ok) throw new Error(`ack failed: HTTP ${res.status}`);
    await refreshAnomaly();
  } catch (err) {
    button.disabled = false;
    button.textContent = "확인 실패, 재시도";
    console.error(err);
  }
}

async function refreshAnomaly() {
  try {
    const rows = await getJSON("/api/v1/anomaly?status=open");
    if (!rows || rows.length === 0) {
      el("anomalyState").textContent = "열린 이상 알림이 없습니다";
      el("anomalyList").innerHTML = "";
      return;
    }
    el("anomalyState").textContent = `${rows.length}건`;
    const list = el("anomalyList");
    list.innerHTML = "";
    for (const row of rows) {
      const li = document.createElement("li");
      li.className = "anomaly-item";
      li.innerHTML =
        `<span class="severity ${severityClass(row.severity)}">${row.severity ?? "unknown"}</span>` +
        `<span>${row.zone_id}</span>` +
        `<span class="muted">${formatTimestamp(row.ts)}</span>` +
        `<span>${row.residual_kwh?.toFixed ? row.residual_kwh.toFixed(2) : row.residual_kwh} kWh</span>` +
        `<button class="ack-btn">확인</button>`;
      li.querySelector(".ack-btn").addEventListener("click", (e) => ackAnomaly(row.event_id, e.target));
      list.appendChild(li);
    }
    return true;
  } catch (err) {
    el("anomalyState").textContent = `조회 실패: ${err.message}`;
    throw err;
  }
}

// ---- 4. 절감/탄소 지표 카드 ----

async function refreshSavings() {
  try {
    const reports = await getJSON("/api/v1/savings");
    const card = formatSavingsCard(reports);
    if (!card.hasData) {
      el("savingsState").textContent = "데이터 없음 (아직 생성된 절감 리포트가 없습니다)";
      el("savingsGrid").hidden = true;
      return;
    }
    el("savingsState").textContent = "";
    el("savingsGrid").hidden = false;
    el("savingsPeriod").textContent = card.periodLabel;
    el("savingsKwh").textContent = card.savedKwhText;
    el("savingsPct").textContent = card.savedPctText;
    el("savingsCo2").textContent = card.co2Text;
    el("savingsTree").textContent = card.treeText;
    return true;
  } catch (err) {
    el("savingsState").textContent = `조회 실패: ${err.message}`;
    throw err;
  }
}

// ---- polling loop ----

async function refreshAll() {
  const results = await Promise.allSettled([
    refreshOccupancy(),
    refreshForecast(),
    refreshAnomaly(),
    refreshSavings(),
  ]);
  setConnStatus(results.some((r) => r.status === "fulfilled"));
}

el("buildingSelect").addEventListener("change", refreshForecast);
el("horizonInput").addEventListener("change", refreshForecast);

refreshAll();
setInterval(refreshAll, POLL_MS);
