#!/usr/bin/env node
/** Enumerate visually plausible character shapes in the demo's shared bank. */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const [dataPath, enginePath, outputPath] = process.argv.slice(2);
if (!dataPath || !enginePath || !outputPath) {
  throw new Error(
    "usage: enumerate_common_shapes.mjs ootwdemo.js another.min.js output-dir",
  );
}

globalThis.atob = (value) => Buffer.from(value, "base64").toString("binary");
globalThis.window = globalThis;
globalThis.document = {};
globalThis.console.log = (...values) =>
  process.stderr.write(`${values.join(" ")}\n`);
vm.runInThisContext(
  `${fs.readFileSync(dataPath, "utf8")}\n${fs.readFileSync(enginePath, "utf8")}`,
  { filename: enginePath },
);
update_screen = () => {};

reset();
next_part = 16002;
run_tasks();
const resource = polygons2;
if (!(resource instanceof Uint8Array) || resource.length < 4) {
  throw new Error("shareware common polygon bank was not loaded");
}

const memo = new Map();
const validate = (offset, active = new Set(), depth = 0) => {
  if ((offset & 1) !== 0 || offset < 0 || offset >= resource.length) return false;
  if (memo.has(offset)) return memo.get(offset);
  if (depth > 24 || active.has(offset)) return false;
  active.add(offset);
  const code = resource[offset];
  let valid = false;
  if (code >= 0xc0) {
    if (offset + 4 <= resource.length) {
      const vertices = resource[offset + 3];
      valid =
        (vertices & 1) === 0 &&
        vertices >= 2 &&
        vertices <= 48 &&
        offset + 4 + vertices * 2 <= resource.length;
    }
  } else if ((code & 0x3f) === 2 && offset + 4 <= resource.length) {
    const children = resource[offset + 3] + 1;
    let cursor = offset + 4;
    valid = children <= 64;
    for (let index = 0; valid && index < children; ++index) {
      if (cursor + 4 > resource.length) {
        valid = false;
        break;
      }
      const descriptor = (resource[cursor] << 8) | resource[cursor + 1];
      const child = (descriptor << 1) & 0xfffe;
      cursor += descriptor & 0x8000 ? 6 : 4;
      if (cursor > resource.length || !validate(child, active, depth + 1)) {
        valid = false;
      }
    }
  }
  active.delete(offset);
  memo.set(offset, valid);
  return valid;
};

const rgbForIndex = (index) => {
  const value = palette32[16 * palette_type + (index & 15)] >>> 0;
  return [value & 255, (value >>> 8) & 255, (value >>> 16) & 255];
};
const ppm = (width, height, rgb) =>
  Buffer.concat([Buffer.from(`P6\n${width} ${height}\n255\n`), rgb]);
const pgm = (width, height, alpha) =>
  Buffer.concat([Buffer.from(`P5\n${width} ${height}\n255\n`), alpha]);

const output = path.resolve(outputPath);
fs.mkdirSync(output, { recursive: true });
const hashes = new Set();
const records = [];
const scratch = 3 * PAGE_SIZE;

for (let offset = 0; offset < resource.length; offset += 2) {
  if (!validate(offset)) continue;
  buffer8.fill(255, scratch, scratch + PAGE_SIZE);
  const savedPage = current_page0;
  current_page0 = 3;
  try {
    draw_shape(resource, offset, 255, 64, 160, 180);
  } catch {
    current_page0 = savedPage;
    continue;
  }
  current_page0 = savedPage;

  let minX = 320;
  let minY = 200;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < 200; ++y) {
    const row = scratch + y * SCALE * SCREEN_W;
    for (let x = 0; x < 320; ++x) {
      if (buffer8[row + x * SCALE] === 255) continue;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  if (maxX < minX || maxY < minY) continue;
  const width = maxX - minX + 1;
  const height = maxY - minY + 1;
  if (width < 5 || width > 72 || height < 18 || height > 88) continue;

  const rgb = Buffer.allocUnsafe(width * height * 3);
  const alpha = Buffer.allocUnsafe(width * height);
  let rc = 0;
  let ac = 0;
  for (let y = minY; y <= maxY; ++y) {
    const row = scratch + y * SCALE * SCREEN_W;
    for (let x = minX; x <= maxX; ++x) {
      const index = buffer8[row + x * SCALE];
      if (index === 255) {
        rgb[rc++] = 255;
        rgb[rc++] = 0;
        rgb[rc++] = 255;
        alpha[ac++] = 0;
      } else {
        const color = rgbForIndex(index);
        rgb[rc++] = color[0];
        rgb[rc++] = color[1];
        rgb[rc++] = color[2];
        alpha[ac++] = 255;
      }
    }
  }
  const hash = crypto
    .createHash("sha1")
    .update(Buffer.from([width, height]))
    .update(rgb)
    .update(alpha)
    .digest("hex")
    .slice(0, 12);
  if (hashes.has(hash)) continue;
  hashes.add(hash);
  const stem = `common-root-${offset.toString(16).padStart(4, "0")}-${width}x${height}-${hash}`;
  fs.writeFileSync(path.join(output, `${stem}.ppm`), ppm(width, height, rgb));
  fs.writeFileSync(path.join(output, `${stem}.pgm`), pgm(width, height, alpha));
  records.push({
    stem,
    offset,
    anchorX: 160,
    anchorY: 180,
    minX,
    minY,
    width,
    height,
    hash,
  });
}

fs.writeFileSync(
  path.join(output, "common-shapes.json"),
  `${JSON.stringify({ resourceBytes: resource.length, shapes: records }, null, 2)}\n`,
);
process.stdout.write(
  `${JSON.stringify({ resourceBytes: resource.length, validOffsets: memo.size, shapes: records.length })}\n`,
);
