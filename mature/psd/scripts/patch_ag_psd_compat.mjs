import fs from 'node:fs';
import path from 'node:path';


function replaceOrVerify(source, original, replacement, filePath) {
  if (source.includes(replacement)) return source;
  if (!source.includes(original)) throw new Error(`Unable to patch ag-psd file: ${filePath}`);
  return source.replace(original, replacement);
}


export function patchAgPsdForJd(root) {
  const files = [
    ['dist', 'psdWriter.js'],
    ['dist-es', 'psdWriter.js'],
    ['src', 'psdWriter.ts'],
  ];
  for (const parts of files) {
    const filePath = path.join(root, 'node_modules', 'ag-psd', ...parts);
    if (!fs.existsSync(filePath)) continue;
    let source = fs.readFileSync(filePath, 'utf8');
    const original = source;
    source = source.replace(
      'function writeSection(writer, round, func, writeTotalLength = false, large = false, absoluteRound = false) {',
      'function writeSection(writer, round, func, writeTotalLength = false, large = false) {',
    );
    source = source.replace('while ((absoluteRound ? writer.offset : len) % round) {', 'while (len % round) {');
    source = source.replace("}, writeTotalLength, large, key === 'TySh');", '}, writeTotalLength, large);');
    source = source.replace(
      "if (key === 'Txt2' || key === 'TySh' && options.invalidateTextLayers) continue;",
      "if (key === 'TySh' && options.invalidateTextLayers) continue;",
    );
    source = source.replace(
      /if \(key === 'Txt2' \|\| key === 'TySh' && options\.invalidateTextLayers\)(\s*)continue;/,
      "if (key === 'TySh' && options.invalidateTextLayers)$1continue;",
    );
    source = replaceOrVerify(
      source,
      "const fourBytes = key === 'Txt2' || key === 'luni'",
      "const fourBytes = key === 'Txt2' || key === 'TySh' || key === 'luni'",
      filePath,
    );
    if (source !== original) fs.writeFileSync(filePath, source, 'utf8');
  }
}
