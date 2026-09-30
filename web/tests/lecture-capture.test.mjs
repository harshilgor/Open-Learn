import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';
import { randomUUID } from 'node:crypto';
import ts from 'typescript';

function captureHarness({ failPersist = false } = {}) {
  const sessions = new Map();
  const events = [];
  const stoppedTracks = [];
  const syncCalls = [];
  const localStore = {
    defaultLecturePreferences: { depth: 'standard', keepAudio: true },
    async createLocalLecture(input) {
      const session = { ...input, phase: 'recording', nextSequenceNumber: 0, expectedChunkCount: null };
      sessions.set(input.id, session);
      return session;
    },
    async getLocalLecture(id) { return sessions.get(id) ?? null; },
    async updateLocalLecture(id, patch) {
      const session = { ...sessions.get(id), ...patch };
      sessions.set(id, session);
      return session;
    },
    async persistAudioSlice(id) {
      if (failPersist) throw new Error('quota exceeded');
      const session = sessions.get(id);
      sessions.set(id, { ...session, nextSequenceNumber: session.nextSequenceNumber + 1 });
    },
  };
  class FakeMediaRecorder {
    static isTypeSupported(type) { return type === 'audio/webm'; }
    constructor() { this.mimeType = 'audio/webm'; this.state = 'inactive'; }
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      this.ondataavailable({ data: new Blob(['audio'], { type: this.mimeType }) });
      this.onstop();
    }
  }
  const filename = resolve('lib/lecture-capture.ts');
  const source = readFileSync(filename, 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {};
  const context = {
    exports,
    require(name) {
      if (name === '@/lib/lecture-local-store') return localStore;
      if (name === '@/lib/lecture-upload-queue') return { syncLecture: async id => { syncCalls.push(id); } };
      throw new Error(`Unexpected import: ${name}`);
    },
    navigator: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop: () => stoppedTracks.push(true) }] }) }, storage: { persist: async () => true } },
    MediaRecorder: FakeMediaRecorder,
    window: { dispatchEvent: event => events.push(event.detail) },
    CustomEvent: class { constructor(_name, options) { this.detail = options.detail; } },
    crypto: { randomUUID },
    performance,
    Date,
    Blob,
    setTimeout,
    clearTimeout,
  };
  runInNewContext(compiled, context, { filename });
  return { capture: exports.lectureCapture, sessions, events, stoppedTracks, syncCalls };
}

async function settle() {
  await new Promise(resolve => setTimeout(resolve, 20));
}

test('a stopped recording is saved after its final audio slice is persisted', async () => {
  const { capture, sessions, events, stoppedTracks, syncCalls } = captureHarness();
  const id = await capture.start({ title: 'Biology' });
  assert.equal(syncCalls.length, 0);
  await capture.stop();
  await settle();
  assert.equal(sessions.get(id).phase, 'stop_requested');
  assert.equal(sessions.get(id).nextSequenceNumber, 1);
  assert.equal(events.at(-1).phase, 'saved');
  assert.equal(stoppedTracks.length, 1);
});

test('a failed local slice save leaves an interrupted session for recovery', async () => {
  const { capture, sessions, events, stoppedTracks, syncCalls } = captureHarness({ failPersist: true });
  const id = await capture.start({ title: 'Biology' });
  assert.equal(syncCalls.length, 0);
  await capture.stop();
  await settle();
  assert.equal(sessions.get(id).phase, 'interrupted');
  assert.equal(sessions.get(id).captureInterrupted, true);
  assert.match(sessions.get(id).lastError, /Local audio storage failed/);
  assert.equal(events.at(-1).phase, 'error');
  assert.equal(stoppedTracks.length, 1);
  assert.equal(syncCalls.length, 0);
});
