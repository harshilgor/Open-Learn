const { app, autoUpdater, BrowserWindow, dialog, ipcMain, Menu, Notification, safeStorage, shell } = require('electron');
const { spawn } = require('node:child_process');
const { existsSync } = require('node:fs');
const { readFileSync, writeFileSync, mkdirSync } = require('node:fs');
const { randomBytes } = require('node:crypto');
const net = require('node:net');
const path = require('node:path');
const http = require('node:http');
const { startWebServer } = require('./web-server.cjs');

if (require('electron-squirrel-startup')) app.quit();

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) app.quit();

const isDev = process.argv.includes('--dev') || !app.isPackaged;
const projectRoot = path.resolve(__dirname, '..', '..');
const configuredApiPort = Number(process.env.FORMA_API_PORT);
let apiPort = Number.isInteger(configuredApiPort) && configuredApiPort > 0 && configuredApiPort < 65536 ? configuredApiPort : undefined;
let webPort;
let apiProcess;
let webProcess;
let window;
let apiToken;
let shuttingDown = false;
let restartAttempts = 0;
let restartTimer;
let reviewTimer;
const updateRepository = 'harshilgor/AI-Tutor-Harness-';
let updateStatus = { state: 'unavailable', currentVersion: app.getVersion() };

function publishUpdateStatus(next) {
  updateStatus = { ...updateStatus, ...next, currentVersion: app.getVersion() };
  window?.webContents.send('forma:update-status', updateStatus);
  return updateStatus;
}

function canCheckForUpdates() {
  return app.isPackaged && !isDev && process.platform === 'win32';
}

function comparableVersion(value) {
  const match = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/.exec(value || '');
  if (!match) return null;
  return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] || ''];
}

function isNewerVersion(candidate, current) {
  const next = comparableVersion(candidate); const installed = comparableVersion(current);
  if (!next || !installed) return false;
  for (let index = 0; index < 3; index += 1) if (next[index] !== installed[index]) return next[index] > installed[index];
  // A release build supersedes a prerelease of the same numeric version.
  return Boolean(installed[3]) && !next[3];
}

async function latestReleaseFeed() {
  const response = await fetch(`https://api.github.com/repos/${updateRepository}/releases?per_page=30`, {
    headers: { Accept: 'application/vnd.github+json', 'User-Agent': `Forma/${app.getVersion()}` }
  });
  if (!response.ok) throw new Error(`GitHub could not check for updates (${response.status}).`);
  const releases = await response.json();
  if (!Array.isArray(releases)) throw new Error('GitHub returned an invalid release list.');
  const current = app.getVersion();
  const compatible = releases.filter(release => !release.draft && typeof release.tag_name === 'string' && isNewerVersion(release.tag_name, current) && Array.isArray(release.assets) && release.assets.some(asset => asset.name === 'RELEASES') && release.assets.some(asset => /-full\.nupkg$/i.test(asset.name)));
  compatible.sort((left, right) => isNewerVersion(left.tag_name, right.tag_name) ? -1 : 1);
  const release = compatible[0];
  if (!release) return null;
  return { version: release.tag_name.replace(/^v/, ''), url: `https://github.com/${updateRepository}/releases/download/${encodeURIComponent(release.tag_name)}` };
}

async function checkForUpdates() {
  if (!canCheckForUpdates()) return publishUpdateStatus({ state: 'unavailable', detail: 'Updates are available in installed Windows releases.' });
  try {
    publishUpdateStatus({ state: 'checking', detail: 'Checking for a new version…' });
    const release = await latestReleaseFeed();
    if (!release) return publishUpdateStatus({ state: 'up-to-date', detail: 'You have the latest Forma version.' });
    autoUpdater.setFeedURL({ url: release.url });
    publishUpdateStatus({ state: 'checking', availableVersion: release.version, detail: `Preparing Forma ${release.version}…` });
    autoUpdater.checkForUpdates();
    return updateStatus;
  } catch (error) {
    return publishUpdateStatus({ state: 'error', detail: error instanceof Error ? error.message : 'Forma could not check for updates.' });
  }
}

