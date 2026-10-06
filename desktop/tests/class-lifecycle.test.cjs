const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { installClassLifecycle } = require('../src/class-lifecycle.cjs');
function fixture() {
  const powerMonitor = new EventEmitter(); const events = []; let hidden = false; let released = 0; let quit = 0;
  const win = { isDestroyed: () => false, hide: () => { hidden = true; }, show() {}, focus() {}, webContents: { isDestroyed: () => false, send: (channel, data) => events.push({channel, data}) } };
  class Tray extends EventEmitter { setToolTip() {} setContextMenu() {} destroy() {} }
  const lifecycle = installClassLifecycle({ app: {quit: () => {quit++;}}, powerMonitor, Tray, Menu: {buildFromTemplate: value => value}, nativeImage: {createFromDataURL: () => ({})}, getWindow: () => win, releasePower: () => {released++;} });
  return {lifecycle, powerMonitor, events, hidden: () => hidden, released: () => released, quit: () => quit};
}
test('lock and sleep stop consented capture, wake never resumes', () => {
  const f = fixture(); f.powerMonitor.emit('lock-screen'); assert.equal(f.events.length, 0);
  f.lifecycle.setActive(true); f.powerMonitor.emit('lock-screen'); f.powerMonitor.emit('suspend'); f.powerMonitor.emit('resume');
  assert.deepEqual(f.events.map(e => e.data.action), ['stop','stop','status']);
  assert.ok(f.events.every(e => e.data.automaticResume === false)); assert.equal(f.released(), 2);
});
test('only active capture keeps close in tray, reset clears ownership', () => {
  const f = fixture(); let prevented = 0; const event = {preventDefault: () => {prevented++;}};
  f.lifecycle.close(event); assert.equal(prevented, 0);
  f.lifecycle.setActive(true); f.lifecycle.close(event); assert.equal(prevented, 1); assert.equal(f.hidden(), true);
  f.lifecycle.reset(); f.lifecycle.close(event); assert.equal(prevented, 1);
});
test('quit waits for saved manifest acknowledgement before shutting down', () => {
  const f = fixture(); let prevented = false; f.lifecycle.setActive(true);
  f.lifecycle.beforeQuit({preventDefault: () => {prevented = true;}});
  assert.equal(prevented, true); assert.equal(f.quit(), 0); assert.equal(f.events[0].data.reason, 'app-quitting');
  f.lifecycle.setActive(false); assert.equal(f.quit(), 1);
});
