/* Browser session stays in an HttpOnly cookie; only CSRF lives in memory. */
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const status = byId("status");
  let csrf = null;
  let expiresAt = 0;
  let expiryTimer;
  let handler = null;
  let sdkPromise = null;
  let attempt = 0;
  let busy = false;

  function message(text = "", error = false) {
    status.textContent = text;
    status.classList.toggle("error", error);
  }
  function panel(name, focus = false) {
    ["loading", "verify", "connect", "success"].forEach((key) => {
      byId(`${key}-panel`).hidden = key !== name;
      const step = byId(`step-${key}`);
      if (step) {
        if (key === name) step.setAttribute("aria-current", "step");
        else step.removeAttribute("aria-current");
      }
    });
    byId("reverify-button").hidden = true;
    if (focus && name !== "loading") byId(`${name}-heading`).focus();
  }
  function destroyHandler() {
    const obsolete = handler;
    handler = null;
    if (obsolete) obsolete.destroy();
  }
  function setBusy(value) {
    busy = value;
    byId("connect-button").disabled = value;
    byId("another-button").disabled = value;
    byId("connect-button").textContent = value ? "Connecting…" : "Connect bank account →";
    document.querySelectorAll(".signout-button").forEach((button) => { button.disabled = value; });
  }
  function clearAttempt() {
    attempt += 1;
    destroyHandler();
    setBusy(false);
  }
  function resetSession(text, error = false) {
    clearAttempt();
    clearTimeout(expiryTimer);
    csrf = null;
    expiresAt = 0;
    byId("password").value = "";
    panel("verify", true);
    message(text, error);
  }
  function expireIfNeeded() {
    if (csrf && Date.now() >= expiresAt * 1000) {
      resetSession("Your verification expired. Verify again to continue.", true);
    }
  }
  function acceptSession(data) {
    csrf = data.csrf_token;
    expiresAt = data.expires_at;
    clearTimeout(expiryTimer);
    expiryTimer = setTimeout(expireIfNeeded, Math.max(0, expiresAt * 1000 - Date.now()));
    panel("connect");
    message();
    expireIfNeeded();
  }
  async function request(path, body, protectedRequest = false) {
    const headers = { "Content-Type": "application/json" };
    if (protectedRequest && csrf) headers["X-CSRF-Token"] = csrf;
    const response = await fetch(`/link-account/${path}`, {
      method: body === undefined ? "GET" : "POST", credentials: "same-origin",
      headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }), cache: "no-store",
    });
    if (protectedRequest && response.status === 401) {
      resetSession("Your verification expired. Verify again to continue.", true);
      throw new Error("handled");
    }
    if (protectedRequest && response.status === 403) {
      clearAttempt();
      message("Please refresh and verify again.", true);
      byId("reverify-button").hidden = false;
      throw new Error("handled");
    }
    return response;
  }
  async function loadSession() {
    panel("loading");
    byId("retry-button").hidden = true;
    message("Checking your verification…");
    try {
      const response = await request("session");
      if (!response.ok) throw new Error("connection");
      const data = await response.json();
      if (data.authenticated) acceptSession(data);
      else { panel("verify"); message(); }
    } catch {
      message("We couldn't check your verification. Please try again using a secure connection.", true);
      byId("retry-button").hidden = false;
    }
  }
  byId("verify-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = byId("continue-button");
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = "Verifying…";
    message();
    try {
      const response = await request("session", {
        username: byId("username").value, password: byId("password").value,
      });
      byId("password").value = "";
      if (!response.ok) {
        message(response.status === 401 ? "We couldn't verify those details. Please try again."
          : response.status === 422 ? "Please check your username and password."
            : "We couldn't verify access. Please refresh and use a secure connection.", true);
        byId("password").focus();
        return;
      }
      acceptSession(await response.json());
      byId("connect-heading").focus();
    } catch {
      byId("password").value = "";
      message("We couldn't reach Jarvis. Please try again.", true);
      byId("password").focus();
    } finally {
      button.disabled = false;
      button.textContent = "Continue →";
    }
  });
  function loadPlaid() {
    if (window.Plaid) return Promise.resolve();
    if (sdkPromise) return sdkPromise;
    sdkPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      const timer = setTimeout(() => fail(), 15000);
      function fail() {
        clearTimeout(timer);
        script.remove();
        sdkPromise = null;
        reject(new Error("sdk"));
      }
      script.src = "https://cdn.plaid.com/link/v2/stable/link-initialize.js";
      script.onload = () => {
        clearTimeout(timer);
        if (window.Plaid) resolve(); else fail();
      };
      script.onerror = fail;
      document.head.appendChild(script);
    });
    return sdkPromise;
  }
  async function startLink() {
    expireIfNeeded();
    if (!csrf || busy) return;
    clearAttempt();
    const activeAttempt = attempt;
    setBusy(true);
    message("Preparing your secure bank connection…");
    try {
      const response = await request("token", {}, true);
      if (!response.ok) throw new Error("provider");
      const data = await response.json();
      await loadPlaid();
      if (activeAttempt !== attempt) return;
      let callbackStarted = false;
      handler = window.Plaid.create({
        token: data.link_token,
        onSuccess: async (publicToken, metadata) => {
          if (activeAttempt !== attempt || callbackStarted) return;
          callbackStarted = true;
          message("Connecting your account…");
          try {
            const callback = await request("callback", {
              public_token: publicToken,
              institution_name: metadata.institution ? metadata.institution.name : "",
              accounts: (metadata.accounts || []).map(({ id, name, mask, type, subtype }) => ({ id, name, mask, type, subtype })),
            }, true);
            if (activeAttempt !== attempt) return;
            if (!callback.ok) throw new Error("provider");
            clearAttempt();
            panel("success", true);
            message();
          } catch (error) {
            if (error.message !== "handled" && activeAttempt === attempt) {
              clearAttempt();
              panel("connect", true);
              message("We couldn't connect your account. Please try again.", true);
            }
          }
        },
        onExit: (error) => {
          if (activeAttempt !== attempt) return;
          clearAttempt();
          panel("connect", true);
          message(error ? "We couldn't connect to your bank. Please try again."
            : "Connection cancelled. You can try again when you're ready.", Boolean(error));
        },
      });
      message("Follow the prompts in Plaid to connect your bank.");
      handler.open();
    } catch (error) {
      if (error.message !== "handled" && activeAttempt === attempt) {
        clearAttempt();
        message("We couldn't start your bank connection. Please try again.", true);
      }
    }
  }
  async function signOut() {
    if (busy) return;
    setBusy(true);
    try {
      const response = await request("logout", {}, true);
      if (!response.ok) throw new Error("logout");
      resetSession("You've signed out.");
    } catch (error) {
      if (error.message !== "handled") message("We couldn't sign you out. Please try again.", true);
    } finally { setBusy(false); }
  }
  byId("connect-button").addEventListener("click", startLink);
  byId("another-button").addEventListener("click", () => { panel("connect", true); message(); });
  byId("retry-button").addEventListener("click", loadSession);
  byId("reverify-button").addEventListener("click", () => resetSession("Verify again to continue."));
  document.querySelectorAll(".signout-button").forEach((button) => button.addEventListener("click", signOut));
  window.addEventListener("focus", expireIfNeeded);
  document.addEventListener("visibilitychange", expireIfNeeded);
  loadSession();
})();