function configureUpdates() {
  ipcMain.handle('updates:status', () => updateStatus);
  ipcMain.handle('updates:check', () => checkForUpdates());
  ipcMain.handle('updates:install', () => {
    if (updateStatus.state !== 'ready') throw new Error('No downloaded update is ready to install.');
    autoUpdater.quitAndInstall();
    return true;
  });
  if (!canCheckForUpdates()) return;
  updateStatus = { state: 'idle', currentVersion: app.getVersion() };
  autoUpdater.on('checking-for-update', () => publishUpdateStatus({ state: 'checking', detail: 'Checking for a new version…' }));
  autoUpdater.on('update-available', event => publishUpdateStatus({ state: 'downloading', availableVersion: event.version, detail: `Downloading Forma ${event.version}…` }));
  autoUpdater.on('update-not-available', () => publishUpdateStatus({ state: 'up-to-date', detail: 'You have the latest Forma version.' }));
  autoUpdater.on('update-downloaded', event => publishUpdateStatus({ state: 'ready', availableVersion: event.version, detail: `Forma ${event.version} is ready to install.` }));
  autoUpdater.on('error', error => publishUpdateStatus({ state: 'error', detail: error.message || 'Forma could not download the update.' }));
}

function runtimePaths() {
  const root = app.getPath('userData');
  return {
    root,
    data: path.join(root, 'data'),
    materials: path.join(root, 'materials'),
    logs: path.join(root, 'logs'),
    cache: path.join(root, 'cache'),
  };
}

function ensureRuntimeDirectories() {
  const paths = runtimePaths();
  for (const directory of Object.values(paths)) mkdirSync(directory, { recursive: true });
  return paths;
}

function availableLoopbackPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(error => error ? reject(error) : resolve(address.port));
    });
  });
}

function credentialFile() { return path.join(app.getPath('userData'), 'credentials.json'); }
function preferencesFile() { return path.join(app.getPath('userData'), 'preferences.json'); }
function readPreferences() { try { return JSON.parse(readFileSync(preferencesFile(), 'utf8')); } catch { return {}; } }
function writePreferences(values) { mkdirSync(app.getPath('userData'), { recursive: true }); writeFileSync(preferencesFile(), JSON.stringify(values), { mode: 0o600 }); }
function readCredentials() {
  try { return JSON.parse(readFileSync(credentialFile(), 'utf8')); } catch { return {}; }
}
function writeCredentials(values) {
  mkdirSync(app.getPath('userData'), { recursive: true });
  writeFileSync(credentialFile(), JSON.stringify(values), { mode: 0o600 });
}
function readCredential(key) {
  const value = readCredentials()[key];
  if (!value || !safeStorage.isEncryptionAvailable()) return undefined;
  try { return safeStorage.decryptString(Buffer.from(value, 'base64')); } catch { return undefined; }
}
function configureCredentialBridge() {
  ipcMain.handle('credentials:has', (_event, key) => Boolean(readCredential(key)));
  ipcMain.handle('credentials:get', (_event, key) => {
    const value = readCredentials()[key];
    if (!value || !safeStorage.isEncryptionAvailable()) return null;
    try { return safeStorage.decryptString(Buffer.from(value, 'base64')); } catch { return null; }
  });
  ipcMain.handle('credentials:set', (_event, key, value) => {
    if (typeof key !== 'string' || !/^[a-z][a-z0-9_.-]{0,80}$/i.test(key) || typeof value !== 'string' || value.length > 20000) throw new Error('Invalid credential.');
    if (!safeStorage.isEncryptionAvailable()) throw new Error('Secure credential storage is unavailable on this device.');
    const values = readCredentials();
    values[key] = safeStorage.encryptString(value).toString('base64');
    writeCredentials(values);
    if (key === 'OPENAI_API_KEY' || key === 'OPENROUTER_API_KEY') {
      const provider = key === 'OPENAI_API_KEY' ? 'openai' : 'openrouter';
      writePreferences({ ...readPreferences(), modelProvider: provider });
    }
    return true;
  });
  ipcMain.handle('credentials:delete', (_event, key) => {
    const values = readCredentials(); delete values[key]; writeCredentials(values);
    const preferences = readPreferences();
    const removedProvider = key === 'OPENAI_API_KEY' ? 'openai' : key === 'OPENROUTER_API_KEY' ? 'openrouter' : undefined;
    if (removedProvider && preferences.modelProvider === removedProvider) {
      const { modelProvider: _removed, ...remaining } = preferences;
      writePreferences(remaining);
    }
    return true;
  });
  ipcMain.handle('preferences:get', () => {
    const saved = readPreferences();
    return {
      reviewNotifications: saved.reviewNotifications === true,
      quietHoursStart: Number.isInteger(saved.quietHoursStart) ? saved.quietHoursStart : 22,
      quietHoursEnd: Number.isInteger(saved.quietHoursEnd) ? saved.quietHoursEnd : 8,
    };
  });
  ipcMain.handle('preferences:set', (_event, values) => {
    if (!values || typeof values.reviewNotifications !== 'boolean'
        || !Number.isInteger(values.quietHoursStart) || values.quietHoursStart < 0 || values.quietHoursStart > 23
        || !Number.isInteger(values.quietHoursEnd) || values.quietHoursEnd < 0 || values.quietHoursEnd > 23) throw new Error('Invalid desktop preference.');
    const next = { ...readPreferences(), reviewNotifications: values.reviewNotifications, quietHoursStart: values.quietHoursStart, quietHoursEnd: values.quietHoursEnd };
    writePreferences(next);
    if (next.reviewNotifications) void notifyDueReviews();
    return { reviewNotifications: next.reviewNotifications, quietHoursStart: next.quietHoursStart, quietHoursEnd: next.quietHoursEnd };
  });
}

