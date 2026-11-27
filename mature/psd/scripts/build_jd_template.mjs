import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PNG } from 'pngjs';

import { expandOfficialTextEngine } from './global_text_engine.mjs';
import { patchAgPsdForJd } from './patch_ag_psd_compat.mjs';
import { verifyJdTemplate } from './verify_jd_template.mjs';


const skillRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const bundledOfficialEnginePath = path.join(skillRoot, 'assets', 'official_text_engine.bin');
const templateIdPattern = /^[a-z0-9][a-z0-9-]*$/;
const jdColumnPattern = /^文案([1-5])$/;


function readPng(filePath) {
  const png = PNG.sync.read(fs.readFileSync(filePath));
  return { width: png.width, height: png.height, data: new Uint8ClampedArray(png.data) };
}


function writePng(image, filePath) {
  fs.writeFileSync(filePath, PNG.sync.write({ width: image.width, height: image.height, data: Buffer.from(image.data) }));
}


function cloneImage(image) {
  return { width: image.width, height: image.height, data: new Uint8ClampedArray(image.data) };
}


function validatedBounds(value) {
  if (!Array.isArray(value) || value.length !== 4 || value.some((item) => !Number.isInteger(item))) {
    throw new Error('图层 bounds 必须是四个整数');
  }
  const [left, top, right, bottom] = value;
  if (!(0 <= left && left < right && right <= 800 && 0 <= top && top < bottom && bottom <= 800)) {
    throw new Error('图层 bounds 必须位于 800×800 画布内');
  }
  return value;
}


function median(values) {
  values.sort((left, right) => left - right);
  return values[Math.floor(values.length / 2)];
}


function sampleBackground(source, bounds, explicitColor) {
  if (Array.isArray(explicitColor) && (explicitColor.length === 3 || explicitColor.length === 4)) {
    return [explicitColor[0], explicitColor[1], explicitColor[2], explicitColor[3] ?? 255];
  }
  const [left, top, right, bottom] = bounds;
  const samples = [[], [], [], []];
  const padding = 3;
  for (let y = Math.max(0, top - padding); y < Math.min(800, bottom + padding); y += 1) {
    for (let x = Math.max(0, left - padding); x < Math.min(800, right + padding); x += 1) {
      if (x >= left && x < right && y >= top && y < bottom) continue;
      const offset = (y * source.width + x) * 4;
      for (let channel = 0; channel < 4; channel += 1) samples[channel].push(source.data[offset + channel]);
    }
  }
  if (samples[0].length === 0) throw new Error('无法采样文字区域背景色');
  return samples.map(median);
}


function extractFallbackLayer(source, bounds, backgroundColor, tolerance) {
  const [left, top, right, bottom] = bounds;
  const width = right - left;
  const height = bottom - top;
  const output = { width, height, data: new Uint8ClampedArray(width * height * 4) };
  let visible = 0;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const sourceOffset = ((top + y) * source.width + left + x) * 4;
      const targetOffset = (y * width + x) * 4;
      const closeToBackground = [0, 1, 2, 3].every(
        (channel) => Math.abs(source.data[sourceOffset + channel] - backgroundColor[channel]) <= tolerance,
      );
      if (closeToBackground) continue;
      for (let channel = 0; channel < 4; channel += 1) output.data[targetOffset + channel] = source.data[sourceOffset + channel];
      if (output.data[targetOffset + 3] > 0) visible += 1;
    }
  }
  if (visible === 0) throw new Error(`文字区域没有可见像素：${bounds.join(',')}`);
  return output;
}


function eraseRegion(background, bounds, color) {
  const [left, top, right, bottom] = bounds;
  for (let y = top; y < bottom; y += 1) {
    for (let x = left; x < right; x += 1) {
      const offset = (y * background.width + x) * 4;
      for (let channel = 0; channel < 4; channel += 1) background.data[offset + channel] = color[channel];
    }
  }
}


function textStyle(field) {
  const [red, green, blue] = field.font.color ?? [0, 0, 0];
  return {
    font: { name: field.font.name, script: 3, type: 1, synthetic: 0 },
    fontSize: field.font.fontSize,
    fauxBold: false,
    fauxItalic: false,
    autoLeading: false,
    leading: field.font.fontSize * 1.2,
    horizontalScale: 1,
    verticalScale: 1,
    tracking: 0,
    autoKerning: true,
    kerning: 0,
    baselineShift: 0,
    fontCaps: 0,
    fontBaseline: 0,
    underline: false,
    strikethrough: false,
    ligatures: true,
    dLigatures: false,
    baselineDirection: 2,
    language: 0,
    noBreak: false,
    fillColor: { r: red, g: green, b: blue },
    strokeColor: { r: red, g: green, b: blue },
  };
}


