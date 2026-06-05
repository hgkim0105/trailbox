"""System audio loopback recorder.

Uses WASAPI loopback via the ``soundcard`` library to capture whatever is
playing through the default speaker. Writes PCM s16le into a WAV file; the
final mp4 is produced by a post-mux step that combines this WAV with the
video output.
"""
from __future__ import annotations

import threading
import time
import wave
from collections import deque
from pathlib import Path

# numpy + soundcard are imported lazily inside `_run` to keep app startup fast.
# soundcard pulls in its WASAPI COM bindings on import (~0.2s), and is only
# touched when the user actually starts a recording with audio enabled.


class AudioRecorder:
    def __init__(
        self,
        output_path: Path,
        samplerate: int = 48000,
        channels: int = 2,
        chunk_seconds: float = 0.1,
        *,
        lookback: bool = False,
        buffer_seconds: float = 30.0,
    ) -> None:
        self.output_path = Path(output_path)
        self.samplerate = int(samplerate)
        self.channels = int(channels)
        self.chunk_frames = max(1, int(self.samplerate * chunk_seconds))

        # Lookback mode: instead of streaming to a WAV, keep an age-bounded
        # ring of (chunk_start_perf, int16_pcm_bytes) chunks in memory and
        # let the controller slice the desired window out on capture.
        self.lookback = bool(lookback)
        self.buffer_seconds = float(buffer_seconds)
        self._ring: deque[tuple[float, bytes]] = deque()
        self._ring_lock = threading.Lock()

        self._stop = threading.Event()
        self._started = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._samples_written = 0
        self._device_name: str = ""

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("AudioRecorder already started")
        self._thread = threading.Thread(
            target=self._run, name="AudioRecorder", daemon=True
        )
        self._thread.start()
        self._started.wait(timeout=5.0)
        if self._error is not None:
            raise self._error

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._error is not None:
            raise self._error

    def samples_written(self) -> int:
        return self._samples_written

    def device_name(self) -> str:
        return self._device_name

    def duration_seconds(self) -> float:
        return self._samples_written / float(self.samplerate)

    def _run(self) -> None:
        try:
            import numpy as np
            import soundcard as sc

            speaker = sc.default_speaker()
            loopback_mic = sc.get_microphone(speaker.name, include_loopback=True)
            self._device_name = speaker.name

            if self.lookback:
                self._run_ring(np, loopback_mic)
                return

            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(self.output_path), "wb") as wav:
                wav.setnchannels(self.channels)
                wav.setsampwidth(2)  # s16le
                wav.setframerate(self.samplerate)

                with loopback_mic.recorder(
                    samplerate=self.samplerate, channels=self.channels
                ) as rec:
                    self._started.set()
                    while not self._stop.is_set():
                        # float32 in [-1, 1], shape (chunk_frames, channels)
                        data = rec.record(numframes=self.chunk_frames)
                        clipped = np.clip(data * 32767.0, -32768.0, 32767.0)
                        wav.writeframes(clipped.astype(np.int16).tobytes())
                        self._samples_written += data.shape[0]
        except BaseException as e:  # noqa: BLE001
            self._error = e
            self._started.set()

    def _run_ring(self, np, loopback_mic) -> None:
        """Lookback capture loop: buffer PCM chunks, prune by age."""
        with loopback_mic.recorder(
            samplerate=self.samplerate, channels=self.channels
        ) as rec:
            self._started.set()
            while not self._stop.is_set():
                t_start = time.perf_counter()
                data = rec.record(numframes=self.chunk_frames)
                clipped = np.clip(data * 32767.0, -32768.0, 32767.0)
                pcm = clipped.astype(np.int16).tobytes()
                self._samples_written += data.shape[0]
                cutoff = t_start - self.buffer_seconds
                with self._ring_lock:
                    self._ring.append((t_start, pcm))
                    while self._ring and self._ring[0][0] < cutoff:
                        self._ring.popleft()

    def flush_window(
        self, t0_new_perf: float, t_end_perf: float, out_path: Path
    ) -> float:
        """Write buffered PCM for ``[t0_new_perf, t_end_perf]`` to a WAV.

        Sample-accurately trims the first/last chunk so the audio starts at
        ``t0_new_perf`` (the same zero the video clip uses) and runs to
        ``t_end_perf``. Returns the written duration in seconds.
        """
        bytes_per_frame = self.channels * 2  # s16le
        with self._ring_lock:
            chunks = list(self._ring)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        frames_out = 0
        with wave.open(str(out_path), "wb") as wav:
            wav.setnchannels(self.channels)
            wav.setsampwidth(2)
            wav.setframerate(self.samplerate)
            for t_start, pcm in chunks:
                n_frames = len(pcm) // bytes_per_frame
                if n_frames <= 0:
                    continue
                t_chunk_end = t_start + n_frames / self.samplerate
                if t_chunk_end <= t0_new_perf or t_start >= t_end_perf:
                    continue
                lo = 0
                hi = n_frames
                if t_start < t0_new_perf:
                    lo = int((t0_new_perf - t_start) * self.samplerate)
                if t_chunk_end > t_end_perf:
                    hi = n_frames - int((t_chunk_end - t_end_perf) * self.samplerate)
                lo = max(0, min(lo, n_frames))
                hi = max(lo, min(hi, n_frames))
                if hi <= lo:
                    continue
                wav.writeframes(pcm[lo * bytes_per_frame : hi * bytes_per_frame])
                frames_out += hi - lo
        return frames_out / float(self.samplerate)
