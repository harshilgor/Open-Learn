// Capture never resumes automatically after an operating-system interruption.
function installClassLifecycle({ app, powerMonitor, Tray, Menu, nativeImage, getWindow, releasePower }) {
  let active = false;
  let quitting = false;
  let tray;
  let quitTimer;
  const show = () => { const win = getWindow(); if (win && !win.isDestroyed()) { win.show(); win.focus(); } };
  const send = reason => {
    releasePower();
    const win = getWindow();
    if (win && !win.isDestroyed() && !win.webContents.isDestroyed()) win.webContents.send('forma:class-lifecycle', { reason, action: 'stop', automaticResume: false });
  };
  const stop = reason => { if (active) send(reason); };
  const ensureTray = () => {
    if (tray) return;
    // Inline icon avoids a missing packaged asset and works with Windows tray scaling.
    const icon = nativeImage.createFromDataURL('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==');
    tray = new Tray(icon);
    tray.setToolTip('Open Learn · class recording');
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: 'Open class recording', click: show },
      { label: 'Stop and save recording', click: () => { show(); stop('tray-stop'); } },
    ]));
    tray.on('double-click', show);
  };
  powerMonitor.on('lock-screen', () => stop('screen-locked'));
  powerMonitor.on('suspend', () => stop('system-suspended'));
  powerMonitor.on('resume', () => { const win = getWindow(); if (win && !win.isDestroyed()) win.webContents.send('forma:class-lifecycle', { reason: 'system-resumed', action: 'status', automaticResume: false }); });
  const beforeQuit = event => {
    if (!active || quitting) return;
    event.preventDefault();
    quitting = true;
    send('app-quitting');
    // OS shutdown may not allow JS to settle. Renderer destruction releases media;
    // the persisted chunk manifest offers recovery on next launch.
    quitTimer = setTimeout(() => app.quit(), 3000);
  };
  return {
    beforeQuit,
    isActive: () => active,
    setActive(value) {
      active = value === true;
      if (active) { try { ensureTray(); } catch (error) { console.error('Class tray unavailable', error); } }
      else { tray?.destroy(); tray = undefined; if (quitting) { clearTimeout(quitTimer); app.quit(); } }
    },
    close(event) { if (active && !quitting && tray) { event.preventDefault(); getWindow()?.hide(); } },
    reset() { active = false; releasePower(); tray?.destroy(); tray = undefined; },
  };
}
module.exports = { installClassLifecycle };
