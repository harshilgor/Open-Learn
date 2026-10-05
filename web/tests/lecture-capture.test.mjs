import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';
import { randomUUID } from 'node:crypto';
import ts from 'typescript';

function captureHarness({ failPersist = false, denyResume = false } = {}) {
  const sessions = new Map();
  const events = [];
  const stoppedTracks = [];
  const syncCalls = [];
  let microphoneRequests = 0;
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
      if (name === './account-session') return { ACCOUNT_CHANGED: 'account-changed' };
      if (name === './live-lecture-transcription') return { LiveLectureTranscription: class {} };
      throw new Error(`Unexpected import: ${name}`);
    },
    navigator: { mediaDevices: { getUserMedia: async () => {
      microphoneRequests++;
      if (denyResume && microphoneRequests > 1) throw new Error('Microphone permission denied.');
      const track = {readyState: 'live', addEventListener() {}, stop() { if (this.readyState === 'live') stoppedTracks.push(true); this.readyState = 'ended'; }};
      return {getTracks: () => [track], getAudioTracks: () => [track]};
    } }, storage: { persist: async () => true } },
    MediaRecorder: FakeMediaRecorder,
    window: { dispatchEvent: event => events.push(event.detail), addEventListener() {} },
    CustomEvent: class { constructor(_name, options) { this.detail = options.detail; } },
    crypto: { randomUUID },
    performance,
    Date,
    Error,
    Blob,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
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

test('pause releases microphone and explicit resume reacquires it without replacing manifest', async () => {
  const {capture, sessions, stoppedTracks} = captureHarness();
  const id = await capture.start({title: 'Biology'});
  await capture.pause(); await settle();
  assert.equal(capture.phase, 'paused'); assert.equal(capture.mediaStream, null); assert.equal(stoppedTracks.length, 1);
  await capture.resume(); assert.equal(capture.phase, 'recording'); assert.equal(capture.recordingId, id);
  await capture.stop(); await settle();
  assert.equal(stoppedTracks.length, 2); assert.equal(sessions.get(id).nextSequenceNumber, 2);
});

test('denied resume stays paused with no live microphone and saved audio can still finish', async () => {
  const {capture, sessions, stoppedTracks} = captureHarness({denyResume: true});
  const id = await capture.start({title: 'Biology'});
  await capture.pause(); await settle(); await capture.resume();
  assert.equal(capture.phase, 'paused'); assert.equal(capture.mediaStream, null);
  assert.match(capture.error, /permission denied/); assert.equal(stoppedTracks.length, 1);
  await capture.stop(); await settle(); assert.equal(sessions.get(id).phase, 'stop_requested');
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
