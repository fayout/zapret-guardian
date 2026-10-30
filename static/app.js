/**
 * Zapret Guardian 2.0 — Frontend Controller
 */

const state = {
  status: null,
  strategies: [],
  activeFilter: "all",
  searchQuery: "",
  isTesting: false,
  benchmarkInterval: null,
};

// DOM References
const servicePill = document.getElementById("servicePill");
const statusDot = document.getElementById("statusDot");
const statusTitle = document.getElementById("statusTitle");
const statusDesc = document.getElementById("statusDesc");

const btnQuickTest = document.getElementById("btnQuickTest");
const btnFullTest = document.getElementById("btnFullTest");
const btnRestart = document.getElementById("btnRestart");
const btnStop = document.getElementById("btnStop");
const btnOpenFolder = document.getElementById("btnOpenFolder");
const btnStartAutoBenchmark = document.getElementById("btnStartAutoBenchmark");

const strategiesGrid = document.getElementById("strategiesGrid");
const stratSearch = document.getElementById("stratSearch");
const totalStratCount = document.getElementById("totalStratCount");

const domainListTextarea = document.getElementById("domainListTextarea");
const btnSaveDomains = document.getElementById("btnSaveDomains");
const svcStateText = document.getElementById("svcStateText");
const btnInstallService = document.getElementById("btnInstallService");
const btnUninstallService = document.getElementById("btnUninstallService");

// Radar elements
const cardDiscordGateway = document.getElementById("cardDiscordGateway");
const badgeDiscordGateway = document.getElementById("badgeDiscordGateway");
const valDiscordGateway = document.getElementById("valDiscordGateway");

const cardDiscordVoice = document.getElementById("cardDiscordVoice");
const badgeDiscordVoice = document.getElementById("badgeDiscordVoice");
const valDiscordVoice = document.getElementById("valDiscordVoice");

const cardYoutubeWeb = document.getElementById("cardYoutubeWeb");
const badgeYoutubeWeb = document.getElementById("badgeYoutubeWeb");
const valYoutubeWeb = document.getElementById("valYoutubeWeb");

const cardYoutubeStream = document.getElementById("cardYoutubeStream");
const badgeYoutubeStream = document.getElementById("badgeYoutubeStream");
const valYoutubeStream = document.getElementById("valYoutubeStream");

const verdictBanner = document.getElementById("verdictBanner");
const verdictIcon = document.getElementById("verdictIcon");
const verdictHeadline = document.getElementById("verdictHeadline");
const verdictDetails = document.getElementById("verdictDetails");

// ============================================================================
// Initialization
// ============================================================================
async function init() {
  setupEventListeners();
  await refreshStatus();
  await loadStrategies();
  await loadDomainLists();

  // Run quick initial test to populate radar cards
  runDiagnosticTest();

  // Polling loop for status (every 4 seconds)
  setInterval(refreshStatus, 4000);
}

// ============================================================================
// API Calls & Status
// ============================================================================
async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    state.status = data;

    if (data.isRunning) {
      statusDot.className = "status-dot pulsing";
      statusTitle.textContent = `WINWS АКТИВЕН (PID: ${data.pid})`;
      statusDesc.textContent = data.activeStrategy
        ? `Стратегия: ${data.activeStrategy}`
        : "Стратегия: Ручной запуск winws";
    } else {
      statusDot.className = "status-dot stopped";
      statusTitle.textContent = "WINWS ОСТАНОВЛЕН";
      statusDesc.textContent = "Выберите стратегию ниже для запуска";
    }

    // Update service tab state
    if (data.service) {
      const state = data.service.state;
      if (state === "RUNNING") {
        svcStateText.textContent = "🟢 РАБОТАЕТ КАК СЛУЖБА";
        svcStateText.style.color = "var(--accent-green)";
      } else if (state === "STOPPED") {
        svcStateText.textContent = "🟡 СЛУЖБА УСТАНОВЛЕНА, НО ОСТАНОВЛЕНА";
        svcStateText.style.color = "var(--accent-amber)";
      } else {
        svcStateText.textContent = "⚪ НЕ УСТАНОВЛЕНА (Работает как процесс)";
        svcStateText.style.color = "var(--text-muted)";
      }
    }
  } catch (err) {
    console.error("Status fetch failed:", err);
  }
}

async function loadStrategies() {
  try {
    const res = await fetch("/api/strategies");
    const data = await res.json();
    state.strategies = data;
    totalStratCount.textContent = data.length;
    renderStrategies();
  } catch (err) {
    console.error("Strategies load failed:", err);
  }
}

async function loadDomainLists() {
  try {
    const res = await fetch("/api/lists");
    const data = await res.json();
    if (data.generalUser) {
      domainListTextarea.value = data.generalUser.join("\n");
    }
  } catch (err) {
    console.error("Lists load failed:", err);
  }
}

