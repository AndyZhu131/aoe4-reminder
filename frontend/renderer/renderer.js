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
let settingsOpen = false;

function ageTier(age) {
  const match = /^age_([1-4])$/.exec(age || "");
  return match ? Number(match[1]) : 0;
}

function ageLabel(age) {
  const tier = ageTier(age);
  return tier ? "I".repeat(tier) : "?";
}

function timerLabel() {
  return state.session?.estimatedTimer || "--:--";
}

function techIsAvailable(technology) {
  const availableAt = ageTiers[technology.ageAvailable];
  const civilization = (state.civilization || "sis").toLowerCase();
  return (
    availableAt
    && availableAt <= ageTier(state.age)
    && (technology.civilization || "sis").toLowerCase() === civilization
  );
}

function renderTechnology(technology, inProgress) {
  return `
    <div class="technology ${inProgress.has(technology.key) ? "technology--active" : ""}" title="${technology.displayName}">
      <img src="${technology.iconUrl}" alt="" />
    </div>
  `;
}

function render() {
  const overlay = document.getElementById("overlay");
  const researched = new Set(state.researchedTechnologies || []);
  const inProgress = new Set(state.inProgressTechnologies || []);
  const availableTechnologies = technologies.filter(
    (technology) => techIsAvailable(technology) && !researched.has(technology.key),
  );
  const economyTechnologies = availableTechnologies.filter(
    (technology) => technology.category === "economy",
  );
  const militaryTechnologies = availableTechnologies.filter(
    (technology) => technology.category === "military",
  );
  const villagerIdle = state.villagerProductionActive === false;
  overlay.className = [
    "overlay",
    villagerIdle ? "overlay--urgent" : "overlay--quiet",
    villagerIdle && flashingEnabled ? "overlay--flashing" : "",
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
          <button class="settings-action settings-action--primary" id="calibrate-button" type="button">Recalibrate screen</button>
        </div>
      ` : ""}
      <div class="session-status">
        <time class="game-timer" title="Game timer">${timerLabel()}</time>
        <div class="age-marker" title="Current age"><span>Age</span><strong>${ageLabel(state.age)}</strong></div>
      </div>
      ${villagerIdle ? `
        <div class="villager-alert" title="Villager production is idle">
          <img src="${villagerIconUrl}" alt="" />
        </div>
      ` : ""}
      <div class="technology-sections">
        <section class="technology-section technology-section--economy">
          <h2>Economy</h2>
          <div class="technology-grid">
            ${economyTechnologies.map((technology) => renderTechnology(technology, inProgress)).join("")}
          </div>
        </section>
        <section class="technology-section technology-section--military">
          <h2>Military</h2>
          <div class="technology-grid">
            ${militaryTechnologies.map((technology) => renderTechnology(technology, inProgress)).join("")}
          </div>
        </section>
      </div>
    </div>
  `;

  document.getElementById("settings-button").addEventListener("click", () => {
    settingsOpen = !settingsOpen;
    render();
  });
  document.getElementById("hide-button").addEventListener("click", () => window.aoeOverlay.hide());
  document.getElementById("close-button").addEventListener("click", () => window.aoeOverlay.close());
  if (settingsOpen) {
    document.getElementById("flash-toggle").addEventListener("change", (event) => {
      window.aoeOverlay.setFlashing(event.currentTarget.checked);
    });
    document.getElementById("reset-position-button").addEventListener("click", () => {
      window.aoeOverlay.resetPosition();
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
  technologies = bootstrap.technologies;
  villagerIconUrl = bootstrap.villagerIconUrl;
  flashingEnabled = bootstrap.flashingEnabled;
  render();

  window.aoeOverlay.onState((nextState) => {
    state = nextState;
    render();
  });
  window.aoeOverlay.onFlashing((enabled) => {
    flashingEnabled = enabled;
    render();
  });
}

start();
