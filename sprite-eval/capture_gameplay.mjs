#!/usr/bin/env node
/**
 * Capture DOS-demo gameplay screens and isolated top-level vector shapes.
 *
 * This runs the original Another World JavaScript VM headlessly.  It does not
 * modify the bytecode or polygon resources.  Top-level shapes are rendered a
 * second time on a transparent scratch page so candidate Lester/buddy frames
 * can be identified without baking a particular background into the sprite.
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const [dataPath, enginePath, outputPath, ticksText = "900"] = process.argv.slice(2);
if (!dataPath || !enginePath || !outputPath) {
  throw new Error(
    "usage: capture_gameplay.mjs ootwdemo.js another.min.js output-dir [ticks-per-part]",
  );
}

const ticksPerPart = Number.parseInt(ticksText, 10);
if (!Number.isFinite(ticksPerPart) || ticksPerPart < 1) {
  throw new Error(`invalid ticks-per-part: ${ticksText}`);
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

const output = path.resolve(outputPath);
const screenDir = path.join(output, "screens");
const shapeDir = path.join(output, "shapes");
fs.mkdirSync(screenDir, { recursive: true });
fs.mkdirSync(shapeDir, { recursive: true });

// The browser display is irrelevant. update_display still performs palette
// changes, while this replacement suppresses canvas access.
update_screen = () => {};

const rgbForIndex = (index) => {
  const value = palette32[16 * palette_type + (index & 15)] >>> 0;
  return [value & 255, (value >>> 8) & 255, (value >>> 16) & 255];
};

const ppm = (width, height, rgb) =>
  Buffer.concat([Buffer.from(`P6\n${width} ${height}\n255\n`), rgb]);
const pgm = (width, height, alpha) =>
  Buffer.concat([Buffer.from(`P5\n${width} ${height}\n255\n`), alpha]);

const captureScreen = (page, filename) => {
  const rgb = Buffer.allocUnsafe(320 * 200 * 3);
  let cursor = 0;
  const base = page * PAGE_SIZE;
  for (let y = 0; y < 200; ++y) {
    const row = base + y * SCALE * SCREEN_W;
    for (let x = 0; x < 320; ++x) {
      const color = rgbForIndex(buffer8[row + x * SCALE]);
      rgb[cursor++] = color[0];
      rgb[cursor++] = color[1];
      rgb[cursor++] = color[2];
    }
  }
  fs.writeFileSync(path.join(screenDir, filename), ppm(320, 200, rgb));
};

let currentPart = 0;
let currentTick = 0;
let displayCount = 0;
let shapeDepth = 0;
let capturePass = false;
let originalDrawShape;

const rootStats = new Map();
const shapeHashes = new Set();
const shapeRecords = [];
const screenRecords = [];

const updateRootStats = (key, width, height) => {
  const item = rootStats.get(key) ?? {
    key,
    count: 0,
    minWidth: width,
    maxWidth: width,
    minHeight: height,
    maxHeight: height,
  };
  item.count++;
  item.minWidth = Math.min(item.minWidth, width);
  item.maxWidth = Math.max(item.maxWidth, width);
  item.minHeight = Math.min(item.minHeight, height);
  item.maxHeight = Math.max(item.maxHeight, height);
  rootStats.set(key, item);
};

const captureTopShape = (resource, offset, override, zoom, x, y) => {
  const scratch = 3 * PAGE_SIZE;
  buffer8.fill(255, scratch, scratch + PAGE_SIZE);
  const savedPage = current_page0;
  current_page0 = 3;
  capturePass = true;
  try {
    originalDrawShape(resource, offset, override, zoom, x, y);
  } finally {
    capturePass = false;
    current_page0 = savedPage;
  }

  let minX = 320;
  let minY = 200;
  let maxX = -1;
  let maxY = -1;
  for (let sy = 0; sy < 200; ++sy) {
    const row = scratch + sy * SCALE * SCREEN_W;
    for (let sx = 0; sx < 320; ++sx) {
      if (buffer8[row + sx * SCALE] === 255) continue;
      minX = Math.min(minX, sx);
      minY = Math.min(minY, sy);
      maxX = Math.max(maxX, sx);
      maxY = Math.max(maxY, sy);
    }
  }
  if (maxX < minX || maxY < minY) return;

  const width = maxX - minX + 1;
  const height = maxY - minY + 1;
  const resourceName = resource === polygons1 ? "p1" : resource === polygons2 ? "p2" : "other";
  const rootKey = `${currentPart}:${resourceName}:${offset}`;
  updateRootStats(rootKey, width, height);

  // Characters are roughly 8..72 pixels wide and 12..96 pixels tall.  This
  // excludes full-screen scenery while retaining crouch/jump/run variants.
  if (width < 5 || height < 10 || width > 80 || height > 100) return;

  const rgb = Buffer.allocUnsafe(width * height * 3);
  const alpha = Buffer.allocUnsafe(width * height);
  let rgbCursor = 0;
  let alphaCursor = 0;
  for (let sy = minY; sy <= maxY; ++sy) {
    const row = scratch + sy * SCALE * SCREEN_W;
    for (let sx = minX; sx <= maxX; ++sx) {
      const index = buffer8[row + sx * SCALE];
      if (index === 255) {
        rgb[rgbCursor++] = 255;
        rgb[rgbCursor++] = 0;
        rgb[rgbCursor++] = 255;
        alpha[alphaCursor++] = 0;
      } else {
        const color = rgbForIndex(index);
        rgb[rgbCursor++] = color[0];
        rgb[rgbCursor++] = color[1];
        rgb[rgbCursor++] = color[2];
        alpha[alphaCursor++] = 255;
      }
    }
  }

  const hash = crypto
    .createHash("sha1")
    .update(Buffer.from([width & 255, height & 255]))
    .update(rgb)
    .update(alpha)
    .digest("hex")
    .slice(0, 12);
  if (shapeHashes.has(hash)) return;
  shapeHashes.add(hash);

  const stem = [
    `part-${currentPart}`,
    resourceName,
    `root-${offset.toString(16).padStart(4, "0")}`,
    `tick-${currentTick.toString().padStart(4, "0")}`,
    `${width}x${height}`,
    hash,
  ].join("-");
  fs.writeFileSync(path.join(shapeDir, `${stem}.ppm`), ppm(width, height, rgb));
  fs.writeFileSync(path.join(shapeDir, `${stem}.pgm`), pgm(width, height, alpha));
  shapeRecords.push({
    stem,
    part: currentPart,
    tick: currentTick,
    resource: resourceName,
    root: offset,
    override,
    zoom,
    x,
    y,
    minX,
    minY,
    width,
    height,
    hash,
  });
};

originalDrawShape = draw_shape;
draw_shape = function (...args) {
  if (capturePass) return originalDrawShape(...args);
  const top = shapeDepth === 0;
  if (top) captureTopShape(...args);
  ++shapeDepth;
  try {
    return originalDrawShape(...args);
  } finally {
    --shapeDepth;
  }
};

const originalUpdateDisplay = update_display;
update_display = function (page) {
  const result = originalUpdateDisplay(page);
  ++displayCount;
  // Capture regularly, plus a denser sample at the start of every part.
  if (displayCount <= 8 || displayCount % 12 === 0) {
    const file = `part-${currentPart}-display-${displayCount
      .toString()
      .padStart(4, "0")}-tick-${currentTick.toString().padStart(4, "0")}.ppm`;
    captureScreen(current_page1, file);
    screenRecords.push({
      file,
      part: currentPart,
      tick: currentTick,
      display: displayCount,
      page: current_page1,
    });
  }
  return result;
};

const clearInput = () => {
  keyboard.fill(0);
};

const setInputForTick = (tick) => {
  clearInput();
  // The shareware section starts underwater.  Swim straight up first; a
  // horizontal/run pattern here causes Lester to drown and returns to the
  // password screen before any gameplay backgrounds are reached.
  if (tick < 130) {
    keyboard[KEY_UP] = 1;
    return;
  }
  const phase = (tick - 130) % 480;
  if (phase < 170) {
    keyboard[KEY_RIGHT] = 1;
    keyboard[KEY_ACTION] = 1;
  } else if (phase < 220) {
    keyboard[KEY_UP] = 1;
  } else if (phase < 390) {
    keyboard[KEY_LEFT] = 1;
    keyboard[KEY_ACTION] = 1;
  } else if (phase < 430) {
    keyboard[KEY_DOWN] = 1;
  }
};

// ootwdemo.js contains the introduction and the shareware gameplay part
// (16002, labelled "Water" by another_js).  Later retail-game parts are
// deliberately not bundled with the demo data.
for (const part of [16002]) {
  reset();
  next_part = part;
  currentPart = part;
  displayCount = 0;
  for (currentTick = 0; currentTick < ticksPerPart; ++currentTick) {
    setInputForTick(currentTick);
    run_tasks();
  }
  clearInput();
}

const metadata = {
  ticksPerPart,
  screens: screenRecords,
  shapes: shapeRecords,
  roots: [...rootStats.values()].sort((a, b) => b.count - a.count),
};
fs.writeFileSync(path.join(output, "capture.json"), `${JSON.stringify(metadata, null, 2)}\n`);
process.stdout.write(
  `${JSON.stringify({
    ticksPerPart,
    screens: screenRecords.length,
    uniqueShapes: shapeRecords.length,
    roots: rootStats.size,
  })}\n`,
);
