"""Decode durable audio files into bounded, timeline-aligned verification WAVs."""
import hashlib
import io
import os
import shutil
import subprocess
import wave

from .lecture_provider import TranscriptionFailure

RATE = 16000


def decode_pcm(content, duration_ms):
    executable = os.getenv('OPENLEARN_FFMPEG_PATH') or shutil.which('ffmpeg')
    if not executable:
        raise TranscriptionFailure('Install FFmpeg on the backend to verify class audio.', code='audio_decoder_unavailable', status_code=503)
    try:
        result = subprocess.run([executable, '-nostdin', '-v', 'error', '-i', 'pipe:0',
                                 '-t', str(duration_ms / 1000 + 1), '-f', 's16le', '-ac', '1', '-ar', str(RATE), 'pipe:1'],
                                input=content, capture_output=True, timeout=20, check=True)
    except (subprocess.SubprocessError, OSError):
        raise TranscriptionFailure('This audio slice could not be decoded; saved audio remains available.', code='audio_decode_failed') from None
    expected = duration_ms * RATE * 2 // 1000
    if len(result.stdout) % 2 or abs(len(result.stdout) - expected) > max(RATE * 2, expected // 10):
        raise TranscriptionFailure('Decoded audio does not match its recording timeline.', code='audio_timing_mismatch')
    return result.stdout[:expected].ljust(expected, b'\0')


def assemble_window(chunks, read, decoder=decode_pcm):
    if not chunks or len(chunks) > 30:
        raise TranscriptionFailure('Invalid verification window.', code='invalid_audio_window')
    start, end = chunks[0]['start_ms'], chunks[-1]['end_ms']
    if not 0 < end - start <= 120000:
        raise TranscriptionFailure('Verification windows must be at most two minutes.', code='invalid_audio_window')
    audio = bytearray((end - start) * RATE * 2 // 1000)
    previous_end = start
    for chunk in chunks:
        if chunk['start_ms'] < previous_end or chunk['end_ms'] <= chunk['start_ms']:
            raise TranscriptionFailure('Overlapping source audio needs reconciliation.', code='audio_overlap')
        content = read(chunk)
        if hashlib.sha256(content).hexdigest() != chunk['sha256']:
            raise TranscriptionFailure('Saved audio failed its integrity check.', code='audio_checksum_mismatch')
        pcm = decoder(content, chunk['end_ms'] - chunk['start_ms'])
        begin = (chunk['start_ms'] - start) * RATE * 2 // 1000
        expected = (chunk['end_ms'] - chunk['start_ms']) * RATE * 2 // 1000
        if len(pcm) != expected:
            raise TranscriptionFailure('Invalid decoded sample count.', code='audio_timing_mismatch')
        audio[begin:begin + expected] = pcm
        previous_end = chunk['end_ms']
    target = io.BytesIO()
    with wave.open(target, 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(RATE); output.writeframes(audio)
    return target.getvalue()
