/* Backend relay format: mono PCM16 at 16 kHz, bounded 100 ms frames. */
class ClassAudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.phase = 0; this.sum = 0; this.count = 0;
    this.frame = new Int16Array(1600); this.position = 0;
  }
  process(inputs) {
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let value = 0;
      for (const channel of channels) value += channel[i] || 0;
      this.sum += value / channels.length; this.count++; this.phase += 16000;
      if (this.phase >= sampleRate) {
        this.phase -= sampleRate;
        const sample = Math.max(-1, Math.min(1, this.sum / this.count));
        this.frame[this.position++] = Math.round(sample * (sample < 0 ? 32768 : 32767));
        this.sum = 0; this.count = 0;
        if (this.position === this.frame.length) {
          this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
          this.frame = new Int16Array(1600); this.position = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('class-audio', ClassAudioProcessor);
