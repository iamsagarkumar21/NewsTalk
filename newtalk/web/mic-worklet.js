// Captures the microphone, downsamples to 16 kHz mono PCM16 and posts ~100 ms frames.
class MicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;
    this.acc = 0;
    this.accN = 0;
    this.out = new Int16Array(1600);
    this.n = 0;
    this.muted = false;
    this.port.onmessage = (e) => {
      if (e.data && e.data.muted !== undefined) this.muted = !!e.data.muted;
    };
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i];
      this.accN += 1;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        let v = this.accN ? this.acc / this.accN : 0;
        this.acc = 0;
        this.accN = 0;
        if (this.muted) v = 0; // keep streaming silence so the STT connection stays alive
        v = Math.max(-1, Math.min(1, v));
        this.out[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
        if (this.n === this.out.length) {
          this.port.postMessage(this.out.buffer.slice(0));
          this.n = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("mic-processor", MicProcessor);