function makeTextLayer(field, name, layerId, textIndex, source, background, tolerance) {
  const bounds = validatedBounds(field.bounds);
  if (!field.font || typeof field.font.name !== 'string' || !(field.font.fontSize > 0)) throw new Error(`文字层字体信息不完整：${name}`);
  if (field.backgroundMode === 'complex') throw new Error(`复杂背景必须先提供 clean background：${name}`);
  const backgroundColor = sampleBackground(source, bounds, field.backgroundColor);
  const imageData = extractFallbackLayer(source, bounds, backgroundColor, tolerance);
  eraseRegion(background, bounds, backgroundColor);
  const [left, top, right, bottom] = bounds;
  const fontSize = field.font.fontSize;
  const unit = (value) => ({ value, units: 'Points' });
  return {
    name,
    id: layerId,
    left,
    top,
    imageData,
    blendMode: 'normal',
    opacity: 1,
    hidden: false,
    text: {
      text: String(field.sampleText ?? ''),
      index: textIndex,
      transform: [1, 0, 0, 1, left, bottom],
      antiAlias: 'smooth',
      orientation: 'horizontal',
      shapeType: 'point',
      pointBase: [0, 0],
      left: 0,
      top: 0,
      right: 0,
      bottom: 0,
      bounds: { top: unit(-fontSize), left: unit(0), right: unit(right - left), bottom: unit(fontSize * 0.25) },
      boundingBox: { top: unit(top - bottom), left: unit(0), right: unit(right - left), bottom: unit(0) },
      style: textStyle(field),
      paragraphStyle: { justification: 'left' },
    },
  };
}


function sha256(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex').toUpperCase();
}


function validateSpec(spec) {
  if (spec.schemaVersion !== 1) throw new Error('仅支持 schemaVersion 1');
  if (!templateIdPattern.test(spec.templateId ?? '')) throw new Error('templateId 只能包含小写字母、数字和短横线');
  if (!Array.isArray(spec.dynamicFields) || spec.dynamicFields.length > 5) throw new Error('最多 5 个动态文案');
  spec.dynamicFields.forEach((field, index) => {
    const expected = `文案${index + 1}`;
    if (!jdColumnPattern.test(field.jdColumn ?? '') || field.jdColumn !== expected) throw new Error(`动态文案列必须连续并按顺序排列：${expected}`);
  });
  if (spec.automaticPriceLayer !== null && spec.automaticPriceLayer !== undefined && typeof spec.automaticPriceLayer !== 'object') {
    throw new Error('automaticPriceLayer 必须是对象或 null');
  }
}


