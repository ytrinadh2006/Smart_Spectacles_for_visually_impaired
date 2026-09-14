"""
Pre-generate speech clips with espeak-ng.

Output: raw headerless PCM, 16 kHz, mono, unsigned 8-bit — exactly what the
ESP32 streams into its sigma-delta player, no parsing needed on-device.

Idempotent: existing clips are kept. Called from server.py at startup so the
cache self-heals when labels.txt changes. Can also be run directly:

    python3 gen_audio.py [labels.txt] [output_dir]
"""

import os
import subprocess
import sys
import tempfile
import wave

import numpy as np

import phrases

TARGET_RATE = 16000
MAX_CLIP_SECONDS = 2.8

ESPEAK_ARGS = ['-v', 'en-us', '-s', '140', '-p', '45', '-a', '190', '-g', '6']


def synth_to_wav(sentence, wav_path):
    subprocess.run(
        ['espeak-ng', *ESPEAK_ARGS, '-w', wav_path, sentence],
        check=True, capture_output=True,
    )


def wav_to_u8_pcm(wav_path):
    """Read espeak's WAV (22050 Hz s16 mono), resample to 16 kHz, convert to u8."""
    with wave.open(wav_path, 'rb') as w:
        rate = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
        sampwidth = w.getsampwidth()
        channels = w.getnchannels()

    if sampwidth == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    elif sampwidth == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
    else:
        raise ValueError(f'unsupported sample width {sampwidth}')

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    # Linear-interp resample to 16 kHz
    if rate != TARGET_RATE:
        duration = len(samples) / rate
        out_n = int(duration * TARGET_RATE)
        src_idx = np.linspace(0, len(samples) - 1, out_n)
        samples = np.interp(src_idx, np.arange(len(samples)), samples)

    # Normalize to ~90% full scale so all clips are equally loud
    peak = np.abs(samples).max()
    if peak > 0:
        samples = samples * (0.9 * 32767.0 / peak)

    u8 = (samples / 256.0 + 128.0).clip(0, 255).astype(np.uint8)
    return u8.tobytes()


def ensure_cache(labels, audio_dir, verbose=True):
    """Generate any missing clips for these labels. Returns number generated."""
    os.makedirs(audio_dir, exist_ok=True)
    made = 0
    for name, sentence in phrases.all_clips(labels):
        out_path = os.path.join(audio_dir, name + '.pcm')
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            continue
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tf:
            tmp_wav = tf.name
        try:
            synth_to_wav(sentence, tmp_wav)
            pcm = wav_to_u8_pcm(tmp_wav)
        finally:
            os.unlink(tmp_wav)

        seconds = len(pcm) / TARGET_RATE
        if seconds > MAX_CLIP_SECONDS and verbose:
            print(f'  WARNING: {name} is {seconds:.1f}s (>{MAX_CLIP_SECONDS}s) — consider shorter phrasing')

        with open(out_path, 'wb') as f:
            f.write(pcm)
        made += 1
        if verbose:
            print(f'  [{made}] {name}.pcm  {seconds:.1f}s  "{sentence}"')
    return made


def load_labels(path):
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


if __name__ == '__main__':
    labels_path = sys.argv[1] if len(sys.argv) > 1 else 'labels.txt'
    audio_dir = sys.argv[2] if len(sys.argv) > 2 else 'audio_cache'
    labels = load_labels(labels_path)
    print(f'Generating clips for {len(labels)} classes into {audio_dir}/ ...')
    n = ensure_cache(labels, audio_dir)
    print(f'Done — {n} new clips generated.')
