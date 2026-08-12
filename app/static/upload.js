(() => {
  const form = document.getElementById("upload-form");
  if (!form) return;
  const inputs = Array.from(form.querySelectorAll('input[type="file"]'));
  const selected = document.getElementById("selected-files");
  const analyze = document.getElementById("analyze-button");
  const zone = document.getElementById("drop-zone");

  function showSelection(files) {
    if (!files.length) return;
    selected.hidden = false;
    selected.textContent = `${files.length} file${files.length === 1 ? "" : "s"} selected · ${Array.from(files).slice(0, 3).map(f => f.name).join(", ")}${files.length > 3 ? "…" : ""}`;
    analyze.disabled = false;
  }

  inputs.forEach(input => input.addEventListener("change", () => {
    inputs.filter(other => other !== input).forEach(other => { other.value = ""; });
    showSelection(input.files);
  }));
  ["dragenter", "dragover"].forEach(event => zone.addEventListener(event, e => { e.preventDefault(); zone.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach(event => zone.addEventListener(event, e => { e.preventDefault(); zone.classList.remove("dragging"); }));
  zone.addEventListener("drop", event => {
    const input = inputs[0];
    input.files = event.dataTransfer.files;
    inputs.slice(1).forEach(other => { other.value = ""; });
    showSelection(input.files);
  });
  form.addEventListener("submit", () => {
    analyze.disabled = true;
    analyze.textContent = "Uploading and validating…";
  });
})();