// ============================================================================
// Diagnostic & Radar Testing
// ============================================================================
async function runDiagnosticTest() {
  if (state.isTesting) return;
  state.isTesting = true;

  btnFullTest.disabled = true;
  btnQuickTest.disabled = true;

  // Set visual testing state
  setMetricTesting(cardDiscordGateway, badgeDiscordGateway, valDiscordGateway);
  setMetricTesting(cardDiscordVoice, badgeDiscordVoice, valDiscordVoice);
  setMetricTesting(cardYoutubeWeb, badgeYoutubeWeb, valYoutubeWeb);
  setMetricTesting(cardYoutubeStream, badgeYoutubeStream, valYoutubeStream);

  verdictHeadline.textContent = "Тестирование каналов связи...";
  verdictDetails.textContent = "Проверка TLS хэндшейков и UDP пакетов Discord...";
  verdictIcon.textContent = "⏳";
  verdictBanner.className = "verdict-banner";

  try {
    const res = await fetch("/api/test-connection", { method: "POST" });
    const data = await res.json();

    // 1. Discord Gateway
    const dApi = data.discord.api;
    setMetricResult(
      cardDiscordGateway,
      badgeDiscordGateway,
      valDiscordGateway,
      dApi.status === "ok",
      `${dApi.latency} ms`,
      dApi.status === "ok" ? "ДОСТУПЕН" : "БЛОКИРОВАН"
    );

    // 2. Discord Voice STUN
    const dStun = data.discord.voiceStun;
    setMetricResult(
      cardDiscordVoice,
      badgeDiscordVoice,
      valDiscordVoice,
      dStun.status === "ok",
      dStun.status === "ok" ? `${dStun.latency} ms` : "ТАЙМАУТ",
      dStun.status === "ok" ? "ГОЛОС OK" : "RTC ОШИБКА"
    );

    // 3. YouTube Web
    const yWeb = data.youtube.web;
    setMetricResult(
      cardYoutubeWeb,
      badgeYoutubeWeb,
      valYoutubeWeb,
      yWeb.status === "ok",
      `${yWeb.latency} ms`,
      yWeb.status === "ok" ? "ДОСТУПЕН" : "БЛОКИРОВАН"
    );

    // 4. YouTube Video Stream CDN
    const yCdn = data.youtube.cdn;
    setMetricResult(
      cardYoutubeStream,
      badgeYoutubeStream,
      valYoutubeStream,
      yCdn.status === "ok",
      `${yCdn.latency} ms`,
      yCdn.status === "ok" ? "4K STREAM OK" : "БУФЕРИЗАЦИЯ"
    );

    // Verdict Banner
    verdictHeadline.textContent = data.verdictText;
    verdictDetails.textContent = `Общий индекс проходимости: ${data.overallScore}% (Discord: ${data.discord.score}%, YouTube: ${data.youtube.score}%)`;

    if (data.verdict === "perfect") {
      verdictIcon.textContent = "✅";
      verdictBanner.className = "verdict-banner";
    } else if (data.verdict === "good" || data.verdict === "yt_only" || data.verdict === "discord_only") {
      verdictIcon.textContent = "⚠️";
      verdictBanner.className = "verdict-banner warning";
    } else {
      verdictIcon.textContent = "❌";
      verdictBanner.className = "verdict-banner danger";
    }

    // Refresh strategy cards to update benchmark badges
    renderStrategies();
  } catch (err) {
    verdictHeadline.textContent = "Ошибка при проведении диагностики";
    verdictDetails.textContent = err.message;
    verdictIcon.textContent = "⚠️";
    verdictBanner.className = "verdict-banner danger";
  } finally {
    state.isTesting = false;
    btnFullTest.disabled = false;
    btnQuickTest.disabled = false;
  }
}

function setMetricTesting(card, badge, val) {
  card.className = "metric-card testing";
  badge.className = "metric-badge";
  badge.textContent = "ПРОВЕРКА...";
  val.textContent = "⏳";
}

function setMetricResult(card, badge, val, isOk, latencyText, badgeText) {
  card.className = `metric-card ${isOk ? "ok" : "fail"}`;
  badge.className = `metric-badge ${isOk ? "ok" : "fail"}`;
  badge.textContent = badgeText;
  val.textContent = latencyText;
}

// ============================================================================
// Strategy Management & Switching
// ============================================================================
async function activateStrategy(filename) {
  try {
    const res = await fetch("/api/strategies/activate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename }),
    });
    const data = await res.json();
    if (data.success) {
      await refreshStatus();
      await loadStrategies();
      // Run quick test after 2 seconds to confirm connection
      setTimeout(runDiagnosticTest, 2000);
    } else {
      alert("Ошибка запуска стратегии: " + data.error);
    }
  } catch (err) {
    alert("Ошибка соединения с сервером: " + err.message);
  }
}

