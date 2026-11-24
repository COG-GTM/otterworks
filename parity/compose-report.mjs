// Builds side-by-side (baseline | upgraded | diff) composites and pixel-diff stats
// from report/shots/{baseline,upgraded}/*.png into report/compare/ and report/summary.md.
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import pixelmatch from 'pixelmatch';
import { PNG } from 'pngjs';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), 'report');
const shots = (p) => path.join(root, 'shots', p);
const outDir = path.join(root, 'compare');
mkdirSync(outDir, { recursive: true });

const pad = (img, width, height) => {
  if (img.width === width && img.height === height) return img;
  const out = new PNG({ width, height });
  out.data.fill(255);
  PNG.bitblt(img, out, 0, 0, img.width, img.height, 0, 0);
  return out;
};

const names = existsSync(shots('baseline')) ? readdirSync(shots('baseline')).filter((f) => f.endsWith('.png')).sort() : [];
const rows = [];
for (const name of names) {
  const upgradedPath = path.join(shots('upgraded'), name);
  if (!existsSync(upgradedPath)) {
    rows.push({ name, missing: true });
    continue;
  }
  const a0 = PNG.sync.read(readFileSync(path.join(shots('baseline'), name)));
  const b0 = PNG.sync.read(readFileSync(upgradedPath));
  const width = Math.max(a0.width, b0.width);
  const height = Math.max(a0.height, b0.height);
  const a = pad(a0, width, height);
  const b = pad(b0, width, height);
  const diff = new PNG({ width, height });
  const changed = pixelmatch(a.data, b.data, diff.data, width, height, { threshold: 0.1 });
  const gap = 16;
  const sheet = new PNG({ width: width * 3 + gap * 2, height });
  sheet.data.fill(255);
  PNG.bitblt(a, sheet, 0, 0, width, height, 0, 0);
  PNG.bitblt(b, sheet, 0, 0, width, height, width + gap, 0);
  PNG.bitblt(diff, sheet, 0, 0, width, height, (width + gap) * 2, 0);
  writeFileSync(path.join(outDir, name), PNG.sync.write(sheet));
  rows.push({
    name,
    size: `${a0.width}x${a0.height} / ${b0.width}x${b0.height}`,
    changed,
    percent: ((changed / (width * height)) * 100).toFixed(3),
  });
}

writeFileSync(path.join(root, 'summary.json'), JSON.stringify(rows, null, 2));
const md = [
  '| Screen | Baseline / upgraded size | Changed pixels | Diff % |',
  '| --- | --- | --- | --- |',
  ...rows.map((r) =>
    r.missing ? `| ${r.name} | missing upgraded shot | - | - |` : `| [${r.name}](compare/${r.name}) | ${r.size} | ${r.changed} | ${r.percent}% |`,
  ),
].join('\n');
writeFileSync(path.join(root, 'summary.md'), md + '\n');
console.log(md);
