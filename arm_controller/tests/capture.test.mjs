// Pure offline AudioWorklet/PCM fixtures. No browser, devices, or network.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {encodeWav} from '../static/capture.js';

function worklet() {
  const messages = [];
  let Processor;
  const context = vm.createContext({
    currentFrame: 0,
    AudioWorkletProcessor: class {
      constructor() { this.port = {postMessage: message => messages.push(message)}; }
    },
    registerProcessor: (_name, constructor) => { Processor = constructor; },
  });
  vm.runInContext(readFileSync(new URL('../static/pcm-worklet.js', import.meta.url), 'utf8'), context);
  const processor = new Processor();
  const render = (frame, present = true) => {
    context.currentFrame = frame;
    const output = new Float32Array(128).fill(1);
    processor.process(present ? [[new Float32Array(128).fill(0.5)]] : [[]], [[output]]);
    assert.ok(output.every(value => value === 0), 'microphone must never be monitored to speakers');
  };
  return {processor, messages, render};
}

test('startup gaps cannot mark capture ready until a contiguous full first buffer', () => {
  const {messages, render} = worklet();
  render(0);
  render(384); // graph-startup gap: restart pre-roll, before Play could be admitted
  for (let i = 1; i < 32; i++) render(384 + i * 128);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].type, 'chunk');
  assert.equal(messages[0].start_frame, 0);
  assert.equal(messages[0].samples.length, 4096);
});

test('post-readiness discontinuity or missing input makes the capture unusable', () => {
  for (const missing of [false, true]) {
    const {messages, render, processor} = worklet();
    for (let i = 0; i < 32; i++) render(i * 128);
    assert.equal(messages[0].type, 'chunk');
    render(missing ? 4096 : 4352, !missing);
    assert.equal(messages[1].type, 'error');
    assert.equal(processor.failed, true);
    render(4480);
    assert.equal(messages.length, 2, 'no further usable chunks after a gap');
  }
});

test('WAV encoding is mono PCM16 with exact sample count and little endian values', async () => {
  const blob = encodeWav([Int16Array.from([-32768, 0, 32767])], 3, 48000);
  const data = new DataView(await blob.arrayBuffer());
  assert.equal(blob.type, 'audio/wav');
  assert.equal(data.byteLength, 50);
  assert.equal(data.getUint16(20, true), 1); // PCM
  assert.equal(data.getUint16(22, true), 1); // mono
  assert.equal(data.getUint32(24, true), 48000);
  assert.equal(data.getUint32(40, true), 6);
  assert.equal(data.getInt16(44, true), -32768);
  assert.equal(data.getInt16(46, true), 0);
  assert.equal(data.getInt16(48, true), 32767);
  assert.throws(() => encodeWav([Int16Array.from([0])], 2, 16000), /frame count mismatch/);
});