async function stopWinws() {
  try {
    await fetch("/api/strategies/stop", { method: "POST" });
    await refreshStatus();
    await loadStrategies();
  } catch (err) {
    alert("Ошибка остановки: " + err.message);
  }
}

function renderStrategies() {
  strategiesGrid.innerHTML = "";

  const query = state.searchQuery.toLowerCase();
  const filter = state.activeFilter;

  const filtered = state.strategies.filter((s) => {
    // Search filter
    if (query && !s.filename.toLowerCase().includes(query) && !s.description.toLowerCase().includes(query)) {
      return false;
    }

    // Category filter
    if (filter === "recommended" && !s.isRecommended) return false;
    if (filter === "voice" && !s.tags.some((t) => t.includes("Discord Voice"))) return false;
    if (filter === "fake" && !s.filename.toUpperCase().includes("FAKE")) return false;
    if (filter === "split" && !s.rawArgs.includes("split")) return false;

    return true;
  });

  if (filtered.length === 0) {
    strategiesGrid.innerHTML = `
      <div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-dim);">
        Стратегии по заданному фильтру не найдены.
      </div>
    `;
    return;
  }

  filtered.forEach((s) => {
    const card = document.createElement("div");
    card.className = `strat-card ${s.isActive ? "active" : ""}`;

    const tagsHtml = s.tags
      .map((t) => `<span class="tag-badge ${t.includes('ТОП') ? 'rec' : ''}">${t}</span>`)
      .join("");

    let benchText = "Еще не тестировалась";
    if (s.lastResult) {
      const r = s.lastResult;
      benchText = `Рейтинг: ${r.overallScore || r.score}% (Голос: ${r.voiceLatency || '--'} ms)`;
    }

    card.innerHTML = `
      <div class="strat-header">
        <span class="strat-title">${s.name}</span>
        ${s.isActive ? '<span class="strat-active-tag">АКТИВНА</span>' : ""}
      </div>

      <div class="strat-desc">${s.description}</div>

      <div class="strat-tags">
        ${tagsHtml}
      </div>

      <div class="strat-footer">
        <span class="strat-bench-pill">${benchText}</span>
        <button class="strat-btn-activate" data-strat="${s.filename}">
          ${s.isActive ? "✓ Работает" : "⚡ Активировать"}
        </button>
      </div>
    `;

    strategiesGrid.appendChild(card);
  });

  // Attach button click handlers
  document.querySelectorAll(".strat-btn-activate").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const strat = e.target.getAttribute("data-strat");
      activateStrategy(strat);
    });
  });
}

// ============================================================================
// Auto-Benchmark Wizard
// ============================================================================
async function startAutoBenchmark() {
  openModal("autoBenchmarkModal");
  const progressBar = document.getElementById("benchProgressBar");
  const percentText = document.getElementById("benchPercentText");
  const statusText = document.getElementById("benchStatusText");
  const resultsList = document.getElementById("benchResultsList");
  const winnerCard = document.getElementById("benchWinnerCard");

  progressBar.style.width = "0%";
  percentText.textContent = "0%";
  statusText.textContent = "Запуск авто-бенчмарка ключевых стратегий...";
  resultsList.innerHTML = "";
  winnerCard.classList.add("hidden");

  try {
    await fetch("/api/benchmark-auto", { method: "POST" });
    if (state.benchmarkInterval) clearInterval(state.benchmarkInterval);
    state.benchmarkInterval = setInterval(pollBenchmarkStatus, 800);
  } catch (err) {
    statusText.textContent = "Ошибка запуска: " + err.message;
  }
}

