const ageTiers = {
  dark: 1,
  feudal: 2,
  castle: 3,
  imperial: 4,
};

let state;
let technologies = [];
let villagerIconUrl = "";
let flashingEnabled = true;
let remindersPaused = false;
let settingsOpen = false;
let timerAnchor;

function ageTier(age) {
  const match = /^age_([1-4])$/.exec(age || "");
  return match ? Number(match[1]) : 0;
}

function ageLabel(age) {
  const tier = ageTier(age);
  return tier ? "I".repeat(tier) : "?";
}

function parseTimer(value) {
  const match = /^(\d+):(\d{2})$/.exec(value || "");
  return match ? (Number(match[1]) * 60) + Number(match[2]) : null;
}

function formatTimer(seconds) {
  const minutes = Math.floor(Math.max(0, seconds) / 60);
  const remainder = Math.floor(Math.max(0, seconds) % 60);
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function syncTimerAnchor(nextState) {
  const seconds = parseTimer(nextState.session?.estimatedTimer);
  if (seconds === null) return;
  timerAnchor = {
    seconds,
    receivedAt: Date.now(),
    status: nextState.session?.status,
  };
}

function timerLabel() {
  if (!timerAnchor) return state.session?.estimatedTimer || "00:00";
  if (
    state.remindersPaused
    || timerAnchor.status === "paused"
    || timerAnchor.status === "starting"
  ) {
    return formatTimer(timerAnchor.seconds);
  }
  const elapsed = Math.floor((Date.now() - timerAnchor.receivedAt) / 1000);
  return formatTimer(timerAnchor.seconds + elapsed);
}

function techIsAvailable(technology) {
  if (state.availableTechnologies !== undefined) {
    return state.availableTechnologies.includes(technology.key);
  }
  const availableAt = ageTiers[technology.ageAvailable];
  const civilization = (state.civilization || "sis").toLowerCase();
  const researched = new Set(state.researchedTechnologies || []);
  return (
    availableAt
    && availableAt <= ageTier(state.age)
    && (technology.civilization || "sis").toLowerCase() === civilization
    && (technology.prerequisites || []).every((key) => researched.has(key))
  );
}

function renderTechnology(technology, detected, locked) {
  return `
    <div class="technology ${detected.has(technology.key) ? "technology--detected" : ""} ${locked ? "technology--locked" : ""}" title="${technology.displayName}">
      <img src="${technology.iconUrl}" alt="" />
    </div>
  `;
}

function render() {
  const overlay = document.getElementById("overlay");
  const researched = new Set(state.researchedTechnologies || []);
  const detected = new Set(state.detectedTechnologies || []);
  const lockedTechnologies = new Set(state.lockedTechnologies || []);
  const visibleTechnologies = technologies.filter(
    (technology) => (
      (techIsAvailable(technology) || lockedTechnologies.has(technology.key))
      && !researched.has(technology.key)
    ),
  );
  const economyTechnologies = visibleTechnologies.filter(
    (technology) => technology.category === "economy",
  );
  const militaryTechnologies = visibleTechnologies.filter(
    (technology) => technology.category === "military",
  );
  const villagerIdle = state.villagerReminder ?? state.villagerProductionActive === false;
  const paused = state.remindersPaused ?? remindersPaused;
  overlay.className = [
    "overlay",
    !paused && villagerIdle ? "overlay--urgent" : "overlay--quiet",
    !paused && villagerIdle && flashingEnabled ? "overlay--flashing" : "",
    paused ? "overlay--paused" : "",
    "overlay--visible",
  ].filter(Boolean).join(" ");

  overlay.innerHTML = `
    <div class="rail">
      <div class="overlay-controls">
        <div class="drag-area" title="Drag to move"></div>
        <button class="icon-button" id="settings-button" type="button" title="Settings" aria-label="Settings">&#9881;</button>
        <button class="icon-button" id="hide-button" type="button" title="Hide overlay" aria-label="Hide overlay">&minus;</button>
        <button class="icon-button" id="close-button" type="button" title="Close overlay" aria-label="Close overlay">&times;</button>
      </div>
      ${settingsOpen ? `
        <div class="settings-panel">
          <label class="settings-toggle">
            <span>Flash alerts</span>
            <input id="flash-toggle" type="checkbox" ${flashingEnabled ? "checked" : ""}>
          </label>
          <button class="settings-action" id="reset-position-button" type="button">Reset position</button>
          <button class="settings-action" id="developer-console-button" type="button">Developer console</button>
          <button class="settings-action settings-action--primary" id="calibrate-button" type="button">Recalibrate screen</button>
        </div>
      ` : ""}
      <div class="reminder-content">
        <aside class="status-panel">
          <div class="session-status">
            <time class="game-timer" title="Game timer">${timerLabel()}</time>
            <div class="age-marker" title="Current age"><span>Age</span><strong>${ageLabel(state.age)}</strong></div>
          </div>
          <div class="reminder-actions">
            <button class="reminder-action" id="pause-reminders-button" type="button" title="${paused ? "Resume reminders" : "Pause reminders"}" aria-label="${paused ? "Resume reminders" : "Pause reminders"}" aria-pressed="${paused}">${paused ? "&#9654;" : "&#10074;&#10074;"}</button>
            <button class="reminder-action" id="reset-reminders-button" type="button" title="Reset reminder session" aria-label="Reset reminder session">&#8635;</button>
          </div>
          <div class="villager-alert ${villagerIdle ? "villager-alert--idle" : "villager-alert--active"}" title="${villagerIdle ? "Villager production is idle" : "Villager production is active"}">
            <img src="${villagerIconUrl}" alt="" />
          </div>
        </aside>
        <div class="technology-sections">
          <section class="technology-section technology-section--economy">
            <h2>Economy</h2>
            <div class="technology-grid">
              ${economyTechnologies.map((technology) => renderTechnology(technology, detected, lockedTechnologies.has(technology.key))).join("")}
            </div>
          </section>
          <section class="technology-section technology-section--military">
            <h2>Military</h2>
            <div class="technology-grid">
              ${militaryTechnologies.map((technology) => renderTechnology(technology, detected, lockedTechnologies.has(technology.key))).join("")}
            </div>
          </section>
        </div>
      </div>
    </div>
  `;

  document.getElementById("settings-button").addEventListener("click", () => {
    settingsOpen = !settingsOpen;
    render();
  });
  document.getElementById("hide-button").addEventListener("click", () => window.aoeOverlay.hide());
  document.getElementById("close-button").addEventListener("click", () => window.aoeOverlay.close());
  document.getElementById("pause-reminders-button").addEventListener("click", async () => {
    remindersPaused = await window.aoeOverlay.setRemindersPaused(!paused);
    state = { ...state, remindersPaused };
    console.info(`[overlay] reminders ${remindersPaused ? "paused" : "resumed"}`);
    render();
  });
  document.getElementById("reset-reminders-button").addEventListener("click", async (event) => {
    event.currentTarget.disabled = true;
    remindersPaused = await window.aoeOverlay.resetReminders();
    state = { ...state, remindersPaused };
    syncTimerAnchor(state);
    console.info("[overlay] reminder session reset requested");
    render();
  });
  if (settingsOpen) {
    document.getElementById("flash-toggle").addEventListener("change", (event) => {
      window.aoeOverlay.setFlashing(event.currentTarget.checked);
    });
    document.getElementById("reset-position-button").addEventListener("click", () => {
      window.aoeOverlay.resetPosition();
    });
    document.getElementById("developer-console-button").addEventListener("click", () => {
      window.aoeOverlay.openDeveloperConsole();
    });
    document.getElementById("calibrate-button").addEventListener("click", async (event) => {
      event.currentTarget.disabled = true;
      await window.aoeOverlay.calibrate();
    });
  }

  requestAnimationFrame(() => {
    const rail = overlay.querySelector(".rail");
    window.aoeOverlay.resize(rail.scrollHeight + 16);
  });
}

async function start() {
  const bootstrap = await window.aoeOverlay.bootstrap();
  state = bootstrap.state;
  syncTimerAnchor(state);
  technologies = bootstrap.technologies;
  villagerIconUrl = bootstrap.villagerIconUrl;
  flashingEnabled = bootstrap.flashingEnabled;
  remindersPaused = bootstrap.remindersPaused;
  render();

  window.aoeOverlay.onState((nextState) => {
    state = nextState;
    syncTimerAnchor(state);
    remindersPaused = nextState.remindersPaused ?? remindersPaused;
    render();
  });
  window.aoeOverlay.onFlashing((enabled) => {
    flashingEnabled = enabled;
    render();
  });
  window.aoeOverlay.onPaused((paused) => {
    remindersPaused = paused;
    state = { ...state, remindersPaused };
    render();
  });
}

setInterval(() => {
  const timer = document.querySelector(".game-timer");
  if (timer) timer.textContent = timerLabel();
}, 250);

start();
