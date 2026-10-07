class DictationCapture extends AudioWorkletProcessor {
  constructor() {
    super(); this.buffer = new Int16Array(4096); this.length = 0; this.finished = false;
    this.port.onmessage = event => {
      if (event.data === 'finish') {
        this.flush(); this.finished = true; this.port.postMessage({ type: 'flushed' });
      }
    };
  }
  flush() {
    if (this.length) {
      const pcm = this.buffer.slice(0, this.length);
      this.port.postMessage(pcm.buffer, [pcm.buffer]); this.length = 0;
    }
  }
  process(inputs) {
    if (this.finished) return false;
    const channels = inputs[0];
    if (channels?.length && channels[0]?.length) {
      for (let i = 0; i < channels[0].length; i++) {
        let sample = 0;
        for (const channel of channels) sample += channel[i] || 0;
        sample = Math.max(-1, Math.min(1, sample / channels.length));
        this.buffer[this.length++] = sample < 0 ? sample * 32768 : sample * 32767;
        if (this.length === this.buffer.length) this.flush();
      }
    }
    return true;
  }
}
registerProcessor('dictation-capture', DictationCapture);
