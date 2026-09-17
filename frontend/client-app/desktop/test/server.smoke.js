/* Smoke test for the embedded static + proxy server (run via `npm test`).
 * Exercises static serving, SPA fallback, asset caching, path traversal,
 * the /api/v1 HTTP + WebSocket proxy against a stub gateway, and the
 * transport guarantees: loopback-only bind, gateway-only forwarding, and
 * error bodies that never echo the request back. */
const http = require("node:http");
const net = require("node:net");
const crypto = require("node:crypto");
const path = require("node:path");
const { startAppServer } = require("../build/server");

const WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

// Dummy "API gateway": echoes path + auth header; supports a raw WS handshake.
const gateway = http.createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ path: req.url, auth: req.headers.authorization || null }));
});
gateway.on("upgrade", (req, socket) => {
  const accept = crypto
    .createHash("sha1")
    .update(req.headers["sec-websocket-key"] + WS_MAGIC)
    .digest("base64");
  socket.write(
    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
      `Sec-WebSocket-Accept: ${accept}\r\n\r\n`
  );
  // Send a single unmasked text frame "hi" then keep the socket open.
  socket.write(Buffer.from([0x81, 0x02, 0x68, 0x69]));
});

function get(url, headers = {}) {
  return new Promise((resolve, reject) => {
    http.get(url, { headers }, (res) => {
      let body = "";
      res.on("data", (c) => (body += c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body }));
    }).on("error", reject);
  });
}

async function main() {
  await new Promise((r) => gateway.listen(0, "127.0.0.1", r));
  const gwPort = gateway.address().port;

  const app = await startAppServer({
    webRoot: path.resolve(__dirname, "..", "..", "dist"),
    gatewayUrl: `http://127.0.0.1:${gwPort}`,
    port: 0,
  });

  let failed = false;
  const check = (name, ok, detail) => {
    console.log(`${ok ? "PASS" : "FAIL"} ${name}${ok ? "" : ` -- ${detail}`}`);
    if (!ok) failed = true;
  };

  const index = await get(`${app.url}/`);
  check("serves index.html", index.status === 200 && index.body.includes("<div id=\"root\">"), index.body.slice(0, 120));

  const spa = await get(`${app.url}/documents/some-deep/route`);
  check("SPA fallback", spa.status === 200 && spa.body.includes("<div id=\"root\">"), spa.status);

  const assetPath = index.body.match(/\/assets\/[^"]+\.js/)[0];
  const asset = await get(`${app.url}${assetPath}`);
  check(
    "asset with immutable cache",
    asset.status === 200 &&
      asset.headers["cache-control"] === "public, max-age=31536000, immutable" &&
      asset.headers["content-type"].startsWith("text/javascript"),
    JSON.stringify({ status: asset.status, cc: asset.headers["cache-control"] })
  );

  const traversal = await get(`${app.url}/..%2f..%2fpackage.json`);
  check("path traversal falls back to SPA", traversal.status === 200 && traversal.body.includes("<div id=\"root\">"), traversal.body.slice(0, 80));

  const api = await get(`${app.url}/api/v1/documents?x=1`, { Authorization: "Bearer test-token" });
  const apiBody = JSON.parse(api.body);
  check(
    "proxies /api/v1 with headers",
    api.status === 200 && apiBody.path === "/api/v1/documents?x=1" && apiBody.auth === "Bearer test-token",
    api.body
  );

  // WebSocket upgrade through the proxy
  const wsResult = await new Promise((resolve) => {
    const key = crypto.randomBytes(16).toString("base64");
    const req = http.request(`${app.url}/api/v1/collab`, {
      headers: {
        Connection: "Upgrade",
        Upgrade: "websocket",
        "Sec-WebSocket-Key": key,
        "Sec-WebSocket-Version": "13",
      },
    });
    req.on("upgrade", (res, socket, head) => {
      const expected = crypto.createHash("sha1").update(key + WS_MAGIC).digest("base64");
      const onFrame = (frame) => {
        resolve({
          accept: res.headers["sec-websocket-accept"] === expected,
          frame: frame[0] === 0x81 && frame.subarray(2).toString() === "hi",
        });
        socket.destroy();
      };
      // The frame may coalesce with the 101 response (head) or arrive separately
      if (head && head.length) onFrame(head);
      else socket.once("data", onFrame);
    });
    req.on("response", () => resolve({ accept: false, frame: false }));
    req.on("error", () => resolve({ accept: false, frame: false }));
    setTimeout(() => resolve({ accept: false, frame: false }), 3000);
    req.end();
  });
  check("WebSocket upgrade proxied", wsResult.accept && wsResult.frame, JSON.stringify(wsResult));

  // An absolute URL in the request line must not redirect the outbound request:
  // only the path/query are copied onto the configured gateway origin.
  const absolute = await new Promise((resolve, reject) => {
    const socket = net.createConnection(Number(new URL(app.url).port), "127.0.0.1", () => {
      socket.write("GET http://127.0.0.1:1/api/v1/steal HTTP/1.1\r\nHost: localhost\r\n\r\n");
    });
    let raw = "";
    socket.on("data", (c) => {
      raw += c;
      if (raw.includes("\r\n\r\n")) {
        socket.destroy();
        resolve(raw);
      }
    });
    socket.on("error", reject);
  });
  // 127.0.0.1:1 refuses connections, so anything other than a 502 proves the
  // request was never forwarded to the client-supplied origin.
  check(
    "absolute-URL request is never proxied off-origin",
    absolute.startsWith("HTTP/1.1 200"),
    absolute.slice(0, 120)
  );

  // A failing upstream returns a fixed code, never the request URL or the
  // upstream error text, so nothing attacker-controlled is reflected.
  const deadApp = await startAppServer({
    webRoot: path.resolve(__dirname, "..", "..", "dist"),
    gatewayUrl: "http://127.0.0.1:1",
    port: 0,
  });
  const reflected = await get(`${deadApp.url}/api/v1/%3Cscript%3Ealert(1)%3C/script%3E`);
  check(
    "proxy errors are not reflected",
    reflected.status === 502 &&
      reflected.body === '{"error":"bad_gateway"}' &&
      reflected.headers["x-content-type-options"] === "nosniff",
    `${reflected.status} ${reflected.body}`
  );
  await deadApp.close();

  let boundNonLoopback = false;
  try {
    const exposed = await startAppServer({
      webRoot: path.resolve(__dirname, "..", "..", "dist"),
      gatewayUrl: `http://127.0.0.1:${gwPort}`,
      port: 0,
      host: "0.0.0.0",
    });
    boundNonLoopback = true;
    await exposed.close();
  } catch {
    // expected: cleartext listener refuses a non-loopback bind
  }
  check("refuses a non-loopback cleartext bind", !boundNonLoopback, "server bound 0.0.0.0");

  await app.close();
  gateway.close();
  process.exit(failed ? 1 : 0);
}

main().catch((err) => {
  console.error("smoke test crashed:", err);
  process.exit(1);
});
