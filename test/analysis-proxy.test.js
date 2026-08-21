const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("http");
const { createServer } = require("../serve");

function listen(server) {
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
}

function close(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

test("proxies Python agent SSE responses", async (t) => {
  const agent = http.createServer((req, res) => {
    assert.equal(req.method, "POST");
    assert.equal(req.url, "/analysis/run");
    res.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-store"
    });
    res.end('data: {"type":"completed","stage":"多 Agent 编排","message":"done","data":{"tests":[]}}\n\n');
  });
  const agentPort = await listen(agent);
  t.after(() => close(agent));

  const app = createServer({ agentServiceUrl: `http://127.0.0.1:${agentPort}` });
  const appPort = await listen(app);
  t.after(() => close(app));

  const response = await fetch(`http://127.0.0.1:${appPort}/api/analysis/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ appId: "123", goal: "goal", reviews: [{ id: "r1", rating: 5, text: "great", appId: "123" }] })
  });
  const text = await response.text();

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /text\/event-stream/);
  assert.match(text, /"type":"completed"/);
});

test("returns a structured error when the Python agent service is unavailable", async (t) => {
  const app = createServer({ agentServiceUrl: "http://127.0.0.1:1" });
  const appPort = await listen(app);
  t.after(() => close(app));

  const response = await fetch(`http://127.0.0.1:${appPort}/api/analysis/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ appId: "123", goal: "goal", reviews: [] })
  });
  const payload = await response.json();

  assert.equal(response.status, 502);
  assert.equal(payload.error.code, "AGENT_SERVICE_UNAVAILABLE");
  assert.equal(payload.error.retryable, true);
});

test("imports review JSON through the Node API", async (t) => {
  const app = createServer();
  const appPort = await listen(app);
  t.after(() => close(app));

  const response = await fetch(`http://127.0.0.1:${appPort}/api/reviews/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      fileName: "reviews.json",
      content: JSON.stringify([{ id: "r1", rating: 5, text: "great" }])
    })
  });
  const payload = await response.json();

  assert.equal(response.status, 200);
  assert.equal(payload.import.format, "json");
  assert.match(payload.appId, /^\d{18}$/);
  assert.equal(payload.reviews[0].id, "r1");
});
