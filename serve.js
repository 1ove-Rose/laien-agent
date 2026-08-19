const http = require("http");
const fs = require("fs");
const path = require("path");
const { ApiError, collectReviews } = require("./lib/apple-reviews");
const { cleanReviews } = require("./lib/review-cleaner");

const root = process.cwd();
const port = Number(process.env.PORT || 8765);
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

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let tooLarge = false;

    req.on("data", (chunk) => {
      if (tooLarge) return;
      size += chunk.length;
      if (size > 2 * 1024 * 1024) {
        tooLarge = true;
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      if (tooLarge) {
        reject(new ApiError("REQUEST_TOO_LARGE", "请求内容不能超过 2 MB。", { status: 413 }));
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

async function handleApi(req, res, pathname) {
  if (req.method !== "POST") {
    sendJson(res, 405, {
      error: { code: "METHOD_NOT_ALLOWED", message: "该接口仅支持 POST。", retryable: false }
    });
    return;
  }

  try {
    const body = await readJsonBody(req);
    if (pathname === "/api/reviews/collect") {
      sendJson(res, 200, await collectReviews(body));
      return;
    }
    if (pathname === "/api/reviews/clean") {
      sendJson(res, 200, cleanReviews(body));
      return;
    }
    sendJson(res, 404, {
      error: { code: "API_NOT_FOUND", message: "接口不存在。", retryable: false }
    });
  } catch (error) {
    sendApiError(res, error);
  }
}

const server = http.createServer(async (req, res) => {
  let pathname;
  try {
    pathname = new URL(req.url, `http://${req.headers.host || "127.0.0.1"}`).pathname;
  } catch {
    res.writeHead(400);
    res.end("Bad request");
    return;
  }
  if (pathname.startsWith("/api/")) {
    await handleApi(req, res, pathname);
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

server.listen(port, "127.0.0.1", () => {
  console.log(`Preview server running at http://127.0.0.1:${port}/`);
});
