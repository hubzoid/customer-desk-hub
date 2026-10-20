"use strict";
// Per-person OAuth + PKCE. No API key or static service credential is shipped.
// Freshworks' request proxy avoids cross-origin MCP transport requirements.
let client, params, resource, accessToken = null, refreshToken = null, clientId = null, refreshing = null;
let pendingAuth = null, requestId = 1, shown = null, pendingReplace = null;
const el = id => document.getElementById(id);
const status = message => { el("status").textContent = message; };
const b64 = data => btoa(String.fromCharCode(...new Uint8Array(data))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

function decodeResponse(response) {
  const raw = typeof response.response === "string" ? response.response : JSON.stringify(response.response);
  try { return JSON.parse(raw); } catch (_) {
    const packets = raw.split(/\r?\n/).filter(line => line.startsWith("data: ")).map(line => JSON.parse(line.slice(6)));
    if (!packets.length) throw new Error("Hubzoid returned an unsupported response. Nothing inserted.");
    return packets[packets.length - 1];
  }
}
async function request(template, path, body, authorization = "") {
  try {
    const response = await client.request.invokeTemplate(template, {
      context: {path, authorization}, body: typeof body === "string" ? body : JSON.stringify(body), cache: false
    });
    if (Number(response.status) >= 400) throw response;
    return decodeResponse(response);
  } catch (failure) {
    const code = Number(failure.status);
    const error = new Error(code === 401 ? "Hubzoid sign-in expired. Sign in again." : code === 403 ?
      "Hubzoid access changed. Check your grants or sign in again." :
      failure.message || "Hubzoid request failed. Check the connection and sign-in, then retry.");
    error.status = code;
    throw error;
  }
}
function acceptToken(token) {
  if (!token.access_token || !token.refresh_token) throw new Error("Hubzoid returned incomplete sign-in credentials. Sign in again.");
  accessToken = token.access_token; refreshToken = token.refresh_token;
}
async function refresh() {
  if (!refreshing) refreshing = (async () => {
    try {
      if (!refreshToken || !clientId) throw new Error("Sign in to Hubzoid again.");
      acceptToken(await request("hub_token", params.mcp_path + "/oauth/token", new URLSearchParams({
        grant_type: "refresh_token", refresh_token: refreshToken, client_id: clientId, resource}).toString()));
    } catch (error) { accessToken = null; refreshToken = null; el("load").disabled = true; throw error; }
  })().finally(() => { refreshing = null; });
  // The SDK rotates refresh tokens and revokes a grant on reuse. Share one
  // promise across concurrent requests; tokens never enter browser storage.
  return refreshing;
}
async function rpc(method, args) {
  if (!accessToken) throw new Error("Sign in to Hubzoid first.");
  const data = {jsonrpc: "2.0", id: requestId++, method, params: args};
  const attempted = accessToken;
  let response;
  try { response = await request("hub_json", params.mcp_path, data, "Bearer " + attempted); }
  catch (error) {
    if (error.status !== 401) throw error;
    if (accessToken === attempted) await refresh();
    response = await request("hub_json", params.mcp_path, data, "Bearer " + accessToken);
  }
  if (response.error) throw new Error(response.error.message || "MCP request refused");
  return response.result;
}
async function context() {
  const [ticket, user] = await Promise.all([client.data.get("ticket"), client.data.get("loggedInUser")]);
  return {ticket_id: String(ticket.ticket.id), agent_id: String(user.loggedInUser.id)};
}
async function payload(placedDigest, claim = false, placementToken = null, expectedDigest = null) {
  const args = await context();
  if (placedDigest) args.placed_digest = placedDigest;
  if (claim) args.claim = true;
  if (expectedDigest) args.expected_digest = expectedDigest;
  if (placementToken) args.placement_token = placementToken;
  return tool("desk_editor_payload", args);
}
async function tool(name, args) {
  const response = await rpc("tools/call", {name, arguments: args});
  if (response.isError) throw new Error("Hubzoid refused this tool call.");
  const text = (response.content || []).filter(c => c.type === "text").map(c => c.text).join("\n");
  const data = JSON.parse(text);
  if (data.error) throw new Error(data.message || data.error);
  return data;
}
async function connect() {
  const popup = window.open("about:blank", "hubzoid-sign-in", "width=540,height=740");
  if (!popup) throw new Error("Allow a sign-in popup, then try again.");
  const redirect = new URL("callback.html", location.href).href.split("?")[0];
  const verifier = b64(crypto.getRandomValues(new Uint8Array(32)));
  const state = b64(crypto.getRandomValues(new Uint8Array(24)));
  const challenge = b64(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  try {
    const cacheKey = "customer-desk-client:" + resource + ":" + redirect;
    try { clientId = clientId || localStorage.getItem(cacheKey); } catch (_) { /* storage may be disabled */ }
    if (!clientId) {
      const registration = await request("hub_json", params.mcp_path + "/oauth/register", {
        client_name: "Customer Desk Freshdesk editor", redirect_uris: [redirect], token_endpoint_auth_method: "none",
        grant_types: ["authorization_code", "refresh_token"], response_types: ["code"]
      });
      if (!registration.client_id) throw new Error("Public-client registration failed.");
      clientId = registration.client_id;
      try { localStorage.setItem(cacheKey, clientId); } catch (_) { /* in-memory reuse still works */ }
    }
    pendingAuth = {popup, redirect, verifier, state, clientId};
    const url = new URL(resource + "/oauth/authorize");
    url.search = new URLSearchParams({response_type: "code", client_id: clientId, redirect_uri: redirect,
      code_challenge: challenge, code_challenge_method: "S256", state, scope: "hub:access", resource});
    popup.location = url.href;
    status("Finish Hubzoid sign-in and consent in the popup.");
  } catch (error) { popup.close(); throw error; }
}
window.addEventListener("message", async event => {
  if (!pendingAuth || event.origin !== location.origin || event.source !== pendingAuth.popup || !event.data || event.data.kind !== "hubzoid-oauth") return;
  const auth = pendingAuth; pendingAuth = null;
  try {
    const query = new URLSearchParams(event.data.query);
    if (query.get("state") !== auth.state || !query.get("code")) throw new Error("Sign-in cancelled or state mismatch.");
    const token = await request("hub_token", params.mcp_path + "/oauth/token", new URLSearchParams({grant_type: "authorization_code",
      code: query.get("code"), code_verifier: auth.verifier, client_id: auth.clientId, redirect_uri: auth.redirect, resource}).toString());
    acceptToken(token);
    await rpc("initialize", {protocolVersion: "2025-03-26", capabilities: {}, clientInfo: {name: "customer-desk-editor", version: "1.0.0"}});
    el("load").disabled = false;
    status("Signed in. Show the suggestion for this ticket. Account linking and current grants are checked on every request.");
  } catch (error) { accessToken = null; refreshToken = null; status(error.message); }
});
async function load() {
  pendingReplace = null; el("confirm-panel").hidden = true;
  shown = await payload();
  el("suggestion").value = shown.body || "";
  el("insert").disabled = !shown.body;
  el("attachments").replaceChildren();
  for (const attachment of shown.attachments || []) {
    const button = document.createElement("button");
    button.textContent = "Download " + attachment.name + ", then attach in Freshdesk";
    button.onclick = async () => {
      try {
        const downloaded = await tool("desk_editor_attachment", {...await context(), sha256: attachment.sha256});
        const bytes = Uint8Array.from(atob(downloaded.base64), c => c.charCodeAt(0));
        const url = URL.createObjectURL(new Blob([bytes], {type: downloaded.media_type}));
        const link = document.createElement("a"); link.href = url; link.download = downloaded.name; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
        status(downloaded.note);
      } catch (error) { status(error.message); }
    };
    el("attachments").appendChild(button);
  }
  status(shown.note || shown.state);
}
async function insert() {
  // Operator action only. No app-open listener writes to the editor.
  const latest = await payload();
  if (!shown || latest.digest !== shown.digest || !latest.body) throw new Error("Suggestion changed or was already placed. Reload it first.");
  const attachmentWarning = (latest.attachments || []).length ? " Download and manually attach the listed PDFs before sending. Body placement does not attach them." : "";
  pendingReplace = latest;
  el("confirm-warning").textContent = "Replace the reply editor text with this suggestion? Existing text, including a human draft, will be lost. Cancel to preserve it. Nothing will be sent." + attachmentWarning;
  el("confirm-panel").hidden = false;
}
function draftHtml(body) {
  const escaped = body.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  return escaped.split(/\n\s*\n/).map(p => "<p>" + p.replace(/\n/g, "<br>") + "</p>").join("");
}
async function confirmInsert() {
  const latest = pendingReplace;
  pendingReplace = null; el("confirm-panel").hidden = true;
  if (!latest) throw new Error("Show the suggestion and confirm replacement first.");
  const checked = await payload(null, true, null, latest.digest);
  if (checked.digest !== latest.digest || !checked.body) throw new Error("Ticket changed during confirmation. Nothing inserted.");
  await client.interface.trigger("click", {id: "reply", text: draftHtml(checked.body)});
  const ack = await payload(checked.digest, false, checked.placement_token);
  el("insert").disabled = true;
  status(ack.note + " Review and edit in Freshdesk. Hubzoid has not claimed persistence or sent anything.");
}
app.initialized().then(async instance => {
  client = instance; params = await client.iparams.get();
  if (!/^[a-zA-Z0-9.-]+$/.test(params.hubzoid_host) || !/^\/(?:b\/[a-zA-Z0-9._-]+\/)?mcp$/.test(params.mcp_path)) throw new Error("Administrator: configure a valid HTTPS hostname and MCP path.");
  resource = "https://" + params.hubzoid_host + params.mcp_path;
  el("cancel-insert").onclick = () => { pendingReplace = null; el("confirm-panel").hidden = true; status("Replacement cancelled. Existing editor text preserved."); };
  for (const [id, action] of [["connect", connect], ["load", load], ["insert", insert], ["confirm-insert", confirmInsert]]) {
    el(id).onclick = () => action().catch(error => status(error.message));
  }
}).catch(error => status(error.message));
