import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

const nginxDir = path.resolve(__dirname, "../../nginx");
const serverConf = readFileSync(path.join(nginxDir, "default.conf.template"), "utf8");
const headersConf = readFileSync(path.join(nginxDir, "security-headers.inc.template"), "utf8");
const dockerfile = readFileSync(path.resolve(__dirname, "../../Dockerfile"), "utf8");

const INCLUDE = "include /etc/nginx/conf.d/security-headers.inc;";

function header(name: string): string | undefined {
  const match = headersConf.match(new RegExp(`^add_header ${name} (.+) always;$`, "m"));
  return match?.[1];
}

function blocks(conf: string): string[] {
  // Every server/location body, innermost last, keyed by its opening brace.
  const bodies: string[] = [];
  const stack: number[] = [];
  for (let i = 0; i < conf.length; i++) {
    if (conf[i] === "{") stack.push(i);
    if (conf[i] === "}") {
      const start = stack.pop()!;
      const opener = conf.slice(conf.lastIndexOf("\n", start) + 1, start);
      if (/^\s*(server|location)\b/.test(opener)) {
        bodies.push(conf.slice(start + 1, i).replace(/\{[^]*\}/g, ""));
      }
    }
  }
  return bodies;
}

describe("web-app nginx security headers", () => {
  it("sets the baseline headers on every response", () => {
    expect(header("X-Content-Type-Options")).toBe('"nosniff"');
    expect(header("X-Frame-Options")).toBe('"DENY"');
    expect(header("Referrer-Policy")).toBe('"strict-origin-when-cross-origin"');
    expect(header("Strict-Transport-Security")).toBe("$hsts_header");
  });

  it("uses a CSP that forbids framing, plugins and foreign scripts", () => {
    const csp = header("Content-Security-Policy") ?? "";
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("script-src 'self';");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).not.toMatch(/script-src[^;]*'unsafe-(inline|eval)'/);
  });

  it("only sends HSTS for TLS requests", () => {
    expect(serverConf).toMatch(/map "\$scheme:\$http_x_forwarded_proto" \$hsts_header \{[^}]*default\s+"";[^}]*~https\s+"max-age=\d+";/);
  });

  it("re-includes the headers in every block that declares its own add_header", () => {
    const server = serverConf.slice(serverConf.indexOf("server {"));
    expect(blocks(server).find((b) => /^\s*listen /m.test(b))).toContain(INCLUDE);
    for (const body of blocks(server)) {
      if (/^\s*add_header /m.test(body)) expect(body).toContain(INCLUDE);
    }
  });

  it("ships the headers template and defines every variable it substitutes", () => {
    expect(dockerfile).toContain("COPY nginx/security-headers.inc.template /etc/nginx/templates/");
    for (const [, name] of headersConf.matchAll(/\$\{(\w+)\}/g)) {
      expect(dockerfile).toMatch(new RegExp(`^ENV ${name}=`, "m"));
    }
  });

  it("allowlists storage origins by exact host, not a shared-domain wildcard", () => {
    const origins = dockerfile.match(/^ENV CSP_STORAGE_ORIGINS="([^"]*)"/m)?.[1] ?? "";
    expect(origins).not.toBe("");
    for (const origin of origins.split(/\s+/)) {
      expect(origin).toMatch(/^https:\/\/[^*\s]+$/);
    }
  });
});
