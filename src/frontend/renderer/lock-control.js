document.getElementById("unlock-button").addEventListener("click", async () => {
  await window.aoeOverlay.setInteractionLocked(false);
});
