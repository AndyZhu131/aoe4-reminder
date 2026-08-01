const log = document.getElementById("log");
const levelButtons = [...document.querySelectorAll(".log-level")];
let activeLevel = "info";
let entries = [];

function appendText(parent, value, className) {
  const element = document.createElement("span");
  element.textContent = value;
  if (className) element.className = className;
  parent.append(element);
}

function formatEntry(entry) {
  const line = document.createElement("div");
  line.className = "log-line";
  appendText(line, `[${entry.timestamp}] ${entry.source}: `, "log-prefix");

  const techMatch = /^TECH_DETECTED: key=([^\s]+) (.+)$/.exec(entry.message);
  if (techMatch) {
    line.classList.add("log-line--technology");
    appendText(line, "TECH DETECTED: ", "log-event");
    appendText(line, techMatch[1], "log-technology-name");
    appendText(line, ` ${techMatch[2]}`);
    return line;
  }

  if (entry.message.startsWith("AGE:")) {
    line.classList.add("log-line--age");
    appendText(line, entry.message);
    return line;
  }

  if (entry.message.startsWith("TIME:")) {
    line.classList.add("log-line--timer");
    appendText(line, entry.message);
    return line;
  }

  if (entry.message.startsWith("VILLAGER_REMINDER: fired")) {
    line.classList.add("log-line--villager-alert");
    appendText(line, "VILLAGER REMINDER FIRED: no villager detected", "log-event");
    const food = /food=(.+)$/.exec(entry.message);
    if (food) appendText(line, ` (food=${food[1]})`);
    return line;
  }

  if (entry.message.startsWith("ERROR:")) {
    line.classList.add("log-line--error");
    appendText(line, entry.message, "log-event");
    return line;
  }

  appendText(line, entry.message);
  return line;
}

function render() {
  log.replaceChildren();
  entries
    .filter((entry) => (entry.level || "info") === activeLevel)
    .forEach((entry) => log.append(formatEntry(entry)));
  log.scrollTop = log.scrollHeight;
}

function append(entry) {
  entries.push(entry);
  if ((entry.level || "info") === activeLevel) {
    log.append(formatEntry(entry));
    log.scrollTop = log.scrollHeight;
  }
}

for (const button of levelButtons) {
  button.addEventListener("click", () => {
    activeLevel = button.dataset.level;
    levelButtons.forEach((candidate) => {
      candidate.classList.toggle("is-active", candidate === button);
    });
    render();
  });
}

async function start() {
  const bootstrapEntries = await window.aoeOverlay.developerConsoleBootstrap();
  bootstrapEntries.forEach(append);
  window.aoeOverlay.onDeveloperConsoleLog(append);
}

start();