async function pollBenchmarkStatus() {
  try {
    const res = await fetch("/api/benchmark-auto/status");
    const data = await res.json();

    const progressBar = document.getElementById("benchProgressBar");
    const percentText = document.getElementById("benchPercentText");
    const statusText = document.getElementById("benchStatusText");
    const resultsList = document.getElementById("benchResultsList");
    const winnerCard = document.getElementById("benchWinnerCard");

    progressBar.style.width = `${data.progress}%`;
    percentText.textContent = `${data.progress}%`;

    if (data.isRunning) {
      statusText.textContent = `Тестирование: ${data.currentStrategy}`;
    }

    // Render results list
    resultsList.innerHTML = "";
    (data.results || []).forEach((r) => {
      const el = document.createElement("div");
      el.className = "bench-item";
      el.innerHTML = `
        <span style="font-weight:700; color:#fff;">${r.strategy}</span>
        <div style="display:flex; gap:12px; font-family:var(--font-mono); font-size:11px;">
          <span style="color:${r.voiceOk ? 'var(--accent-green)' : 'var(--accent-red)'};">
            Голос: ${r.voiceLatency} ms
          </span>
          <span style="color:var(--accent-cyan);">
            Ютуб: ${r.ytLatency} ms
          </span>
          <span style="color:#fff; font-weight:800;">
            ${r.overallScore}%
          </span>
        </div>
      `;
      resultsList.appendChild(el);
    });

    if (!data.isRunning && data.winner) {
      clearInterval(state.benchmarkInterval);
      state.benchmarkInterval = null;
      statusText.textContent = "✅ Авто-подбор успешно завершен!";
      progressBar.style.width = "100%";
      percentText.textContent = "100%";

      const w = data.winner;
      winnerCard.classList.remove("hidden");
      document.getElementById("winnerTitle").textContent = w.strategy;
      document.getElementById("winnerStats").textContent =
        `Общий счет: ${w.overallScore}% | Голос: ${w.voiceLatency} ms | YouTube: ${w.ytLatency} ms`;

      document.getElementById("btnApplyWinner").onclick = () => {
        activateStrategy(w.strategy);
        closeModal("autoBenchmarkModal");
      };

      refreshStatus();
      loadStrategies();
    }
  } catch (err) {
    console.error("Benchmark poll failed:", err);
  }
}

// ============================================================================
// Event Listeners
// ============================================================================
function setupEventListeners() {
  // Navigation actions
  btnQuickTest.addEventListener("click", runDiagnosticTest);
  btnFullTest.addEventListener("click", runDiagnosticTest);

  btnRestart.addEventListener("click", () => {
    if (state.status && state.status.activeStrategy) {
      activateStrategy(state.status.activeStrategy);
    } else {
      activateStrategy("general (ALT).bat");
    }
  });

  btnStop.addEventListener("click", stopWinws);

  btnOpenFolder.addEventListener("click", async () => {
    await fetch("/api/open-zapret-folder", { method: "POST" });
  });

  btnStartAutoBenchmark.addEventListener("click", startAutoBenchmark);

  // Tabs switching
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));

      btn.classList.add("active");
      document.getElementById(btn.dataset.tab).classList.add("active");
    });
  });

  // Strategy filters
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      state.activeFilter = chip.dataset.filter;
      renderStrategies();
    });
  });

  stratSearch.addEventListener("input", (e) => {
    state.searchQuery = e.target.value;
    renderStrategies();
  });

  // Domain Lists Editor
  btnSaveDomains.addEventListener("click", async () => {
    const raw = domainListTextarea.value;
    const domains = raw.split("\n").map((d) => d.trim()).filter(Boolean);
    try {
      const res = await fetch("/api/lists/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ listName: "list-general-user", domains }),
      });
      const data = await res.json();
      if (data.success) {
        alert("Список доменов успешно сохранен в list-general-user.txt!");
      }
    } catch (err) {
      alert("Ошибка сохранения: " + err.message);
    }
  });

  // Preset domain buttons
  document.querySelectorAll(".preset-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const presetKey = btn.dataset.preset;
      try {
        const res = await fetch("/api/lists/apply-preset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ presetKey, listName: "list-general-user" }),
        });
        const data = await res.json();
        if (data.success) {
          domainListTextarea.value = data.domains.join("\n");
          alert(`Набор «${presetKey}» добавлен в список!`);
        }
      } catch (err) {
        alert("Ошибка добавления набора: " + err.message);
      }
    });
  });

  // Windows Service Controls
  btnInstallService.addEventListener("click", async () => {
    const strat = state.status?.activeStrategy || "general (ALT).bat";
    if (confirm(`Установить стратегию «${strat}» как автозагружаемую службу Windows?`)) {
      try {
        const res = await fetch("/api/service/install", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: strat }),
        });
        const data = await res.json();
        if (data.success) {
          alert("Служба zapret успешно создана и запущена!");
          refreshStatus();
        } else {
          alert("Ошибка установки службы: " + data.error);
        }
      } catch (err) {
        alert("Ошибка: " + err.message);
      }
    }
  });

  btnUninstallService.addEventListener("click", async () => {
    if (confirm("Вы уверены, что хотите удалить службу zapret?")) {
      try {
        const res = await fetch("/api/service/uninstall", { method: "POST" });
        const data = await res.json();
        if (data.success) {
          alert("Служба zapret успешно удалена.");
          refreshStatus();
        }
      } catch (err) {
        alert("Ошибка: " + err.message);
      }
    }
  });

  // Modal Closers
  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => {
      closeModal(btn.dataset.close);
    });
  });
}

// Helpers
function openModal(id) {
  document.getElementById(id).classList.add("open");
}

function closeModal(id) {
  document.getElementById(id).classList.remove("open");
}

window.addEventListener("DOMContentLoaded", init);
