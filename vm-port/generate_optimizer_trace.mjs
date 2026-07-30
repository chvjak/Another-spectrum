#!/usr/bin/env node
import fs from 'node:fs';
import vm from 'node:vm';

const [dataPath, enginePath, outPath] = process.argv.slice(2);
if (!dataPath || !enginePath || !outPath) {
  throw new Error('usage: generate_optimizer_trace.mjs ootwdemo.js another.min.js out.log');
}

globalThis.atob = (value) => Buffer.from(value, 'base64').toString('binary');
globalThis.window = globalThis;
globalThis.document = {};

const source = fs.readFileSync(dataPath, 'utf8') + '\n' + fs.readFileSync(enginePath, 'utf8');
vm.runInThisContext(source, { filename: enginePath });

// Headless run: the display conversion is irrelevant to ownership tracing.
update_screen = function() {};

const trace = [];
const emit = (line) => trace.push(line);
let tickNumber = -1;
let shapeDepth = 0;
let textDepth = 0;
let eventCount = 0;

const originalDrawShape = draw_shape;
draw_shape = function(...args) {
  const top = shapeDepth === 0;
  if (top) {
    ++eventCount;
    emit(`vid_opcd_event ${eventCount}`);
  }
  ++shapeDepth;
  try {
    return originalDrawShape(...args);
  } finally {
    --shapeDepth;
  }
};

const originalDrawString = draw_string;
draw_string = function(...args) {
  ++eventCount;
  emit(`Script::op_drawString(${args[0]}, ${args[1]}, ${args[2]}, ${args[3]})`);
  ++textDepth;
  try {
    return originalDrawString(...args);
  } finally {
    --textDepth;
  }
};

// The JS renderer works at SCALE=2. The optimizer trace is in the original
// 320x200 coordinate system used by rawgl.
draw_polygon = function(page, color, vertices) {
  emit(`SEM quadstrip buffer=${page} color=${color} vertices=${vertices.length}`);
  for (let i = 0; i < vertices.length; ++i) {
    emit(`SEM vertex index=${i} x=${Math.trunc(vertices[i].x / SCALE)} y=${Math.trunc(vertices[i].y / SCALE)}`);
  }
};

draw_point = function(page, color, x, y) {
  emit(`SEM point buffer=${page} color=${color} x=${Math.trunc(x / SCALE)} y=${Math.trunc(y / SCALE)}`);
};

draw_char = function(page, chr, color, x, y) {
  if (textDepth > 0) {
    emit(`SEM glyph buffer=${page} color=${color} char=${chr} x=${x * 8} y=${y}`);
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

// Bitmap resources replace page 0 wholesale. They have no draw-event owner;
// resetting ownership is the correct semantic input for later copies.
draw_bitmap = function(_num) {
  emit('SEM clear buffer=0 color=0');
};

reset();
restart(16001);
next_part = 0;
// Match the recovered Spectrum VM/rawgl intro setup.
vars[0xf2] = 4000;

let ticks = 0;
for (tickNumber = 0; tickNumber < 4000; ++tickNumber) {
  emit(`TRACE_TICK ${tickNumber}`);
  run_tasks();
  ++ticks;
  if (next_part !== 0) {
    break;
  }
}

fs.writeFileSync(outPath, trace.join('\n') + '\n');
const summary = { ticks, next_part, events: eventCount, trace_lines: trace.length };
console.log(JSON.stringify(summary));
if (ticks !== 2980 || next_part !== 16002 || eventCount !== 9648) {
  throw new Error(`unexpected intro trace ${JSON.stringify(summary)}`);
}
