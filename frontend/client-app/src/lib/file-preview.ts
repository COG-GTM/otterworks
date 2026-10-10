export type PreviewKind = "image" | "video" | "audio" | "pdf" | "text" | "unsupported";

// Types that say nothing about the content (or are commonly mislabeled by
// browsers, e.g. `.ts` source reported as an MPEG transport stream).
const GENERIC_MIME_TYPES = new Set([
  "",
  "application/octet-stream",
  "binary/octet-stream",
  "application/unknown",
  "video/mp2t",
]);

const TEXT_MIME_TYPES = new Set([
  "application/json",
  "application/xml",
  "application/javascript",
  "application/typescript",
  "application/x-yaml",
  "application/yaml",
  "application/x-sh",
  "application/sql",
  "application/toml",
  "application/x-httpd-php",
]);

const EXTENSION_KINDS: Record<string, PreviewKind> = {
  // images
  png: "image", jpg: "image", jpeg: "image", gif: "image", webp: "image",
  bmp: "image", ico: "image", avif: "image",
  // documents
  pdf: "pdf",
  // video
  mp4: "video", m4v: "video", webm: "video", mov: "video", ogv: "video",
  // audio
  mp3: "audio", wav: "audio", ogg: "audio", oga: "audio", m4a: "audio",
  flac: "audio", aac: "audio",
  // text & code
  txt: "text", log: "text", md: "text", markdown: "text", csv: "text", tsv: "text",
  json: "text", xml: "text", yaml: "text", yml: "text", toml: "text", ini: "text",
  cfg: "text", conf: "text", env: "text", properties: "text", html: "text",
  htm: "text", svg: "text", css: "text", scss: "text", js: "text", mjs: "text", cjs: "text",
  jsx: "text", ts: "text", tsx: "text", py: "text", rb: "text", go: "text",
  rs: "text", java: "text", kt: "text", c: "text", h: "text", cpp: "text",
  hpp: "text", cs: "text", php: "text", swift: "text", scala: "text", sql: "text",
  sh: "text", bash: "text", gradle: "text", dockerfile: "text", makefile: "text",
};

function extensionOf(fileName: string): string {
  const base = fileName.split("/").pop() ?? fileName;
  const dot = base.lastIndexOf(".");
  // Extensionless well-known names such as "Dockerfile" or "Makefile".
  return (dot >= 0 ? base.slice(dot + 1) : base).toLowerCase();
}

function kindFromMime(mimeType: string): PreviewKind {
  const mime = mimeType.split(";")[0].trim().toLowerCase();
  if (mime === "application/pdf") return "pdf";
  // SVG is served as plain text (it can carry script), so show its source.
  if (mime === "image/svg+xml") return "text";
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  if (
    mime.startsWith("text/") ||
    TEXT_MIME_TYPES.has(mime) ||
    mime.endsWith("+json") ||
    mime.endsWith("+xml")
  ) {
    return "text";
  }
  return "unsupported";
}

/** Decide how a stored file should be previewed, from its MIME type and name. */
export function getPreviewKind(mimeType: string | undefined, fileName: string): PreviewKind {
  const mime = (mimeType ?? "").split(";")[0].trim().toLowerCase();
  if (!GENERIC_MIME_TYPES.has(mime)) {
    return kindFromMime(mime);
  }
  return EXTENSION_KINDS[extensionOf(fileName)] ?? "unsupported";
}
