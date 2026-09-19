// No device is accessed on import/page load. start() is called only from Play.
export class PcmCapture {
  constructor({maxSeconds = 60, onFailure = () => {}} = {}) {
    this.maxSeconds = maxSeconds;
    this.onFailure = onFailure;
    this.frames = 0;
    this.chunks = [];
    this.pending = new Map();
    this.sequence = 0;
    this.closed = false;
    this.failure = null;
  }

  prime() {
    // Call synchronously inside the Play gesture, BEFORE awaiting a server
    // reservation/permission prompt. Otherwise autoplay policy can suspend
    // WebAudio indefinitely even after microphone permission was granted.
    if (this.context || this.closed) return;
    this.context = new AudioContext({latencyHint: 'interactive'});
    this.resumePromise = this.context.resume();
    this.resumePromise.catch(() => {}); // handled by start(); never an unhandled rejection
  }

  async start() {
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      throw new Error('Microphone capture needs a browser with AudioWorklet on localhost/HTTPS');
    }
    try {
      const permission = navigator.mediaDevices.getUserMedia({
        audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false},
        video: false,
      }).then(stream => {
        // getUserMedia itself cannot be cancelled. Dispose a late permission
        // result even after the UI has already timed out/stopped this attempt.
        if (this.closed) {
          stream.getTracks().forEach(track => track.stop());
          throw new Error('Recording cancelled while permission was pending');
        }
        return stream;
      });
      let permissionTimer, stream;
      try {
        stream = await Promise.race([permission, new Promise((_, reject) => {
          this.rejectPermission = reject;
          permissionTimer = setTimeout(() => reject(new Error('Microphone permission timed out; no motion started')), 30000);
        })]);
      } finally { clearTimeout(permissionTimer); this.rejectPermission = null; }
      if (this.closed) { stream.getTracks().forEach(track => track.stop()); throw new Error('Recording cancelled'); }
      this.stream = stream;
      this.prime();
      let resumeTimer;
      try {
        await Promise.race([this.resumePromise, new Promise((_, reject) => {
          resumeTimer = setTimeout(() => reject(new Error('Audio context did not start; click Play again after inspection')), 4000);
        })]);
      } finally { clearTimeout(resumeTimer); }
      await this.context.audioWorklet.addModule('/static/pcm-worklet.js');
      if (this.closed) throw new Error('Recording cancelled');
      this.sampleRate = this.context.sampleRate;
      this.node = new AudioWorkletNode(this.context, 'guitarra-pcm', {
        numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
      });
      this.node.onprocessorerror = () => this.fail('Audio processor failed');
      this.node.port.onmessage = ({data}) => {
        if (this.closed) return;
        if (data.type === 'chunk') {
          if (data.start_frame !== this.frames) return this.fail('Audio samples were lost or reordered');
          this.frames += data.samples.length;
          if (this.frames > this.maxSeconds * this.sampleRate) return this.fail('Recording limit reached');
          this.chunks.push(data.samples);
          this.firstChunk?.();
        } else if (data.type === 'error') {
          this.fail(data.message || 'Microphone frames were interrupted');
        } else if (data.type === 'mark') {
          const pending = this.pending.get(data.id);
          if (pending) {
            clearTimeout(pending.timer);
            this.pending.delete(data.id);
            pending.resolve(data.frames);
          }
        }
      };
      for (const track of stream.getAudioTracks()) {
        track.onended = () => this.fail('Microphone disconnected');
        track.onmute = () => this.fail('Microphone input was interrupted/muted');
      }
      this.context.onstatechange = () => {
        if (!this.closed && this.context.state !== 'running') this.fail('Audio context was interrupted');
      };
      this.source = this.context.createMediaStreamSource(stream);
      const ready = new Promise((resolve, reject) => {
        this.rejectReady = reject;
        this.readyTimer = setTimeout(() => reject(new Error('No microphone samples received')), 4000);
        this.firstChunk = () => {
          clearTimeout(this.readyTimer); this.firstChunk = null; this.rejectReady = null; resolve();
        };
      });
      this.startedAt = performance.now();
      this.source.connect(this.node);
      this.node.connect(this.context.destination); // worklet emits only zeros
      this.timer = setTimeout(() => this.fail('60-second recording limit reached; take incomplete'),
        (this.maxSeconds - 0.2) * 1000);
      await ready;
      if (this.failure || this.closed) throw new Error(this.failure || 'Recording cancelled');
      return this;
    } catch (error) {
      await this.abort();
      throw error;
    }
  }

  fail(message) {
    if (this.closed || this.failure) return;
    this.failure = message;
    // Stop tracks immediately, not after a slow network/Stop response.
    void this.release(); // retain received chunks for an explicitly incomplete LOCAL clip
    this.onFailure(message);
  }

  mark() {
    if (this.closed || this.failure || !this.node) {
      return Promise.reject(new Error(this.failure || 'Recorder is not running'));
    }
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error('Audio flush timed out; capture is incomplete'));
      }, 1500);
      this.pending.set(id, {resolve, reject, timer});
      this.node.port.postMessage({type: 'mark', id});
    });
  }

  async release() {
    this.closed = true;
    clearTimeout(this.timer);
    clearTimeout(this.readyTimer);
    this.rejectPermission?.(new Error(this.failure || 'Recording cancelled while permission was pending'));
    this.rejectPermission = null;
    this.rejectReady?.(new Error(this.failure || 'Recording cancelled before the first samples'));
    this.rejectReady = null;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(new Error('Recorder closed'));
    }
    this.pending.clear();
    this.stream?.getTracks().forEach(track => track.stop());
    this.source?.disconnect();
    this.node?.disconnect();
    this.node?.port.close();
    if (this.context && this.context.state !== 'closed') await this.context.close().catch(() => {});
  }

  async abort() {
    await this.release();
    this.chunks = [];
  }

  async partial() {
    // Close the mic immediately. Do not wait for a flush or claim this covers the
    // final motion; received chunks alone are retained for local operator review.
    await this.release();
    const frames = this.chunks.reduce((count, chunk) => count + chunk.length, 0);
    if (!frames || !this.sampleRate) return null;
    const blob = encodeWav(this.chunks, frames, this.sampleRate);
    this.chunks = [];
    return {blob, frames, sample_rate: this.sampleRate};
  }

  async finish() {
    await this.mark();
    const elapsed = (performance.now() - this.startedAt) / 1000;
    // Build only after disconnecting; no frames can leak into the next take.
    await this.release();
    if (this.failure || !this.frames) throw new Error(this.failure || 'Empty recording');
    const blob = encodeWav(this.chunks, this.frames, this.sampleRate);
    this.chunks = [];
    return {blob, frames: this.frames, sample_rate: this.sampleRate, elapsed_s: elapsed};
  }
}

export function encodeWav(chunks, frames, rate) {
  const buffer = new ArrayBuffer(44 + frames * 2);
  const view = new DataView(buffer);
  const text = (offset, value) => [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, 36 + frames * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, frames * 2, true);
  let offset = 44;
  for (const chunk of chunks) for (const sample of chunk) { view.setInt16(offset, sample, true); offset += 2; }
  if (offset !== buffer.byteLength) throw new Error('PCM frame count mismatch');
  return new Blob([buffer], {type: 'audio/wav'});
}
