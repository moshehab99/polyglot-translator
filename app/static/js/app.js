(function () {
  "use strict";

  const root = document.getElementById("translator");
  const MAX_CHARS = Number(root.dataset.maxChars);
  const AUTO = root.dataset.autoCode;

  const sourceSelect = document.getElementById("source");
  const targetSelect = document.getElementById("target");
  const sourceText = document.getElementById("source-text");
  const output = document.getElementById("output");
  const count = document.getElementById("count");
  const counter = document.getElementById("counter");
  const detected = document.getElementById("detected");
  const swapButton = document.getElementById("swap");
  const copyButton = document.getElementById("copy");
  const copyLabel = document.getElementById("copy-label");
  const clearButton = document.getElementById("clear");
  const translateButton = document.getElementById("translate");
  const translateLabel = document.getElementById("translate-label");
  const spinner = document.getElementById("spinner");
  const scriptButton = document.getElementById("arabic-script");
  const scriptSpinner = document.getElementById("script-spinner");
  const errorBox = document.getElementById("error");

  // Code of the language detected by the server for the current input (auto mode only).
  let detectedCode = null;
  let busy = false;
  // True while the output holds a script conversion (Arabic script of the input, not a
  // translation into the target), so target changes and swap leave it alone.
  let scriptOutput = false;
  let copyTimer = null;

  const ARABIC_SCRIPT = /[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]/;
  const STRONG_LTR = /[A-Za-zÀ-ɏ]/;

  function optionFor(select, code) {
    return Array.from(select.options).find((o) => o.value === code) || null;
  }

  function isRtl(select, code) {
    const option = optionFor(select, code);
    return option ? option.dataset.rtl === "true" : false;
  }

  function nameFor(select, code) {
    const option = optionFor(select, code);
    return option ? option.dataset.name || option.textContent : code;
  }

  /** Direction of free text: first strong character wins, like dir="auto". */
  function guessDirection(text) {
    for (const ch of text) {
      if (ARABIC_SCRIPT.test(ch)) return "rtl";
      if (STRONG_LTR.test(ch)) return "ltr";
    }
    return "ltr";
  }

  function applySourceDirection() {
    const code = sourceSelect.value;
    if (code === AUTO) {
      sourceText.dir = guessDirection(sourceText.value);
      sourceText.lang = detectedCode || "";
    } else {
      sourceText.dir = isRtl(sourceSelect, code) ? "rtl" : "ltr";
      sourceText.lang = code;
    }
  }

  function applyTargetDirection() {
    if (scriptOutput) return;
    const code = targetSelect.value;
    output.dir = isRtl(targetSelect, code) ? "rtl" : "ltr";
    output.lang = code;
  }

  function updateCounter() {
    const length = sourceText.value.length;
    count.textContent = String(length);
    counter.classList.toggle("over", length >= MAX_CHARS);
    clearButton.hidden = length === 0;
    const empty = sourceText.value.trim().length === 0;
    translateButton.disabled = busy || empty;
    scriptButton.disabled = busy || empty;
  }

  function updateSwapState() {
    const source = sourceSelect.value;
    const effectiveSource = source === AUTO ? detectedCode : source;
    // Can't swap before we know what the source language is.
    swapButton.disabled =
      busy || scriptOutput || !effectiveSource || effectiveSource === targetSelect.value;
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function clearError() {
    errorBox.hidden = true;
    errorBox.textContent = "";
  }

  function setOutput(text, isScript = false) {
    output.textContent = text;
    copyButton.disabled = text.length === 0;
    scriptOutput = isScript && text.length > 0;
  }

  /** action: "translate" or "script", the request that is running (ignored when idle). */
  function setBusy(value, action = "translate") {
    busy = value;
    spinner.hidden = !(value && action === "translate");
    scriptSpinner.hidden = !(value && action === "script");
    translateLabel.textContent = value && action === "translate" ? "Translating…" : "Translate";
    sourceSelect.disabled = value;
    targetSelect.disabled = value;
    updateCounter();
    updateSwapState();
  }

  function resetDetection() {
    detectedCode = null;
    detected.textContent = "";
    updateSwapState();
  }

  /** POST JSON. Returns the parsed body, or null after showing the server's error. */
  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    let body = null;
    try {
      body = await response.json();
    } catch (_) {
      body = null;
    }

    if (!response.ok) {
      const detail = body && typeof body.detail === "string" ? body.detail : null;
      showError(detail || `Request failed (${response.status}). Please try again.`);
      return null;
    }
    return body;
  }

  async function translate() {
    if (busy) return;
    const text = sourceText.value.trim();
    if (!text) return;
    if (sourceSelect.value !== AUTO && sourceSelect.value === targetSelect.value) {
      showError("Source and target languages are the same. Pick a different target.");
      return;
    }

    clearError();
    setBusy(true);
    try {
      const body = await postJson("/api/translate", {
        text,
        source: sourceSelect.value,
        target: targetSelect.value,
      });
      if (!body) return;

      setOutput(body.translation);
      output.dir = body.target_rtl ? "rtl" : "ltr";
      output.lang = targetSelect.value;

      if (sourceSelect.value === AUTO) {
        detectedCode = body.detected_source;
        detected.textContent = `Detected: ${nameFor(sourceSelect, detectedCode)}`;
        applySourceDirection();
      } else {
        resetDetection();
      }
      updateSwapState();
    } catch (_) {
      showError("Could not reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  /** Franco-Arabic -> Arabic script: same words, no translation; languages are ignored. */
  async function toArabicScript() {
    if (busy) return;
    const text = sourceText.value.trim();
    if (!text) return;

    clearError();
    setBusy(true, "script");
    try {
      const body = await postJson("/api/arabic-script", { text });
      if (!body) return;

      resetDetection();
      applySourceDirection();
      setOutput(body.result, true);
      output.dir = "rtl";
      output.lang = "arz";
      updateSwapState();
    } catch (_) {
      showError("Could not reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  function swap() {
    const source = sourceSelect.value;
    const effectiveSource = source === AUTO ? detectedCode : source;
    if (!effectiveSource) return;

    const previousTarget = targetSelect.value;
    sourceSelect.value = previousTarget;
    targetSelect.value = effectiveSource;

    const translated = output.textContent;
    if (translated) {
      sourceText.value = translated;
      setOutput("");
    }
    resetDetection();
    applySourceDirection();
    applyTargetDirection();
    updateCounter();
    clearError();
    sourceText.focus();
  }

  function fallbackCopy(text) {
    const helper = document.createElement("textarea");
    helper.value = text;
    helper.setAttribute("readonly", "");
    helper.style.position = "fixed";
    helper.style.opacity = "0";
    document.body.appendChild(helper);
    helper.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (_) {
      ok = false;
    }
    document.body.removeChild(helper);
    return ok;
  }

  async function copy() {
    const text = output.textContent;
    if (!text) return;
    let ok = false;
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        ok = true;
      } catch (_) {
        ok = false;
      }
    }
    if (!ok) ok = fallbackCopy(text);

    copyLabel.textContent = ok ? "Copied!" : "Copy failed";
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => {
      copyLabel.textContent = "Copy";
    }, 1600);
  }

  // --- wiring ---------------------------------------------------------------

  sourceText.addEventListener("input", () => {
    updateCounter();
    if (sourceSelect.value === AUTO) {
      // The old detection no longer applies once the text changes.
      if (detectedCode) resetDetection();
      applySourceDirection();
    }
  });

  sourceText.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      translate();
    }
  });

  sourceSelect.addEventListener("change", () => {
    resetDetection();
    applySourceDirection();
    clearError();
  });

  targetSelect.addEventListener("change", () => {
    applyTargetDirection();
    updateSwapState();
    clearError();
  });

  translateButton.addEventListener("click", translate);
  scriptButton.addEventListener("click", toArabicScript);
  swapButton.addEventListener("click", swap);
  copyButton.addEventListener("click", copy);
  clearButton.addEventListener("click", () => {
    sourceText.value = "";
    setOutput("");
    applyTargetDirection();
    resetDetection();
    clearError();
    updateCounter();
    applySourceDirection();
    sourceText.focus();
  });

  applySourceDirection();
  applyTargetDirection();
  updateCounter();
  updateSwapState();
})();
