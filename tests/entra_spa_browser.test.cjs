const assert = require("node:assert/strict");
const { createHash, webcrypto } = require("node:crypto");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");

const source = readFileSync(resolve(__dirname, "../src/ddplrll_reader/entra_spa.js"), "utf8");
const storageKey = "ddplrll.entra.spa.attempt";
const config = {
  authorizeUrl: "https://login.microsoftonline.com/test/oauth2/v2.0/authorize",
  tokenUrl: "https://login.microsoftonline.com/test/oauth2/v2.0/token",
  clientId: "test-client",
  scope: "api://test-api/access_as_user",
  redirectUri: "http://localhost:5173/callback",
};
const token = {
  access_token: "synthetic-test-token",
  token_type: "Bearer",
  expires_in: 3600,
  scope: config.scope,
  refresh_token: "must-not-send",
  id_token: "must-not-send",
};
const attempt = {
  key: "k".repeat(43),
  state: "expected-state",
  verifier: "v".repeat(43),
  config,
};

function response(value, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => value,
    text: async () => JSON.stringify(value),
  };
}

async function browser(url, saved = attempt, tokenReply = response(token)) {
  const storage = new Map(saved ? [[storageKey, JSON.stringify(saved)]] : []);
  const location = new URL(url);
  const status = { textContent: "" };
  const requests = [];
  const history = [];
  let redirect;
  const context = {
    URL,
    URLSearchParams,
    Uint8Array,
    TextEncoder,
    crypto: webcrypto,
    btoa: value => Buffer.from(value, "binary").toString("base64"),
    document: { getElementById: () => status },
    location: {
      pathname: location.pathname,
      search: location.search,
      hash: location.hash,
      replace: url => { redirect = url; },
    },
    history: { replaceState: (state, title, url) => history.push(url) },
    sessionStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (url === "/_entra/config") return response(config);
      if (url === "/_entra/result") return response({ accepted: true });
      if (url === config.tokenUrl) {
        if (tokenReply instanceof Error) throw tokenReply;
        return tokenReply;
      }
      throw new Error(`Unexpected test request: ${url}`);
    },
  };
  await runInNewContext(source, context);
  return { storage, status, requests, history, redirect };
}

test("start creates random state and S256 PKCE with exact scope and callback", async () => {
  const result = await browser(`http://localhost:5173/_entra/start#${attempt.key}`, null);
  const saved = JSON.parse(result.storage.get(storageKey));
  const authorize = new URL(result.redirect);
  assert.match(saved.verifier, /^[A-Za-z0-9_-]{43}$/);
  assert.match(saved.state, /^[A-Za-z0-9_-]{43}$/);
  assert.notEqual(saved.state, saved.verifier);
  assert.equal(saved.key, attempt.key);
  assert.equal(authorize.searchParams.get("code_challenge_method"), "S256");
  assert.equal(
    authorize.searchParams.get("code_challenge"),
    createHash("sha256").update(saved.verifier).digest("base64url"),
  );
  assert.equal(authorize.searchParams.get("state"), saved.state);
  assert.equal(authorize.searchParams.get("scope"), config.scope);
  assert.equal(authorize.searchParams.get("redirect_uri"), config.redirectUri);
  assert.equal(authorize.searchParams.get("client_id"), config.clientId);
  assert.equal(authorize.searchParams.get("response_type"), "code");
  assert.deepEqual(result.history, ["/_entra/start"]);
  assert.equal(result.requests[0].options.headers["X-Entra-Handoff"], attempt.key);
});

test("callback redeems code in browser and sends only access-token fields locally", async () => {
  const result = await browser(
    "http://localhost:5173/callback?code=synthetic-code&state=expected-state",
  );
  assert.equal(result.requests.length, 2);
  const exchange = result.requests[0];
  assert.equal(exchange.url, config.tokenUrl);
  assert.equal(exchange.options.body.get("grant_type"), "authorization_code");
  assert.equal(exchange.options.body.get("code_verifier"), attempt.verifier);
  assert.equal(exchange.options.body.get("redirect_uri"), config.redirectUri);
  assert.equal(exchange.options.body.get("scope"), config.scope);
  assert.equal(exchange.options.body.get("code"), "synthetic-code");
  assert.equal(exchange.options.body.has("client_secret"), false);
  assert.equal(exchange.options.headers.Origin, undefined);
  const handoff = result.requests[1];
  assert.equal(handoff.url, "/_entra/result");
  assert.deepEqual(JSON.parse(handoff.options.body), {
    access_token: token.access_token,
    token_type: token.token_type,
    expires_in: token.expires_in,
    scope: token.scope,
  });
  assert.equal(handoff.options.headers["X-Entra-Handoff"], attempt.key);
  assert.equal(result.storage.has(storageKey), false);
  assert.deepEqual(result.history, ["/callback"]);
  assert.match(result.status.textContent, /^Signed in/);
});

for (const query of [
  "?code=test&state=wrong",
  "?code=test",
  "?code=test&state=expected-state&state=expected-state",
  "?error=access_denied&state=wrong",
  "?state=expected-state",
  "?code=a&code=b&state=expected-state",
]) {
  test(`rejects invalid callback without redeeming a code: ${query}`, async () => {
    const result = await browser(`http://localhost:5173/callback${query}`);
    assert.equal(result.requests.length, 1);
    assert.equal(result.requests[0].url, "/_entra/result");
    assert.equal(JSON.parse(result.requests[0].options.body).error, "browser_sign_in_failed");
    assert.equal(result.storage.has(storageKey), false);
    assert.match(result.status.textContent, /^Sign-in failed/);
  });
}

test("reports Entra authorization errors after state validation", async () => {
  const result = await browser(
    "http://localhost:5173/callback?error=access_denied"
    + "&error_description=synthetic+denial&state=expected-state",
  );
  const failure = JSON.parse(result.requests[0].options.body);
  assert.match(failure.error_description, /access_denied: synthetic denial/);
});

for (const reply of [
  response({ error: "invalid_client", error_description: "synthetic rejection" }, 400),
  response({ id_token: "not-an-access-token" }),
  response({ ...token, expires_in: 0 }),
  new Error("synthetic network failure"),
]) {
  test("token failures notify Python and never hand off a success-shaped result", async () => {
    const result = await browser(
      "http://localhost:5173/callback?code=test&state=expected-state", attempt, reply,
    );
    assert.equal(result.requests.length, 2);
    const failure = JSON.parse(result.requests[1].options.body);
    assert.equal(failure.error, "browser_sign_in_failed");
    assert.equal(failure.access_token, undefined);
    assert.equal(result.storage.has(storageKey), false);
  });
}

test("missing session produces an explicit error without sending any token request", async () => {
  const result = await browser(
    "http://localhost:5173/callback?code=test&state=expected-state", null,
  );
  assert.equal(result.requests.length, 0);
  assert.match(result.status.textContent, /No pending sign-in/);
});
