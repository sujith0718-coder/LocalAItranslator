const textArea = document.getElementById("text");
const charCount = document.getElementById("charCount");
const form = document.getElementById("translateForm");
const button = document.getElementById("translateButton");
const buttonLabel = document.getElementById("buttonLabel");
const spinner = button.querySelector(".spinner");
const languageSelect = document.getElementById("language");
const translationArea = document.getElementById("translationArea");
const outputFooter = document.getElementById("outputFooter");
const providerLabel = document.getElementById("providerLabel");
const copyButton = document.getElementById("copyButton");
const clearButton = document.getElementById("clearButton");
const message = document.getElementById("message");

const MAX_LEN = textArea.maxLength;
const CLIENT_TIMEOUT_MS = Number(form.dataset.timeout) || 60000;

let busy = false;          // blocks duplicate submissions
let timers = [];


function updateCount() {
    charCount.textContent = `${textArea.value.length} / ${MAX_LEN}`;
}

textArea.addEventListener("input", updateCount);


function showMessage(text, kind) {
    message.textContent = text;
    message.className = "message " + (kind || "");
    message.hidden = !text;
}


function setBusy(isBusy) {
    busy = isBusy;
    button.disabled = isBusy;
    button.setAttribute("aria-busy", String(isBusy));
    spinner.hidden = !isBusy;
    buttonLabel.textContent = isBusy ? "Translating..." : "✦ Translate";
}


function clearTimers() {
    timers.forEach(clearTimeout);
    timers = [];
}


function showTranslation(text, provider) {
    translationArea.textContent = "";
    const p = document.createElement("p");
    p.id = "translation";
    p.textContent = text;            // textContent: never interpreted as HTML
    translationArea.appendChild(p);
    providerLabel.textContent = provider || "";
    outputFooter.hidden = false;
}


function clearText() {
    textArea.value = "";
    updateCount();
    textArea.focus();
}

clearButton.addEventListener("click", clearText);


async function copyTranslation() {
    const el = document.getElementById("translation");
    if (!el) {
        return;
    }
    try {
        await navigator.clipboard.writeText(el.textContent);
    } catch (err) {
        // Fallback for browsers without clipboard permission
        const range = document.createRange();
        range.selectNodeContents(el);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        document.execCommand("copy");
        sel.removeAllRanges();
    }
    copyButton.textContent = "Copied!";
    setTimeout(() => { copyButton.textContent = "Copy"; }, 1500);
}

copyButton.addEventListener("click", copyTranslation);


async function translate(event) {
    event.preventDefault();

    if (busy) {
        return;
    }

    const text = textArea.value.trim();
    if (!text) {
        showMessage("Please enter some text.", "error");
        textArea.focus();
        return;
    }

    setBusy(true);
    showMessage("Translating…", "info");

    // Reassure the user if it is taking a while (e.g. free server waking up).
    timers.push(setTimeout(() => showMessage(
        "Still working… the AI is thinking.", "info"), 5000));
    timers.push(setTimeout(() => showMessage(
        "This is taking longer than usual. The free server may be waking up — please keep this page open.", "info"), 15000));

    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), CLIENT_TIMEOUT_MS);
    let cooldown = 0;

    try {
        const response = await fetch("/translate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: text, language: languageSelect.value }),
            signal: controller.signal,
        });

        let data = {};
        try {
            data = await response.json();
        } catch (err) {
            // Non-JSON reply (e.g. proxy error page)
        }

        if (response.ok && data.translation) {
            showTranslation(data.translation, data.provider);
            showMessage("Done ✓", "success");
            setTimeout(() => {
                if (message.classList.contains("success")) { showMessage(""); }
            }, 2500);
        } else if (response.status === 429) {
            showMessage(data.error || "The service is busy. Please try again shortly.", "warning");
            cooldown = Math.min(Number(response.headers.get("Retry-After")) || 5, 30);
        } else if (response.status >= 500) {
            showMessage(data.error || "The service is temporarily unavailable. Please try again.", "warning");
        } else {
            showMessage(data.error || "Something went wrong. Please try again.", "error");
        }
    } catch (err) {
        if (err.name === "AbortError") {
            showMessage("The request took too long. Please try again.", "warning");
        } else {
            showMessage("Could not reach the server. Check your connection and try again.", "error");
        }
    } finally {
        clearTimeout(abortTimer);
        clearTimers();
        if (cooldown > 0) {
            // brief pause after a rate limit so users don't hammer the service
            buttonLabel.textContent = `Try again in ${cooldown}s`;
            spinner.hidden = true;
            const tick = setInterval(() => {
                cooldown -= 1;
                if (cooldown <= 0) {
                    clearInterval(tick);
                    setBusy(false);
                } else {
                    buttonLabel.textContent = `Try again in ${cooldown}s`;
                }
            }, 1000);
        } else {
            setBusy(false);
        }
    }
}

form.addEventListener("submit", translate);

// Ctrl/Cmd + Enter submits from the text box
textArea.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        form.requestSubmit();
    }
});
