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

const [
  dataPath,
  enginePath,
  outputPath,
  ticksText = "900",
  demoJoyPath,
  partText = "16002",
] =
  process.argv.slice(2);
if (!dataPath || !enginePath || !outputPath) {
  throw new Error(
    "usage: capture_gameplay.mjs data.js another.min.js output-dir [ticks-per-part] [DEMO3.JOY|-] [part]",
  );
}

const ticksPerPart = Number.parseInt(ticksText, 10);
if (!Number.isFinite(ticksPerPart) || ticksPerPart < 1) {
  throw new Error(`invalid ticks-per-part: ${ticksText}`);
}
const part = Number.parseInt(partText, 10);
if (!Number.isFinite(part) || part < 16001 || part > 16008) {
  throw new Error(`invalid part: ${partText}`);
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

// The minified demo engine normally receives ByteKiller-compressed resources.
// Anniversary-demo extraction emits raw base64 when a resource is already
// unpacked; handle that branch explicitly (the historical minified copy has a
// bad charCodeAt index in this rarely used path).
const originalLoadResource = load;
load = function (encoded, size) {
  const decoded = atob(encoded);
  if (decoded.length !== size) return originalLoadResource(encoded, size);
  return Uint8Array.from(decoded, (character) => character.charCodeAt(0) & 0xff);
};

const output = path.resolve(outputPath);
const screenDir = path.join(output, "screens");
const preActorDir = path.join(output, "pre-actor-screens");
const shapeDir = path.join(output, "shapes");
fs.mkdirSync(screenDir, { recursive: true });
fs.mkdirSync(preActorDir, { recursive: true });
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

const captureScreen = (page, filename, directory = screenDir) => {
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
  fs.writeFileSync(path.join(directory, filename), ppm(320, 200, rgb));
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
const shapeOccurrences = [];
const screenRecords = [];
const preActorScreenRecords = [];
const preActorTicks = new Set([45, 69, 201, 369, 717, 729, 825, 921, 1005, 1233]);
const lesterRoots = new Set([
  0x061c, 0x0640, 0x06a4, 0x0734, 0x07b8, 0x0854, 0x08f0,
  0x0970, 0x0998, 0x09c0, 0x09e8, 0x0a14, 0x0ca0, 0x0e78,
  0x1668, 0x16d0, 0x1884, 0x1928, 0x19d4, 0x1a84, 0x1b48,
  0x1bdc, 0x1c04, 0x1c2c, 0x1c54, 0x1c80,
]);
const capturedPreActorTicks = new Set();

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
  const stem = [
    `part-${currentPart}`,
    resourceName,
    `root-${offset.toString(16).padStart(4, "0")}`,
    `tick-${currentTick.toString().padStart(4, "0")}`,
    `${width}x${height}`,
    hash,
  ].join("-");
  const occurrence = {
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
  };
  shapeOccurrences.push(occurrence);
  if (shapeHashes.has(hash)) return;
  shapeHashes.add(hash);

  fs.writeFileSync(path.join(shapeDir, `${stem}.ppm`), ppm(width, height, rgb));
  fs.writeFileSync(path.join(shapeDir, `${stem}.pgm`), pgm(width, height, alpha));
  shapeRecords.push(occurrence);
};

originalDrawShape = draw_shape;
draw_shape = function (...args) {
  if (capturePass) return originalDrawShape(...args);
  const top = shapeDepth === 0;
  if (top) {
    const [resource, offset] = args;
    if (
      currentPart === 16002 &&
      resource === polygons1 &&
      lesterRoots.has(offset) &&
      preActorTicks.has(currentTick) &&
      !capturedPreActorTicks.has(currentTick)
    ) {
      const file = `part-${currentPart}-pre-actor-tick-${currentTick
        .toString()
        .padStart(4, "0")}.ppm`;
      captureScreen(current_page0, file, preActorDir);
      preActorScreenRecords.push({ file, part: currentPart, tick: currentTick, page: current_page0 });
      capturedPreActorTicks.add(currentTick);
    }
    captureTopShape(...args);
  }
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
      vars: Array.from({ length: 256 }, (_, index) => vars[index] ?? 0),
    });
  }
  return result;
};

const clearInput = () => {
  keyboard.fill(0);
};

const demoJoy = demoJoyPath && demoJoyPath !== "-" ? fs.readFileSync(demoJoyPath) : null;
let demoJoyPosition = 0;
let demoJoyMask = demoJoy?.[0] ?? 0;
let demoJoyCounter = demoJoy?.[1] ?? 0;
if (demoJoy) demoJoyPosition = 2;

const applyMask = (mask) => {
  clearInput();
  keyboard[KEY_RIGHT] = (mask & 1) !== 0 ? 1 : 0;
  keyboard[KEY_LEFT] = (mask & 2) !== 0 ? 1 : 0;
  keyboard[KEY_DOWN] = (mask & 4) !== 0 ? 1 : 0;
  keyboard[KEY_UP] = (mask & 8) !== 0 ? 1 : 0;
  keyboard[KEY_ACTION] = (mask & 0x80) !== 0 ? 1 : 0;
};

const nextDemoJoyMask = () => {
  if (!demoJoy) return null;
  if (demoJoyCounter === 0) {
    if (demoJoyPosition + 1 >= demoJoy.length) return 0;
    demoJoyMask = demoJoy[demoJoyPosition++];
    demoJoyCounter = demoJoy[demoJoyPosition++];
  } else {
    --demoJoyCounter;
  }
  return demoJoyMask;
};

const setInputForTick = (tick) => {
  const recordedMask = nextDemoJoyMask();
  if (recordedMask !== null) {
    applyMask(recordedMask);
    return;
  }
  clearInput();
  if (part === 16003) {
    // Jail opens in the hanging cage.  Lean in the current swing direction
    // (the signed cage phase is bytecode variable 1) to build momentum until
    // the scripted break-out releases Lester and Buddy into normal play.
    if (tick >= 125) {
      keyboard[vars[1] < 0 ? KEY_LEFT : KEY_RIGHT] = 1;
    }
    return;
  }
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

// The public DOS data contains the introduction and Water (16002).  The
// official Anniversary demo additionally exposes Jail (16003), which lets the
// asset audit record Buddy as he is actually composited during gameplay.
reset();
next_part = part;
currentPart = part;
displayCount = 0;
for (currentTick = 0; currentTick < ticksPerPart; ++currentTick) {
  setInputForTick(currentTick);
  run_tasks();
}
clearInput();

const metadata = {
  ticksPerPart,
  part,
  input: demoJoy
    ? { kind: "DOS DEMO3.JOY", bytes: demoJoy.length }
    : { kind: "fallback scripted input" },
  screens: screenRecords,
  preActorScreens: preActorScreenRecords,
  shapes: shapeRecords,
  shapeOccurrences,
  roots: [...rootStats.values()].sort((a, b) => b.count - a.count),
};
fs.writeFileSync(path.join(output, "capture.json"), `${JSON.stringify(metadata, null, 2)}\n`);
process.stdout.write(
  `${JSON.stringify({
    ticksPerPart,
    screens: screenRecords.length,
    uniqueShapes: shapeRecords.length,
    shapeOccurrences: shapeOccurrences.length,
    roots: rootStats.size,
  })}\n`,
);