function notifyServiceStatus(status) { window?.webContents.send('forma:service-status', status); }

async function notifyDueReviews() {
  const preferences = readPreferences();
  if (!preferences.reviewNotifications || !apiPort || !apiToken || !Notification.isSupported()) return;
  const quietStart = Number.isInteger(preferences.quietHoursStart) ? preferences.quietHoursStart : 22;
  const quietEnd = Number.isInteger(preferences.quietHoursEnd) ? preferences.quietHoursEnd : 8;
  const localHour = new Date().getHours();
  const quietNow = quietStart === quietEnd || (quietStart < quietEnd ? localHour >= quietStart && localHour < quietEnd : localHour >= quietStart || localHour < quietEnd);
  if (quietNow) return;
  try {
    const response = await fetch(`http://127.0.0.1:${apiPort}/v1/learners/local/review-queue`, { headers: { 'X-Forma-Desktop-Token': apiToken } });
    if (!response.ok) return;
    const due = await response.json();
    const notified = preferences.notifiedReviewKeys && typeof preferences.notifiedReviewKeys === 'object' ? preferences.notifiedReviewKeys : {};
    let changed = false;
    for (const review of due) {
      const key = `${review.id}:${review.due_at}`;
      if (notified[key]) continue;
      new Notification({ title: 'A Forma review is ready', body: `Revisit ${review.concept_id.replace(/[_-]/g, ' ')} while it is fresh.` }).show();
      notified[key] = new Date().toISOString(); changed = true;
    }
    if (changed) writePreferences({ ...preferences, notifiedReviewKeys: notified });
  } catch (error) { console.error('Could not check due Forma reviews', error); }
}

function startReviewNotifications() {
  clearInterval(reviewTimer);
  void notifyDueReviews();
  reviewTimer = setInterval(() => void notifyDueReviews(), 5 * 60 * 1000);
}

function scheduleApiRestart() {
  if (shuttingDown || restartTimer || restartAttempts >= 3) return;
  const delay = 1000 * (2 ** restartAttempts); restartAttempts += 1;
  notifyServiceStatus({ state: 'restarting', attempt: restartAttempts });
  restartTimer = setTimeout(() => {
    restartTimer = undefined;
    startApi().then(() => { restartAttempts = 0; startReviewNotifications(); notifyServiceStatus({ state: 'ready' }); })
      .catch(error => { console.error('Forma API restart failed', error); scheduleApiRestart(); });
  }, delay);
}

function configureApplicationMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { role: 'appMenu' },
    { label: 'File', submenu: [
      { label: 'Local data settings', click: () => window?.webContents.send('forma:open-settings') },
      { label: 'Check for updates', click: () => { void checkForUpdates(); window?.webContents.send('forma:open-settings'); } },
      { type: 'separator' },
      { role: 'quit' },
    ] },
    { role: 'viewMenu' },
    { role: 'windowMenu' },
  ]));
}

function checkHealth() {
  return new Promise(resolve => {
    const request = http.get(`http://127.0.0.1:${apiPort}/health`, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { body += chunk; });
      response.on('end', () => {
        try { resolve(response.statusCode === 200 && JSON.parse(body).service === 'learning-harness'); }
        catch { resolve(false); }
      });
    });
    request.setTimeout(1500, () => { request.destroy(); resolve(false); });
    request.on('error', () => resolve(false));
  });
}

function pythonExecutable() {
  const configured = process.env.FORMA_PYTHON;
  if (configured && existsSync(configured)) return configured;
  const executableName = process.platform === 'win32' ? 'forma-api.exe' : 'forma-api';
  const bundledCandidates = [
    path.join(process.resourcesPath, 'backend', 'forma-api', executableName),
    path.join(process.resourcesPath, 'backend', executableName),
  ];
  if (!isDev) {
    const bundled = bundledCandidates.find((candidate) => existsSync(candidate));
    if (bundled) return bundled;
  }
  const local = path.join(projectRoot, 'backend', '.venv', process.platform === 'win32' ? 'Scripts' : 'bin', process.platform === 'win32' ? 'python.exe' : 'python');
  return existsSync(local) ? local : (process.platform === 'win32' ? 'python.exe' : 'python3');
}

