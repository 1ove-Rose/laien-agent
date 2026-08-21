const http = require("http");
const fs = require("fs");
const path = require("path");
const { ApiError, collectReviews } = require("./lib/apple-reviews");
const { cleanReviews } = require("./lib/review-cleaner");
const { importReviews } = require("./lib/review-importer");

const port = Number(process.env.PORT || 8765);
const defaultAgentServiceUrl = process.env.AGENT_SERVICE_URL || "http://127.0.0.1:8770";
const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8"
};

function sendJson(res, status, payload) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store"
  });
  res.end(JSON.stringify(payload));
}

function readJsonBody(req, maxBytes = 2 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let tooLarge = false;

    req.on("data", (chunk) => {
      if (tooLarge) return;
      size += chunk.length;
      if (size > maxBytes) {
        tooLarge = true;
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      if (tooLarge) {
        reject(new ApiError("REQUEST_TOO_LARGE", "请求内容超过允许上限。", { status: 413 }));
        return;
      }
      try {
        resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {});
      } catch {
        reject(new ApiError("INVALID_JSON", "请求内容必须是有效 JSON。", { status: 400 }));
      }
    });
    req.on("error", reject);
  });
}

function sendApiError(res, error) {
  const apiError = error instanceof ApiError
    ? error
    : new ApiError("INTERNAL_ERROR", "服务器处理请求时发生错误。", { status: 500 });

  if (!(error instanceof ApiError)) console.error(error);
  sendJson(res, apiError.status, {
    error: {
      code: apiError.code,
      message: apiError.message,
      retryable: apiError.retryable
    }
  });
}

async function proxyAgentRun(req, res, agentServiceUrl) {
  if (req.method !== "POST") {
    sendJson(res, 405, {
      error: { code: "METHOD_NOT_ALLOWED", message: "该接口仅支持 POST。", retryable: false }
    });
    return;
  }

  let body;
  try {
    body = await readJsonBody(req);
  } catch (error) {
    sendApiError(res, error);
    return;
  }

  const controller = new AbortController();
  res.on("close", () => controller.abort());

  let upstream;
  try {
    upstream = await fetch(`${agentServiceUrl.replace(/\/$/, "")}/analysis/run`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream"
      },
      body: JSON.stringify(body),
      signal: controller.signal
    });
  } catch (error) {
    if (controller.signal.aborted) return;
    sendJson(res, 502, {
      error: {
        code: "AGENT_SERVICE_UNAVAILABLE",
        message: "Python 多 Agent 服务不可用，请确认已启动 agent_service。",
        stage: "多 Agent 编排",
        retryable: true
      }
    });
    return;
  }

  const contentType = upstream.headers.get("content-type") || "";
  if (!upstream.ok || !contentType.includes("text/event-stream")) {
    let payload;
    try {
      payload = await upstream.json();
    } catch {
      payload = {
        error: {
          code: "AGENT_RUN_FAILED",
          message: `Python 多 Agent 服务返回 HTTP ${upstream.status}。`,
          stage: "多 Agent 编排",
          retryable: upstream.status >= 500
        }
      };
    }
    sendJson(res, upstream.ok ? 502 : upstream.status, payload);
    return;
  }

  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-store",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no"
  });

  const reader = upstream.body?.getReader();
  if (!reader) {
    res.end();
    return;
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!res.write(Buffer.from(value))) {
        await new Promise((resolve) => res.once("drain", resolve));
      }
    }
  } catch (error) {
    if (!controller.signal.aborted) {
      res.write(`data: ${JSON.stringify({
        type: "error",
        stage: "多 Agent 编排",
        message: "多 Agent 流式响应中断。",
        data: {
          error: {
            code: "AGENT_STREAM_INTERRUPTED",
            message: "多 Agent 流式响应中断。",
            stage: "多 Agent 编排",
            retryable: true
          }
        }
      })}\n\n`);
    }
  } finally {
    res.end();
  }
}

async function handleApi(req, res, pathname, agentServiceUrl) {
  if (pathname === "/api/analysis/run") {
    await proxyAgentRun(req, res, agentServiceUrl);
    return;
  }

  if (req.method !== "POST") {
    sendJson(res, 405, {
      error: { code: "METHOD_NOT_ALLOWED", message: "该接口仅支持 POST。", retryable: false }
    });
    return;
  }

  try {
    const body = await readJsonBody(req, pathname === "/api/reviews/import" ? 3 * 1024 * 1024 : 2 * 1024 * 1024);
    if (pathname === "/api/reviews/collect") {
      sendJson(res, 200, await collectReviews(body));
      return;
    }
    if (pathname === "/api/reviews/clean") {
      sendJson(res, 200, cleanReviews(body));
      return;
    }
    if (pathname === "/api/reviews/import") {
      sendJson(res, 200, importReviews(body));
      return;
    }
    sendJson(res, 404, {
      error: { code: "API_NOT_FOUND", message: "接口不存在。", retryable: false }
    });
  } catch (error) {
    sendApiError(res, error);
  }
}

function createServer({ root = process.cwd(), agentServiceUrl = defaultAgentServiceUrl } = {}) {
  return http.createServer(async (req, res) => {
    let pathname;
    try {
      pathname = new URL(req.url, `http://${req.headers.host || "127.0.0.1"}`).pathname;
    } catch {
      res.writeHead(400);
      res.end("Bad request");
      return;
    }
    if (pathname.startsWith("/api/")) {
      await handleApi(req, res, pathname, agentServiceUrl);
      return;
    }

    const requestedPath = pathname === "/" ? "/index.html" : pathname;
    const filePath = path.normalize(path.join(root, decodeURIComponent(requestedPath)));
    const relativePath = path.relative(root, filePath);

    if (relativePath.startsWith("..") || path.isAbsolute(relativePath)) {
      res.writeHead(403);
      res.end("Forbidden");
      return;
    }

    fs.readFile(filePath, (error, data) => {
      if (error) {
        res.writeHead(404);
        res.end("Not found");
        return;
      }

      res.writeHead(200, {
        "Content-Type": types[path.extname(filePath)] || "text/plain; charset=utf-8"
      });
      res.end(data);
    });
  });
}

if (require.main === module) {
  const server = createServer();
  server.listen(port, "127.0.0.1", () => {
    console.log(`Preview server running at http://127.0.0.1:${port}/`);
  });
}

module.exports = {
  createServer,
  proxyAgentRun,
  sendJson
};
