"""默认静音的短猫叫通道；声音失败不影响视觉玩法。"""

from pathlib import Path


class WaveOutput:
    def play(self, path):
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    def stop(self):
        import winsound
        winsound.PlaySound(None, 0)


class PlayAudio:
    def __init__(self, root, output=None):
        self.path = Path(root) / 'audio/meow.wav'
        self.output = output if output is not None else WaveOutput()
        self.session_id = -1
        self.calls = 0
        self.last_call_ms = None
        self.playing = False

    def close(self):
        if self.playing:
            try:
                self.output.stop()
            except (OSError, RuntimeError, ImportError):
                pass
            self.playing = False

    def update(self, view, enabled=False, quiet=False, paused=False):
        if view.session_id < self.session_id:
            return
        if view.session_id != self.session_id:
            self.close()
            self.session_id = view.session_id
            self.calls = 0
            self.last_call_ms = None
        if not enabled or quiet or paused or view.mode != 'begging':
            self.close()
            return
        elapsed = view.session_elapsed_ms
        if self.calls >= 2 or (self.last_call_ms is not None and elapsed - self.last_call_ms < 60000):
            return
        # 即使设备失败也占用本次机会，避免每16毫秒反复尝试播放。
        self.calls += 1
        self.last_call_ms = elapsed
        if not self.path.is_file():
            return
        try:
            self.output.play(self.path)
            self.playing = True
        except (OSError, RuntimeError, ImportError):
            self.playing = False
