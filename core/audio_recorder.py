"""System audio loopback recorder.

Uses WASAPI loopback via the ``soundcard`` library to capture whatever is
playing through the default speaker. Writes PCM s16le into a WAV file; the
final mp4 is produced by a post-mux step that combines this WAV with the
video output.
"""
from __future__ import annotations

import threading
import wave
from pathlib import Path

import numpy as np
import soundcard as sc


class AudioRecorder:
    def __init__(
        self,
        output_path: Path,
        samplerate: int = 48000,
        channels: int = 2,
        chunk_seconds: float = 0.1,
    ) -> None:
        self.output_path = Path(output_path)
        self.samplerate = int(samplerate)
        self.channels = int(channels)
        self.chunk_frames = max(1, int(self.samplerate * chunk_seconds))

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
            speaker = sc.default_speaker()
            loopback_mic = sc.get_microphone(speaker.name, include_loopback=True)
            self._device_name = speaker.name

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
