import { createRequire } from 'node:module';


const require = createRequire(import.meta.url);
const { parseEngineData, serializeEngineData } = require('../node_modules/ag-psd/dist/engineData.js');


function clone(value) {
  return structuredClone(value);
}


function expandCollection(collection, count, label) {
  if (!Array.isArray(collection) || collection.length === 0) throw new Error(`Official Txt2 is missing ${label}`);
  if (!Number.isInteger(count) || count < 1) throw new Error(`Invalid ${label} count: ${count}`);
  if (collection.length > count) collection.splice(count);
  while (collection.length < count) collection.push(clone(collection[collection.length - 1]));
}


function colorValues(color, fallback) {
  const value = color ?? fallback;
  return [1, value.r / 255, value.g / 255, value.b / 255];
}


function synchronizeEditor(entry, layer) {
  const text = `${String(layer.text.text ?? '').replace(/\r?\n/g, '\r').replace(/\r+$/g, '')}\r`;
  const editor = entry?.['0'];
  const paragraphRuns = editor?.['5']?.['0'];
  const styleRuns = editor?.['6']?.['0'];
  if (!editor || !Array.isArray(paragraphRuns) || paragraphRuns.length === 0 || !Array.isArray(styleRuns) || styleRuns.length === 0) {
    throw new Error('Official Txt2 editor template is incomplete');
  }
  editor['0'] = text;
  const paragraphRun = clone(paragraphRuns[0]);
  paragraphRun['1'] = text.length;
  editor['5']['0'] = [paragraphRun];
  const styleRun = clone(styleRuns[0]);
  styleRun['1'] = text.length;
  const styleData = styleRun?.['0']?.['0']?.['6'];
  if (!styleData) throw new Error('Official Txt2 style template is incomplete');
  const style = layer.text.style ?? {};
  styleData['0'] = style.font?.name === 'FZLTHJW--GB1-0' ? 1 : 0;
  styleData['1'] = style.fontSize ?? styleData['1'];
  styleData['2'] = style.fauxBold ?? false;
  styleData['3'] = style.fauxItalic ?? false;
  styleData['4'] = style.autoLeading ?? false;
  styleData['5'] = style.leading ?? style.fontSize * 1.2;
  styleData['6'] = style.horizontalScale ?? 1;
  styleData['7'] = style.verticalScale ?? 1;
  styleData['8'] = style.tracking ?? 0;
  styleData['9'] = style.baselineShift ?? 0;
  styleData['11'] = style.kerning ?? 0;
  styleData['12'] = style.fontCaps ?? 0;
  styleData['13'] = style.fontBaseline ?? 0;
  styleData['18'] = style.ligatures ?? true;
  styleData['19'] = style.dLigatures ?? false;
  styleData['35'] = style.baselineDirection ?? 2;
  styleData['38'] = style.language ?? 0;
  styleData['52'] = style.noBreak ?? false;
  styleData['53'] = { '0': { '0': 1, '1': colorValues(style.fillColor, { r: 0, g: 0, b: 0 }) }, '99': '/SimplePaint' };
  styleData['54'] = { '0': { '0': 1, '1': colorValues(style.strokeColor, { r: 0, g: 0, b: 0 }) }, '99': '/SimplePaint' };
  editor['6']['0'] = [styleRun];
}


function serializeImplicitRoot(value) {
  const serialized = Buffer.from(serializeEngineData(value, true));
  let start = 0;
  while (/\s/.test(String.fromCharCode(serialized[start]))) start += 1;
  let end = serialized.length;
  while (end > 0 && /\s/.test(String.fromCharCode(serialized[end - 1]))) end -= 1;
  const wrapped = serialized[start] === 0x3c && serialized[start + 1] === 0x3c;
  const bodyStart = wrapped ? start + 2 : start;
  const bodyEnd = wrapped ? end - 2 : end;
  const body = serialized.subarray(bodyStart, bodyEnd).toString('latin1');
  return Buffer.from(` ${body.replace(/(^|\s)null(?=\s|$)/g, '$1/nil').trim()} `, 'latin1');
}


export function expandOfficialTextEngine(source, layers) {
  const parsed = parseEngineData(source);
  const textFrames = parsed?.['0']?.['8']?.['0'];
  const editors = parsed?.['1']?.['1'];
  expandCollection(textFrames, layers.length, 'TextFrameSet');
  expandCollection(editors, layers.length, 'per-layer EngineData');
  editors.forEach((entry, index) => synchronizeEditor(entry, layers[index]));
  const expanded = serializeImplicitRoot(parsed);
  const roundTrip = parseEngineData(expanded);
  if (roundTrip?.['0']?.['8']?.['0']?.length !== layers.length || roundTrip?.['1']?.['1']?.length !== layers.length) {
    throw new Error('Expanded Txt2 did not round-trip with the requested frame count');
  }
  return expanded;
}
