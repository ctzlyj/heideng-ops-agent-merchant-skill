// Local entry for both POP skills. The runtime cache contains code and npm dependencies only.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');

const root = path.dirname(__dirname);
const runtimeFiles = ['package.json', 'package-lock.json', 'scripts/build_jd_template.mjs',
  'scripts/verify_jd_template.mjs', 'scripts/global_text_engine.mjs', 'scripts/patch_ag_psd_compat.mjs'];

function runtimeLocation() {
  const hash = crypto.createHash('sha256');
  for (const name of runtimeFiles) hash.update(name).update(fs.readFileSync(path.join(root, name)));
  const home = process.env.HEIDENG_MERCHANT_HOME || process.env.HEIDENG_POP_HOME ||
    path.join(os.homedir(), '.heideng');
  return path.join(home, 'optional-runtimes', 'psd', hash.digest('hex'));
}

function npmCommand() {
  if (process.platform !== 'win32') return ['npm'];
  const dirs = [path.dirname(process.execPath), ...(process.env.PATH || '').split(path.delimiter)];
  for (const dir of dirs) {
    if (!path.isAbsolute(dir)) continue;
    const npm = path.join(dir, 'node_modules', 'npm', 'bin', 'npm-cli.js');
    if (fs.existsSync(npm)) return [process.execPath, npm];
  }
  throw new Error('本地 PSD 制作需要 Node 与 npm；安装可用的 Node 后可继续本任务。');
}

function ready(directory) {
  return fs.existsSync(path.join(directory, '.ready')) && runtimeFiles.every(name =>
    fs.existsSync(path.join(directory, name)) &&
    fs.readFileSync(path.join(directory, name)).equals(fs.readFileSync(path.join(root, name)))) &&
    ['ag-psd','pngjs'].every(name => fs.existsSync(path.join(directory, 'node_modules', name, 'package.json')));
}

async function prepare(directory) {
  if (ready(directory)) return;
  const parent = path.dirname(directory);
  fs.mkdirSync(parent, { recursive: true });
  const scratch = fs.mkdtempSync(path.join(parent, '.prepare-'));
  try {
    fs.mkdirSync(path.join(scratch, 'scripts'));
    for (const name of runtimeFiles) fs.copyFileSync(path.join(root, name), path.join(scratch, name));
    const [program, ...prefix] = npmCommand();
    const install = spawnSync(program, [...prefix, 'ci', '--ignore-scripts', '--no-audit', '--no-fund',
      '--registry=https://registry.npmjs.org'], { cwd:scratch, encoding:'utf8', timeout:180000, windowsHide:true });
    if (install.error || install.status !== 0) throw new Error('PSD 的锁定 npm 依赖未准备成功，检查本机 npm 与公开源连接。');
    const patcher = await import(pathToFileURL(path.join(scratch, 'scripts', 'patch_ag_psd_compat.mjs')).href);
    patcher.patchAgPsdForJd(scratch);
    fs.writeFileSync(path.join(scratch, '.ready'), '');
    // Every writer builds outside the published runtime. Repair an incomplete cache
    // without altering any scripts another invocation is currently loading.
    if (fs.existsSync(directory) && !ready(directory)) {
      try {
        fs.renameSync(directory, path.join(parent, '.retired-' + crypto.randomUUID()));
      } catch (error) {
        if (error.code !== 'ENOENT' && !ready(directory)) throw error;
      }
    }
    try {
      fs.renameSync(scratch, directory);
    } catch (error) {
      if (!ready(directory)) throw error;
    }
  } finally {
    fs.rmSync(scratch, { recursive:true, force:true });
  }
}

function option(args, name, required = false) {
  const index = args.indexOf(name);
  if (index < 0 && !required) return null;
  if (index < 0 || !args[index+1] || args[index+1].startsWith('--')) throw new Error('缺少参数 ' + name);
  return path.resolve(args[index+1]);
}

async function main(args) {
  const [command, ...flags] = args;
  const directory = runtimeLocation();
  if (command === 'status') return { ready:ready(directory), optional:true, platformWrites:0 };
  if (!['prepare','build','verify'].includes(command)) throw new Error('可用命令：status / prepare / build / verify');
  const sourcePath = command === 'build' && option(flags,'--source',true);
  const specPath = command === 'build' && option(flags,'--spec',true);
  const outputDir = command === 'build' && option(flags,'--output-dir',true);
  const manifestPath = command === 'verify' && option(flags,'--manifest',true);
  for (const supplied of [sourcePath, specPath, manifestPath]) {
    if (supplied && !fs.statSync(supplied).isFile()) throw new Error('输入应为本地文件：' + supplied);
  }
  await prepare(directory);
  if (command === 'prepare') return { ready:true, optional:true, platformWrites:0 };
  if (command === 'verify') {
    const {verifyTemplatePackage} = await import(pathToFileURL(path.join(directory,'scripts/verify_jd_template.mjs')).href);
    const result = verifyTemplatePackage(manifestPath);
    return {...result, localStatus:result.valid ? 'passed' : 'failed', jdReady:result.valid && result.jdReady,
      jdUploadStatus:'pending', platformWrites:0};
  }
  const {buildJdTemplate} = await import(pathToFileURL(path.join(directory,'scripts/build_jd_template.mjs')).href);
  const result = await buildJdTemplate({sourcePath,specPath,outputDir,
    officialEnginePath:option(flags,'--official-engine'), requireOfficialEngine:flags.includes('--require-official-engine'),
    overwrite:flags.includes('--overwrite')});
  const manifest = JSON.parse(fs.readFileSync(result.manifestPath,'utf8'));
  return {...result, ...manifest.verification, jdExcelColumns:manifest.jdExcelColumns, platformWrites:0};
}

if (require.main === module) main(process.argv.slice(2)).then(result => {
  console.log(JSON.stringify(result, null, 2));
  if (result.valid === false) process.exitCode = 2;
}).catch(error => {
  console.error(JSON.stringify({status:'blocked', reason:error.message, platformWrites:0}));
  process.exitCode = 2;
});
