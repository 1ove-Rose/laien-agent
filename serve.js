const http = require("http");
const fs = require("fs");
const path = require("path");

const root = process.cwd();
const port = Number(process.env.PORT || 8765);
const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8"
};

const server = http.createServer((req, res) => {
  const requestedPath = req.url === "/" ? "/index.html" : req.url.split("?")[0];
  const filePath = path.normalize(path.join(root, decodeURIComponent(requestedPath)));

  if (!filePath.startsWith(root)) {
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
