import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readPsd } from 'ag-psd';


export function verifyJdTemplate(psdPath, expectedLayers, officialEngineExpected = false) {
  const psd = readPsd(fs.readFileSync(psdPath), { skipLayerImageData: true, skipCompositeImageData: true });
  const layers = psd.children ?? [];
  const textLayers = layers.filter((layer) => layer.text);
  const layerIds = layers.map((layer) => layer.id);
  const checks = {
    exactSize: psd.width === 800 && psd.height === 800,
    onePixelBackground: layers.filter((layer) => !layer.text).length === 1,
    expectedLayerNames: layers.map((layer) => layer.name).join('\0') === expectedLayers.map((layer) => layer.name).join('\0'),
    positiveUniqueLayerIds: layerIds.every((id) => Number.isInteger(id) && id > 0) && new Set(layerIds).size === layerIds.length,
    tightLayerBounds: layers.every((layer, index) => {
      const expected = expectedLayers[index];
      return layer.left === expected.bounds[0] && layer.top === expected.bounds[1] && layer.right === expected.bounds[2] && layer.bottom === expected.bounds[3];
    }),
    textIndices: textLayers.every((layer, index) => layer.text.index === index),
    underSizeLimit: fs.statSync(psdPath).size < 200 * 1024 * 1024,
  };
  const officialTextEngine = Boolean(psd.engineData);
  return {
    valid: Object.values(checks).every(Boolean),
    checks,
    officialTextEngine,
    jdReady: Object.values(checks).every(Boolean) && officialEngineExpected && officialTextEngine,
    width: psd.width,
    height: psd.height,
    bytes: fs.statSync(psdPath).size,
    layers: layers.map((layer) => ({
      name: layer.name,
      layerId: layer.id,
      type: layer.text ? 'text' : 'pixel',
      bounds: [layer.left, layer.top, layer.right, layer.bottom],
    })),
  };
}


function sha256(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex').toUpperCase();
}


function resolveInside(base, relativePath) {
  const target = path.resolve(base, relativePath);
  const relative = path.relative(base, target);
  if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error(`模板路径越界：${relativePath}`);
  return target;
}


export function verifyTemplatePackage(manifestPath) {
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const base = path.dirname(path.resolve(manifestPath));
  const dynamicLayers = [...(manifest.dynamicFields ?? [])]
    .sort((left, right) => left.layerId - right.layerId)
    .map((field) => ({ name: field.psdLayerName, bounds: field.bounds }));
  const expectedLayers = [
    { name: manifest.backgroundLayer.psdLayerName, bounds: manifest.backgroundLayer.bounds },
    ...dynamicLayers,
    ...(manifest.automaticPriceLayer ? [{ name: manifest.automaticPriceLayer.psdLayerName, bounds: manifest.automaticPriceLayer.bounds }] : []),
  ];
  const psdPath = resolveInside(base, manifest.psdPath);
  const structure = verifyJdTemplate(psdPath, expectedLayers, Boolean(manifest.verification?.officialTextEngine));
  const fileChecks = Object.entries(manifest.files ?? {}).map(([relativePath, expected]) => {
    const filePath = resolveInside(base, relativePath);
    return { relativePath, valid: fs.existsSync(filePath) && sha256(filePath) === String(expected).toUpperCase() };
  });
  const columns = manifest.jdExcelColumns ?? [];
  const manifestChecks = {
    schemaVersion: manifest.schemaVersion === 1,
    filesPresentAndHashed: fileChecks.length > 0 && fileChecks.every((check) => check.valid),
    jdColumns: columns[0] === 'SKUID' && !columns.includes('价格') && new Set(columns).size === columns.length,
  };
  return {
    ...structure,
    valid: structure.valid && Object.values(manifestChecks).every(Boolean),
    manifestChecks,
    fileChecks,
  };
}


if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const manifestIndex = args.indexOf('--manifest');
  if (!args[0] || manifestIndex < 0 || !args[manifestIndex + 1]) throw new Error('用法：verify_jd_template.mjs <psd> --manifest <template.json>');
  const result = verifyTemplatePackage(path.resolve(args[manifestIndex + 1]));
  if (path.resolve(args[0]) !== path.resolve(path.dirname(args[manifestIndex + 1]), JSON.parse(fs.readFileSync(args[manifestIndex + 1], 'utf8')).psdPath)) {
    throw new Error('命令行 PSD 路径与 manifest 不一致');
  }
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.valid ? 0 : 1);
}
