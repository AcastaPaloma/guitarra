// Browser microphone -> mono PCM16. No playback, no camera, no network here.
class PcmRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Int16Array(4096);
    this.used = 0;
    this.frames = 0;
    this.nextRenderFrame = null;
    this.failed = false;
    this.port.onmessage = ({data}) => {
      if (data.type === 'mark') {
        this.flush();
        this.port.postMessage({type: 'mark', id: data.id, frames: this.frames});
      }
    };
  }
  flush() {
    if (!this.used) return;
    const samples = this.buffer.slice(0, this.used);
    this.port.postMessage({type: 'chunk', start_frame: this.frames, samples}, [samples.buffer]);
    this.frames += this.used;
    this.used = 0;
  }
  process(inputs, outputs) {
    // Explicit silence on the output; microphone is never monitored through speakers.
    for (const output of outputs) for (const channel of output) channel.fill(0);
    const channels = inputs[0];
    const missing = !channels || !channels.length || !channels[0].length;
    if (this.failed) return true;
    if (this.nextRenderFrame !== null && (missing || currentFrame !== this.nextRenderFrame)) {
      if (this.frames === 0) {
        // Graph startup can skip quanta. Require a full contiguous FIRST buffer
        // before announcing capture readiness; no Play can have started yet.
        this.used = 0;
        this.nextRenderFrame = null;
      } else {
        this.failed = true;
        this.port.postMessage({type: 'error', message: 'Microphone render frames were interrupted'});
        return true;
      }
    }
    if (missing) return true; // no initial samples yet: Play remains blocked
    this.nextRenderFrame = currentFrame + channels[0].length;
    for (let i = 0; i < channels[0].length; i++) {
      let sample = 0;
      for (const channel of channels) sample += channel[i] / channels.length;
      sample = Math.max(-1, Math.min(1, sample));
      this.buffer[this.used++] = Math.round(sample * (sample < 0 ? 32768 : 32767));
      if (this.used === this.buffer.length) this.flush();
    }
    return true;
  }
}
registerProcessor('guitarra-pcm', PcmRecorder);
