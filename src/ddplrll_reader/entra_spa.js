"use strict";

const storageKey = "ddplrll.entra.spa.attempt";
const statusElement = document.getElementById("status");

function base64url(bytes) {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomValue() {
  return base64url(crypto.getRandomValues(new Uint8Array(32)));
}

async function handoff(key, result) {
  const response = await fetch("/_entra/result", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Entra-Handoff": key },
    body: JSON.stringify(result),
    credentials: "omit",
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Local token handoff failed (${response.status}): ${await response.text()}`);
  }
}

async function signIn() {
  let key;
  try {
    if (location.pathname === "/_entra/start") {
      key = location.hash.slice(1);
      history.replaceState(null, "", location.pathname);
      sessionStorage.removeItem(storageKey);
      if (!/^[A-Za-z0-9_-]{43}$/.test(key)) {
        throw new Error("Missing sign-in handoff credential. Restart the Python script.");
      }
      const response = await fetch("/_entra/config", {
        headers: { "X-Entra-Handoff": key },
        credentials: "omit",
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`Could not load sign-in configuration (${response.status}).`);
      }
      const config = await response.json();
      const verifier = randomValue();
      const state = randomValue();
      const challenge = base64url(new Uint8Array(
        await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)),
      ));
      sessionStorage.setItem(storageKey, JSON.stringify({ key, verifier, state, config }));
      const authorizeUrl = new URL(config.authorizeUrl);
      authorizeUrl.search = new URLSearchParams({
        client_id: config.clientId,
        redirect_uri: config.redirectUri,
        response_type: "code",
        response_mode: "query",
        scope: config.scope,
        state,
        code_challenge: challenge,
        code_challenge_method: "S256",
      }).toString();
      statusElement.textContent = "Redirecting to Microsoft Entra...";
      location.replace(authorizeUrl.href);
      return;
    }

    const params = new URLSearchParams(location.search);
    history.replaceState(null, "", location.pathname);
    const saved = sessionStorage.getItem(storageKey);
    sessionStorage.removeItem(storageKey);
    if (!saved) {
      throw new Error("No pending sign-in in this browser tab. Restart the Python script.");
    }
    const attempt = JSON.parse(saved);
    key = attempt.key;
    if (params.getAll("state").length !== 1 || params.get("state") !== attempt.state) {
      throw new Error("OAuth state mismatch. Restart sign-in; no code was redeemed.");
    }
    if (params.has("error")) {
      throw new Error(
        `${params.get("error")}: ${params.get("error_description") || "Sign-in was rejected."}`,
      );
    }
    if (params.getAll("code").length !== 1 || !params.get("code")) {
      throw new Error("Microsoft Entra returned no authorization code.");
    }
    statusElement.textContent = "Acquiring the LRLL API token in your browser...";
    const tokenResponse = await fetch(attempt.config.tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: attempt.config.clientId,
        redirect_uri: attempt.config.redirectUri,
        grant_type: "authorization_code",
        code: params.get("code"),
        code_verifier: attempt.verifier,
        scope: attempt.config.scope,
      }),
      credentials: "omit",
      cache: "no-store",
    });
    const result = await tokenResponse.json();
    if (!tokenResponse.ok || result.error) {
      throw new Error(
        `${result.error || `HTTP ${tokenResponse.status}`}: `
        + `${result.error_description || "Microsoft Entra token acquisition failed."}`,
      );
    }
    if (typeof result.access_token !== "string" || !result.access_token.trim()
        || typeof result.token_type !== "string" || result.token_type.toLowerCase() !== "bearer"
        || !Number.isInteger(result.expires_in) || result.expires_in <= 0
        || typeof result.scope !== "string" || !result.scope.trim()) {
      throw new Error("Microsoft Entra returned an invalid access-token result.");
    }
    await handoff(key, {
      access_token: result.access_token,
      token_type: result.token_type,
      expires_in: result.expires_in,
      scope: result.scope,
    });
    statusElement.textContent = "Signed in. Return to Python; you can close this tab.";
  } catch (error) {
    sessionStorage.removeItem(storageKey);
    const description = error instanceof Error ? error.message : String(error);
    statusElement.textContent = `Sign-in failed: ${description}`;
    if (key) {
      try {
        await handoff(key, { error: "browser_sign_in_failed", error_description: description });
      } catch (handoffError) {
        statusElement.textContent += ` Python could not be notified: ${handoffError.message}`;
      }
    }
  }
}

signIn();
