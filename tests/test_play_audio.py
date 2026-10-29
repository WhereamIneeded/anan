"""验证默认静音、索食限频及中断时只停止本进程的声音。"""

import importlib
from types import SimpleNamespace


class Output:
    def __init__(self):
        self.played = []
        self.stopped = 0

    def play(self, path):
        self.played.append(path)

    def stop(self):
        self.stopped += 1


def player(tmp_path, output=None):
    try:
        module = importlib.import_module('anan_pet.audio')
    except ModuleNotFoundError:
        assert False, '尚未实现默认关闭的趣味声音通道'
    (tmp_path / 'audio').mkdir(exist_ok=True)
    (tmp_path / 'audio/meow.wav').write_bytes('测试不外放'.encode('utf-8'))
    output = output or Output()
    return module.PlayAudio(tmp_path, output), output


def view(elapsed=0, session=1, mode='begging'):
    return SimpleNamespace(session_id=session, mode=mode, session_elapsed_ms=elapsed)


def test_default_off_never_touches_audio_device(tmp_path):
    audio, out = player(tmp_path)
    for elapsed in (0, 60000, 120000):
        audio.update(view(elapsed))
    audio.close()
    assert not out.played and out.stopped == 0


def test_only_two_short_calls_per_session_with_sixty_second_gap(tmp_path):
    audio, out = player(tmp_path)
    for elapsed in (0, 1, 59999, 60000, 60001, 120000, 1200000):
        audio.update(view(elapsed), enabled=True)
    assert len(out.played) == 2
    audio.update(view(0, session=2), enabled=True)
    assert len(out.played) == 3


def test_pause_stops_and_does_not_replay_first_call(tmp_path):
    audio, out = player(tmp_path)
    audio.update(view(), enabled=True)
    audio.update(view(100), enabled=True, paused=True)
    audio.update(view(100), enabled=True)
    assert len(out.played) == 1 and out.stopped == 1
    audio.update(view(60000), enabled=True)
    assert len(out.played) == 2


def test_disable_quiet_and_cancel_stop_without_reviving_old_session(tmp_path):
    audio, out = player(tmp_path)
    audio.update(view(), enabled=True)
    audio.update(view(100), enabled=True, quiet=True)
    assert out.stopped == 1
    audio.update(view(100, session=2, mode='none'), enabled=True)
    audio.update(view(60000, session=1), enabled=True)
    assert len(out.played) == 1


def test_missing_file_or_playback_failure_preserves_visual_flow(tmp_path):
    class Broken(Output):
        def play(self, path):
            raise RuntimeError('设备不可用')
    audio, out = player(tmp_path, Broken())
    audio.update(view(), enabled=True)
    (tmp_path / 'audio/meow.wav').unlink()
    audio.update(view(60000), enabled=True)
    audio.close()
    assert out.stopped == 0
