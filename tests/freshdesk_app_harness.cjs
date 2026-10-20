// Model-free UI logic regression. Run: node tests/freshdesk_app_harness.cjs
// No browser, provider request or server is started.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {webcrypto} = require("node:crypto");

async function main() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {hidden: true, disabled: false, textContent: "", value: "",
      replaceChildren() {}, appendChild() {}});
    return elements.get(id);
  };
  const storage = new Map();
  let registrations = 0, refreshes = 0, failStatus = null;
  const inserted = [];
  const client = {
    iparams: {get: async () => ({hubzoid_host: "hub.example.test", mcp_path: "/mcp"})},
    data: {get: async name => name === "ticket" ? {ticket: {id: 42}} : {loggedInUser: {id: 9}}},
    interface: {trigger: async (name, args) => { inserted.push({name, args}); }},
    request: {invokeTemplate: async (template, options) => {
      if (failStatus) throw {status: failStatus, response: "refused"};
      const reply = body => ({status: 200, response: JSON.stringify(body)});
      if (options.context.path.endsWith("/register")) {
        registrations++;
        assert.deepEqual(JSON.parse(options.body).grant_types, ["authorization_code", "refresh_token"]);
        return reply({client_id: "public-client"});
      }
      if (template === "hub_token") {
        const params = new URLSearchParams(options.body);
        assert.equal(params.get("grant_type"), "refresh_token");
        refreshes++;
        await new Promise(setImmediate); // overlap simultaneous expired requests
        return reply({access_token: "renewed", refresh_token: "rotated"});
      }
      if (options.context.authorization === "Bearer expired") throw {status: 401, response: "expired"};
      return reply({jsonrpc: "2.0", result: {ok: true}});
    }}
  };
  const sandbox = {URL, URLSearchParams, Uint8Array, TextEncoder, crypto: webcrypto,
    btoa: text => Buffer.from(text, "binary").toString("base64"),
    document: {getElementById: element}, location: {href: "https://app.example.test/app/index.html", origin: "https://app.example.test"},
    localStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value)},
    window: {addEventListener() {}, open: () => ({close() {}})},
    app: {initialized: async () => client}, setTimeout, console};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync("freshdesk-app/app/app.js", "utf8"), sandbox);
  await new Promise(setImmediate);
  await vm.runInContext("connect()", sandbox);
  await vm.runInContext("connect()", sandbox);
  assert.equal(registrations, 1, "sign-in reuses the cached public registration");
  // Simulate a new app frame sharing only non-secret registration storage.
  vm.runInContext("clientId = null", sandbox);
  await vm.runInContext("connect()", sandbox);
  assert.equal(registrations, 1);
  vm.runInContext("accessToken = 'expired'; refreshToken = 'refresh-one'; clientId = 'public-client'", sandbox);
  await vm.runInContext("Promise.all([rpc('tools/list', {}), rpc('tools/list', {})])", sandbox);
  assert.equal(refreshes, 1, "concurrent 401s share one rotating refresh");
  assert.equal(vm.runInContext("refreshToken", sandbox), "rotated");
  assert.deepEqual([...storage.values()], ["public-client"], "browser storage holds no tokens");
  failStatus = 403;
  await assert.rejects(vm.runInContext("request('hub_json', '/mcp', {})", sandbox), /access changed/);
  failStatus = null;
  let claims = 0, acknowledgements = 0;
  const suggestion = {digest: "d1", body: "<unsafe> & text\n\nSecond paragraph", attachments: []};
  sandbox.mockPayload = async (digest, claim, token, expected) => {
    if (digest) { acknowledgements++; assert.equal(token, "opaque"); return {note: "pending"}; }
    if (claim) { assert.equal(expected, "d1"); claims++; return {...suggestion, placement_token: "opaque"}; }
    return suggestion;
  };
  vm.runInContext("payload = mockPayload", sandbox);
  await vm.runInContext("load();", sandbox);
  await vm.runInContext("insert();", sandbox);
  assert.equal(claims, 0, "showing the inline confirmation never claims or inserts");
  assert.equal(inserted.length, 0);
  element("cancel-insert").onclick();
  assert.equal(inserted.length, 0);
  await vm.runInContext("insert();", sandbox);
  await vm.runInContext("confirmInsert();", sandbox);
  assert.equal(claims, 1); assert.equal(acknowledgements, 1);
  assert.equal(inserted[0].name, "click"); assert.equal(inserted[0].args.id, "reply");
  assert.equal(inserted[0].args.text, "<p>&lt;unsafe&gt; &amp; text</p><p>Second paragraph</p>");
  console.log("Freshdesk app: registration reuse, shared refresh, errors, inline confirmation and escaped placement passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