export async function buildJdTemplate({ sourcePath, specPath, outputDir, officialEnginePath = null, requireOfficialEngine = false, overwrite = false }) {
  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
  validateSpec(spec);
  if (officialEnginePath && !fs.existsSync(officialEnginePath)) throw new Error(`官方文字引擎不存在：${officialEnginePath}`);
  const resolvedOfficialEnginePath = officialEnginePath
    ? path.resolve(officialEnginePath)
    : (fs.existsSync(bundledOfficialEnginePath) ? bundledOfficialEnginePath : null);
  if (requireOfficialEngine && !resolvedOfficialEnginePath) throw new Error('必须提供合法的官方文字引擎文件');

  const source = readPng(sourcePath);
  if (source.width !== 800 || source.height !== 800) throw new Error('京东模板源图必须是 800×800');
  outputDir = path.resolve(outputDir);
  if (fs.existsSync(path.join(outputDir, 'template.json')) && !overwrite) throw new Error(`模板输出目录已存在：${outputDir}`);
  fs.mkdirSync(outputDir, { recursive: true });
  const background = spec.cleanBackgroundImage ? readPng(path.resolve(path.dirname(specPath), spec.cleanBackgroundImage)) : cloneImage(source);
  if (background.width !== 800 || background.height !== 800) throw new Error('clean background 必须是 800×800');
  const tolerance = Number.isFinite(spec.backgroundTolerance) ? spec.backgroundTolerance : 12;

  const dynamicCount = spec.dynamicFields.length;
  const mappedFields = spec.dynamicFields.map((field, index) => ({
    ...field,
    psdLayerName: `文案${dynamicCount - index}`,
    layerId: dynamicCount - index + 1,
  }));
  const physicalFields = [...mappedFields].reverse();
  const textLayers = [];
  for (const field of physicalFields) {
    textLayers.push(makeTextLayer(field, field.psdLayerName, field.layerId, textLayers.length, source, background, tolerance));
  }
  let automaticPriceLayer = null;
  if (spec.automaticPriceLayer) {
    const field = { ...spec.automaticPriceLayer, font: spec.automaticPriceLayer.font };
    const layerId = dynamicCount + 2;
    textLayers.push(makeTextLayer(field, '自动价格', layerId, textLayers.length, source, background, tolerance));
    automaticPriceLayer = {
      ...spec.automaticPriceLayer,
      logicalName: '自动价格',
      jdField: '价格',
      psdLayerName: '自动价格',
      layerId,
    };
  }

  patchAgPsdForJd(skillRoot);
  const { writePsdBuffer } = await import('ag-psd');
  const backgroundLayer = {
    name: '背景装饰',
    id: 1,
    left: 0,
    top: 0,
    imageData: background,
    blendMode: 'normal',
    opacity: 1,
    hidden: false,
  };
  const psd = { width: 800, height: 800, imageData: source, children: [backgroundLayer, ...textLayers] };
  const hasOfficialEngine = Boolean(resolvedOfficialEnginePath && textLayers.length > 0);
  if (hasOfficialEngine) psd.engineData = expandOfficialTextEngine(fs.readFileSync(resolvedOfficialEnginePath), textLayers).toString('base64');

  const psdPath = path.join(outputDir, `${spec.templateId}.psd`);
  const previewPath = path.join(outputDir, `${spec.templateId}_preview.png`);
  const transparentPath = path.join(outputDir, `${spec.templateId}_transparent.png`);
  const copiedSourcePath = path.join(outputDir, 'source.png');
  const validationPath = path.join(outputDir, 'validation.json');
  const manifestPath = path.join(outputDir, 'template.json');
  fs.writeFileSync(psdPath, writePsdBuffer(psd, { generateThumbnail: false, noBackground: true, trimImageData: false, invalidateTextLayers: false }));
  writePng(source, previewPath);
  writePng(source, transparentPath);
  writePng(source, copiedSourcePath);

  const expectedLayers = [
    { name: '背景装饰', bounds: [0, 0, 800, 800] },
    ...physicalFields.map((field) => ({ name: field.psdLayerName, bounds: field.bounds })),
    ...(automaticPriceLayer ? [{ name: '自动价格', bounds: automaticPriceLayer.bounds }] : []),
  ];
  const verification = verifyJdTemplate(psdPath, expectedLayers, hasOfficialEngine);
  fs.writeFileSync(validationPath, JSON.stringify({
    schemaVersion: 1,
    localStatus: verification.valid ? 'passed' : 'failed',
    jdReady: verification.jdReady,
    jdUploadStatus: 'pending',
    ...verification,
  }, null, 2), 'utf8');
  if (!verification.valid) throw new Error(`PSD 本地结构验证失败：${JSON.stringify(verification.checks)}`);

  const manifest = {
    schemaVersion: 1,
    templateId: spec.templateId,
    displayName: spec.displayName,
    version: spec.version ?? '1.0.0',
    sourceImage: 'source.png',
    psdPath: path.basename(psdPath),
    previewPath: path.basename(previewPath),
    transparentPath: path.basename(transparentPath),
    validationPath: path.basename(validationPath),
    canvas: { width: 800, height: 800, colorMode: 'RGB', bitsPerChannel: 8 },
    backgroundLayer: { psdLayerName: '背景装饰', layerId: 1, bounds: [0, 0, 800, 800] },
    automaticPriceLayer,
    dynamicFields: mappedFields,
    pricingProfile: spec.pricingProfile ?? null,
    formula: spec.formula ?? null,
    parameters: spec.parameters ?? [],
    jdExcelColumns: ['SKUID', ...mappedFields.map((field) => field.jdColumn)],
    jdImportNotes: '京东导入时价格列必须留空或选择不导入；文案列分别映射 Excel 同名列。',
    verification: {
      localStatus: 'passed',
      jdReady: verification.jdReady,
      jdUploadStatus: 'pending',
      officialTextEngine: verification.officialTextEngine,
    },
    files: {
      [path.basename(psdPath)]: sha256(psdPath),
      [path.basename(previewPath)]: sha256(previewPath),
      [path.basename(transparentPath)]: sha256(transparentPath),
      'source.png': sha256(copiedSourcePath),
    },
  };
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf8');
  return { psdPath, previewPath, transparentPath, sourcePath: copiedSourcePath, validationPath, manifestPath };
}


function argument(args, name, fallback = null) {
  const index = args.indexOf(name);
  return index >= 0 && index + 1 < args.length ? args[index + 1] : fallback;
}


if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const result = await buildJdTemplate({
    sourcePath: path.resolve(argument(args, '--source')),
    specPath: path.resolve(argument(args, '--spec')),
    outputDir: path.resolve(argument(args, '--output-dir')),
    officialEnginePath: argument(args, '--official-engine'),
    requireOfficialEngine: args.includes('--require-official-engine'),
    overwrite: args.includes('--overwrite'),
  });
  console.log(JSON.stringify(result, null, 2));
}
