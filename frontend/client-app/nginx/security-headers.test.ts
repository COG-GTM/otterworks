// @vitest-environment node
import { readFileSync } from "node:fs";
import path from "node:path";

const dir = path.resolve(__dirname);
const snippet = readFileSync(path.join(dir, "security-headers.conf"), "utf8");
const template = readFileSync(path.join(dir, "default.conf.template"), "utf8");
const dockerfile = readFileSync(path.join(dir, "..", "Dockerfile"), "utf8");

const SNIPPET_PATH = "/etc/nginx/snippets/security-headers.conf";
const INCLUDE = `include ${SNIPPET_PATH};`;

function headers(conf: string): Map<string, string> {
  const found = new Map<string, string>();
  for (const match of conf.matchAll(/^\s*add_header\s+(\S+)\s+"([^"]*)"\s+always;/gm)) {
    found.set(match[1].toLowerCase(), match[2]);
  }
  return found;
}

function csp(): Map<string, string[]> {
  const value = headers(snippet).get("content-security-policy") ?? "";
  return new Map(
    value
      .split(";")
      .map((d) => d.trim().split(/\s+/))
      .filter((parts) => parts[0])
      .map(([name, ...sources]) => [name, sources]),
  );
}

// Brace-matched location blocks, so nested braces cannot hide a block's body.
function locationBlocks(conf: string): { name: string; body: string }[] {
  const blocks: { name: string; body: string }[] = [];
  for (const match of conf.matchAll(/location\s+([^{]+)\{/g)) {
    let depth = 1;
    let i = match.index! + match[0].length;
    const start = i;
    while (depth > 0 && i < conf.length) {
      if (conf[i] === "{") depth++;
      if (conf[i] === "}") depth--;
      i++;
    }
    blocks.push({ name: match[1].trim(), body: conf.slice(start, i - 1) });
  }
  return blocks;
}

describe("web-app nginx security headers", () => {
  it("sets every header the DAST attack-surface contract expects, on all statuses", () => {
    const set = headers(snippet);
    expect(set.get("x-content-type-options")).toBe("nosniff");
    expect(set.get("x-frame-options")).toBe("DENY");
    expect(set.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
    expect(set.get("strict-transport-security")).toMatch(/max-age=\d{7,}/);
    expect(set.get("content-security-policy")).toBeTruthy();
    // Every add_header in the snippet must use `always` (the regex above requires it).
    expect(snippet.match(/^\s*add_header\b/gm)).toHaveLength(set.size);
  });

  it("forbids framing and keeps scripts same-origin", () => {
    const policy = csp();
    expect(policy.get("frame-ancestors")).toEqual(["'none'"]);
    expect(policy.get("default-src")).toEqual(["'self'"]);
    expect(policy.get("script-src")).toEqual(["'self'"]);
    expect(policy.get("object-src")).toEqual(["'none'"]);
    expect(policy.get("base-uri")).toEqual(["'self'"]);
    expect(policy.get("form-action")).toEqual(["'self'"]);
  });

  it("includes the headers at server level", () => {
    const serverLevel = template.replace(/location\s+[^{]+\{[^}]*\}/g, "");
    expect(serverLevel).toContain(INCLUDE);
  });

  it("re-includes the headers in every location that sets its own add_header", () => {
    const withOwnHeaders = locationBlocks(template).filter((b) => /\badd_header\b/.test(b.body));
    expect(withOwnHeaders.map((b) => b.name)).toContain("/assets/");
    for (const block of withOwnHeaders) {
      expect(block.body, `location ${block.name}`).toContain(INCLUDE);
    }
  });

  it("ships the snippet where the template includes it", () => {
    expect(dockerfile).toContain(`COPY nginx/security-headers.conf ${SNIPPET_PATH}`);
  });
});
