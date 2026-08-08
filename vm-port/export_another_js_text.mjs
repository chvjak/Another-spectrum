#!/usr/bin/env node
/** Export the compact 8x8 intro text blob from another_js and a VM trace. */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const [dataPath, tracePath, outputPath] = process.argv.slice(2);
if (!outputPath) {
  throw new Error('usage: export_another_js_text.mjs ootwdemo.js optimizer-trace.log output.bin');
}

const context = { console };
context.globalThis = context;
vm.createContext(context);
const source = fs.readFileSync(dataPath, 'utf8') + `
globalThis.__aw_strings_en = strings_en;
globalThis.__aw_font = font;
`;
vm.runInContext(source, context, { filename: dataPath });
const strings = context.__aw_strings_en;
const font = Uint8Array.from(context.__aw_font);
if (font.length !== 96 * 8) throw new Error(`unexpected font bytes ${font.length}`);

const used = new Set();
let tick = -1;
let pendingString = null;
for (const line of fs.readFileSync(tracePath, 'utf8').split('\n')) {
  let match = line.match(/^TRACE_TICK (\d+)/);
  if (match) {
    tick = Number(match[1]);
    continue;
  }
  match = line.match(/^Script::op_drawString\((\d+),/);
  if (match) {
    pendingString = { id: Number(match[1]), tick };
    continue;
  }
  match = line.match(/^SEM glyph buffer=(\d+)/);
  if (match && pendingString !== null) {
    const buffer = Number(match[1]);
    const sampled = pendingString.tick === 0 || (
      pendingString.tick >= 8 && (pendingString.tick - 8) % 10 === 0
    );
    if (buffer === 0 || sampled) used.add(pendingString.id);
    pendingString = null;
  }
}
const ids = [...used].sort((a, b) => a - b);
for (const id of ids) {
  if (!(id in strings)) throw new Error(`missing English string ${id}`);
}

const characters = new Set();
for (const id of ids) {
  for (const character of Buffer.from(strings[id], 'latin1')) {
    if (character !== 10 && character !== 13) characters.add(character);
  }
}
const orderedCharacters = [...characters].sort((a, b) => a - b);
const glyphMap = Buffer.alloc(96, 0xff);
const glyphs = [];
for (const [slot, character] of orderedCharacters.entries()) {
  if (character < 0x20 || character > 0x7f) {
    throw new Error(`unsupported text byte ${character}`);
  }
  glyphMap[character - 0x20] = slot;
  glyphs.push(Buffer.from(font.slice((character - 0x20) * 8, (character - 0x1f) * 8)));
}

const headerSize = 7 + ids.length * 4;
const textParts = [];
const entries = Buffer.alloc(ids.length * 4);
let textLength = 0;
for (const [index, id] of ids.entries()) {
  const payload = Buffer.concat([Buffer.from(strings[id], 'latin1'), Buffer.from([0])]);
  entries.writeUInt16LE(id, index * 4);
  entries.writeUInt16LE(headerSize + textLength, index * 4 + 2);
  textParts.push(payload);
  textLength += payload.length;
}
const glyphMapOffset = headerSize + textLength;
const glyphDataOffset = glyphMapOffset + glyphMap.length;
const header = Buffer.alloc(7);
header[0] = ids.length;
header.writeUInt16LE(headerSize, 1);
header.writeUInt16LE(glyphMapOffset, 3);
header.writeUInt16LE(glyphDataOffset, 5);
const output = Buffer.concat([header, entries, ...textParts, glyphMap, ...glyphs]);
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, output);
console.log(JSON.stringify({
  strings: ids.length,
  characters: orderedCharacters.length,
  bytes: output.length,
}));