async function startApi() {
  if (isDev && !apiPort) apiPort = 8000;
  if (isDev && await checkHealth()) return;
  if (!apiPort) apiPort = await availableLoopbackPort();
  const paths = ensureRuntimeDirectories();
  apiToken = apiToken || randomBytes(32).toString('hex');
  process.env.FORMA_API_TOKEN = apiToken;
  process.env.FORMA_API_PORT = String(apiPort);
  const executable = pythonExecutable();
  const providerEnvironment = {};
  for (const key of ['OPENROUTER_API_KEY', 'OPENAI_API_KEY']) {
    const value = readCredential(key);
    if (value) providerEnvironment[key] = value;
  }
  const preferredProvider = readPreferences().modelProvider;
  if (preferredProvider === 'openai' && providerEnvironment.OPENAI_API_KEY) providerEnvironment.AI_TUTOR_PROVIDER = 'openai';
  else if (preferredProvider === 'openrouter' && providerEnvironment.OPENROUTER_API_KEY) providerEnvironment.AI_TUTOR_PROVIDER = 'openrouter';
  else if (providerEnvironment.OPENAI_API_KEY) providerEnvironment.AI_TUTOR_PROVIDER = 'openai';
  else if (providerEnvironment.OPENROUTER_API_KEY) providerEnvironment.AI_TUTOR_PROVIDER = 'openrouter';
  const args = isDev || !executable.endsWith('forma-api.exe') && !executable.endsWith('forma-api')
    ? ['-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', String(apiPort)]
    : ['--host', '127.0.0.1', '--port', String(apiPort)];
  const child = spawn(executable, args, {
    cwd: projectRoot,
    env: { ...process.env, ...providerEnvironment, DATABASE_URL: '', AI_TUTOR_ENV: 'development', FORMA_DB_PATH: path.join(paths.data, 'forma.db'), AI_TUTOR_MATERIAL_DIR: paths.materials, FORMA_API_TOKEN: apiToken, FORMA_API_HOST: '127.0.0.1', FORMA_API_PORT: String(apiPort), FORMA_WEB_ORIGIN: `http://127.0.0.1:${webPort || 3000}` },
    stdio: isDev ? 'inherit' : 'ignore',
    windowsHide: true
  });
  apiProcess = child;
  child.on('error', error => console.error('Forma API failed to start', error));
  child.on('exit', (code, signal) => {
    if (apiProcess === child) apiProcess = undefined;
    if (!shuttingDown && !child.killed) {
      console.error(`Forma API stopped unexpectedly (code=${code ?? 'null'}, signal=${signal ?? 'none'})`);
      scheduleApiRestart();
    }
  });
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (await checkHealth()) { restartAttempts = 0; return; }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error(`The local tutor service did not start on port ${apiPort}.`);
}

function stopApi() {
  clearTimeout(restartTimer); restartTimer = undefined;
  if (!apiProcess || apiProcess.killed) return;
  apiProcess.kill();
  apiProcess = undefined;
}

async function createWindow() {
  if (!isDev) webPort = await availableLoopbackPort();
  await startApi();
  window = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 960,
    minHeight: 680,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, 'preload.cjs')
    }
  });
  window.once('ready-to-show', () => window.show());
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://') || url.startsWith('http://')) void shell.openExternal(url);
    return { action: 'deny' };
  });
  if (isDev) await window.loadURL(process.env.FORMA_WEB_URL || 'http://127.0.0.1:3000');
  else {
    webProcess = await startWebServer({ root: path.join(process.resourcesPath, 'web'), port: webPort });
    await window.loadURL(`http://127.0.0.1:${webPort}`);
  }
}

app.whenReady().then(() => {
  if (!hasSingleInstanceLock) return;
  configureCredentialBridge();
  configureUpdates();
  configureApplicationMenu();
  return createWindow().then(() => { startReviewNotifications(); if (canCheckForUpdates()) setTimeout(() => void checkForUpdates(), 8000); }).catch(error => {
    dialog.showErrorBox('Forma could not start', error.message);
    app.quit();
  });
});
app.on('window-all-closed', () => { shuttingDown = true; stopApi(); clearInterval(reviewTimer); webProcess?.close(); if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => { shuttingDown = true; stopApi(); clearInterval(reviewTimer); webProcess?.close(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) void createWindow(); });
