#!/usr/bin/env node
import fs from 'node:fs';
import vm from 'node:vm';

const [dataPath, enginePath, outPath] = process.argv.slice(2);
if (!dataPath || !enginePath || !outPath) {
  throw new Error('usage: generate_deep_trace.mjs ootwdemo.js another.min.js out.log');
}

globalThis.atob = value => Buffer.from(value, 'base64').toString('binary');
globalThis.window = globalThis;
globalThis.document = {};

const source = fs.readFileSync(dataPath, 'utf8') + '\n' + fs.readFileSync(enginePath, 'utf8');
vm.runInThisContext(source, { filename: enginePath });
update_screen = function() {};

const trace = [];
const emit = line => trace.push(line);
let shapeDepth = 0;
let textDepth = 0;
let eventCount = 0;
let primitiveCount = 0;
let currentEvent = 0;
let currentPrimitive = 0;

const originalDrawShape = draw_shape;
draw_shape = function(...args) {
  const [resource, offset, override, zoom, x, y] = args;
  const top = shapeDepth === 0;
  const previousEvent = currentEvent;
  const previousPrimitive = currentPrimitive;
  if (top) {
    ++eventCount;
    currentEvent = eventCount;
    emit(`vid_opcd_event ${eventCount}`);
    emit(`SEM top_shape event=${eventCount} root=${offset} color=${override} zoom=${zoom} x=${x} y=${y} page=${current_page0}`);
  }

  const code = resource[offset];
  if (code >= 0xC0) {
    ++primitiveCount;
    currentPrimitive = primitiveCount;
    const color = (override & 0x80) !== 0 ? (code & 0x3F) : override;
    emit(`SEM primitive id=${primitiveCount} event=${currentEvent} shape=${offset} color=${color} zoom=${zoom} x=${x} y=${y} page=${current_page0} depth=${shapeDepth}`);
  }

  ++shapeDepth;
  try {
    return originalDrawShape(...args);
  } finally {
    --shapeDepth;
    currentPrimitive = previousPrimitive;
    if (top) currentEvent = previousEvent;
  }
};

const originalDrawString = draw_string;
draw_string = function(...args) {
  ++eventCount;
  currentEvent = eventCount;
  emit(`SEM text_event event=${eventCount}`);
  emit(`Script::op_drawString(${args[0]}, ${args[1]}, ${args[2]}, ${args[3]})`);
  ++textDepth;
  try {
    return originalDrawString(...args);
  } finally {
    --textDepth;
    currentEvent = 0;
  }
};

// another_js renders at SCALE=2; emit the original 320x200 coordinates.
draw_polygon = function(page, color, vertices) {
  emit(`SEM quadstrip primitive=${currentPrimitive} event=${currentEvent} buffer=${page} color=${color} vertices=${vertices.length}`);
  for (let i = 0; i < vertices.length; ++i) {
    emit(`SEM vertex primitive=${currentPrimitive} index=${i} x=${Math.trunc(vertices[i].x / SCALE)} y=${Math.trunc(vertices[i].y / SCALE)}`);
  }
};

draw_point = function(page, color, x, y) {
  emit(`SEM point primitive=${currentPrimitive} event=${currentEvent} buffer=${page} color=${color} x=${Math.trunc(x / SCALE)} y=${Math.trunc(y / SCALE)}`);
};

draw_char = function(page, chr, color, x, y) {
  if (textDepth > 0) {
    emit(`SEM glyph event=${currentEvent} buffer=${page} color=${color} char=${chr} x=${x * 8} y=${y}`);
  }
};

const originalFillPage = fill_page;
fill_page = function(num, color) {
  const page = get_page(num);
  emit(`SEM clear buffer=${page} color=${color}`);
  return originalFillPage(num, color);
};

const originalCopyPage = copy_page;
copy_page = function(src, dst, vscroll) {
  const resolvedDst = get_page(dst);
  const resolvedSrc = src >= 0xfe ? get_page(src) : get_page(src & 3);
  emit(`SEM copy dst=${resolvedDst} src=${resolvedSrc}`);
  return originalCopyPage(src, dst, vscroll);
};

const originalUpdateDisplay = update_display;
update_display = function(num) {
  const result = originalUpdateDisplay(num);
  emit(`SEM present buffer=${current_page1}`);
  return result;
};

draw_bitmap = function(_num) {
  emit('SEM clear buffer=0 color=0');
};

reset();
restart(16001);
next_part = 0;
vars[0xf2] = 4000;

let ticks = 0;
for (let tick = 0; tick < 4000; ++tick) {
  emit(`TRACE_TICK ${tick}`);
  run_tasks();
  ++ticks;
  if (next_part !== 0) break;
}

fs.writeFileSync(outPath, trace.join('\n') + '\n');
const summary = { ticks, next_part, events: eventCount, primitives: primitiveCount, trace_lines: trace.length };
console.log(JSON.stringify(summary));
if (ticks !== 2980 || next_part !== 16002 || eventCount !== 9648 || primitiveCount === 0) {
  throw new Error(`unexpected intro trace ${JSON.stringify(summary)}`);
}
