"""窗口外完整双击及原生监听生命周期的回归验证。"""

import ctypes
import importlib
import os
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


def _module():
    return importlib.import_module("anan_pet.global_mouse")


def _tracker():
    return _module().DoubleClickTracker(500, (8, 10), (4, 5))


def _click(tracker, time_ms=100, x=-300, y=-200, inside=False):
    assert not tracker.feed("down", time_ms, x, y, inside)
    return tracker.feed("up", time_ms + 30, x, y, inside)


def test_complete_outside_double_click_finishes_only_on_second_release():
    tracker = _tracker()
    assert not _click(tracker)
    assert not tracker.feed("down", 300, -298, -203)
    assert tracker.feed("up", 330, -298, -203)
    assert not _click(tracker, 400)


@pytest.mark.parametrize("time_ms,x,y", [(601, -300, -200), (300, -295, -200), (300, -300, -194)])
def test_distant_click_becomes_new_first_click(time_ms, x, y):
    tracker = _tracker()
    assert not _click(tracker)
    assert not _click(tracker, time_ms, x, y)
    assert _click(tracker, time_ms + 100, x, y)


def test_double_click_limits_use_down_time_and_half_rectangle():
    tracker = _tracker()
    assert not _click(tracker)
    assert _click(tracker, 600, -296, -195)


@pytest.mark.parametrize("second", [False, True])
def test_drag_away_and_back_invalidates_whole_sequence(second):
    tracker = _tracker()
    if second:
        assert not _click(tracker)
    start = 300 if second else 100
    assert not tracker.feed("down", start, -300, -200)
    assert not tracker.feed("move", start + 10, -290, -200)
    assert not tracker.feed("move", start + 20, -300, -200)
    assert not tracker.feed("up", start + 30, -300, -200)
    assert not _click(tracker, start + 100)


def test_release_displacement_is_also_a_drag():
    tracker = _tracker()
    assert not tracker.feed("down", 100, 0, 0)
    assert not tracker.feed("up", 120, 5, 0)
    assert not _click(tracker, 200, 5, 0)


@pytest.mark.parametrize("second", [False, True])
def test_long_hold_is_not_a_click(second):
    tracker = _tracker()
    if second:
        assert not _click(tracker)
    start = 300 if second else 100
    assert not tracker.feed("down", start, -300, -200)
    assert not tracker.feed("up", start + 501, -300, -200)
    assert not _click(tracker, start + 600)


@pytest.mark.parametrize("kind", ["right_down", "right_up", "other", "cancel"])
def test_other_button_and_cancellation_clear_history(kind):
    tracker = _tracker()
    assert not _click(tracker)
    assert not tracker.feed(kind, 200, -300, -200)
    assert not _click(tracker, 300)


@pytest.mark.parametrize("inside_at", ["down", "up", "move"])
def test_any_inside_event_prevents_cross_window_double_click(inside_at):
    tracker = _tracker()
    assert not _click(tracker)
    assert not tracker.feed("down", 300, -300, -200, inside_at == "down")
    assert not tracker.feed("move", 310, -300, -200, inside_at == "move")
    assert not tracker.feed("up", 330, -300, -200, inside_at == "up")
    assert not _click(tracker, 400)


@pytest.mark.parametrize("time_ms", [129, 1])
def test_backwards_time_cannot_join_old_click(time_ms):
    tracker = _tracker()
    assert not _click(tracker)
    assert not tracker.feed("move", time_ms, -300, -200)
    assert not _click(tracker, 300)


@pytest.mark.parametrize("second_time", [100, 200])
def test_millisecond_precision_allows_equal_timestamps(second_time):
    tracker = _tracker()
    assert not tracker.feed("down", 100, -300, -200)
    assert not tracker.feed("move", 100, -300, -200)
    assert not tracker.feed("up", 100, -300, -200)
    assert not tracker.feed("down", second_time, -300, -200)
    assert tracker.feed("up", second_time, -300, -200)


def test_reset_and_unmatched_release_cannot_reuse_history():
    tracker = _tracker()
    assert not _click(tracker)
    tracker.reset()
    assert not _click(tracker, 300)
    assert not tracker.feed("up", 350, -300, -200)
    assert not _click(tracker, 400)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_offscreen_requests_are_idempotent_and_queued_events_have_generation(app, monkeypatch):
    module = _module()
    factory = Mock(side_effect=AssertionError("离屏测试不得安装桌面监听"))
    monkeypatch.setattr(module, "_MouseHook", factory)
    monitor = module.TeaserExitMonitor(123, native=False)
    received = []
    monitor.double_clicked.connect(received.append)
    assert not monitor.enabled
    monitor.set_enabled(True)
    generation = monitor.generation
    monitor.set_enabled(True)
    assert monitor.generation == generation
    monitor._detected.emit(generation)
    assert not received
    app.processEvents()
    assert received == [generation]
    monitor._detected.emit(generation)
    monitor.set_enabled(False)
    monitor.set_enabled(True)
    app.processEvents()
    assert received == [generation]
    monitor.close()
    closed_generation = monitor.generation
    monitor.close()
    monitor.set_enabled(True)
    assert monitor.generation == closed_generation
    assert not monitor.enabled
    factory.assert_not_called()


def test_install_failure_is_reported_without_repeated_attempts(app, monkeypatch):
    module = _module()
    hook = Mock(error="安装失败")
    factory = Mock(return_value=hook)
    monkeypatch.setattr(module, "_MouseHook", factory)
    monitor = module.TeaserExitMonitor(123)
    monitor.set_enabled(True)
    monitor.set_enabled(True)
    assert monitor.enabled
    assert monitor.error == "安装失败"
    assert factory.call_count == 1
    monitor.close()
    hook.close.assert_called_once()


def test_native_signal_is_delivered_on_qt_thread(app):
    module = _module()
    monitor = module.TeaserExitMonitor(123, native=False)
    monitor.set_enabled(True)
    receiver_threads = []
    monitor.double_clicked.connect(lambda generation: receiver_threads.append(threading.get_ident()))
    worker = threading.Thread(target=monitor._detected.emit, args=(monitor.generation,))
    worker.start()
    worker.join()
    assert not receiver_threads
    app.processEvents()
    assert receiver_threads == [threading.get_ident()]
    monitor.close()


class _FakeApi:
    """只替代操作系统边界，实际运行线程、回调及纯判定。"""

    def __init__(self, install=True, uninstall=True):
        self.quit = threading.Event()
        self.message_ready = threading.Event()
        self.loop_entered = threading.Event()
        self.callback = None
        self.user32 = SimpleNamespace(
            SetThreadDpiAwarenessContext=Mock(return_value=1),
            PeekMessageW=Mock(side_effect=self._peek),
            MsgWaitForMultipleObjects=Mock(side_effect=self._wait),
            GetDoubleClickTime=Mock(return_value=500),
            GetSystemMetrics=Mock(side_effect=lambda index: {36: 8, 37: 10, 68: 4, 69: 5}[index]),
            SetWindowsHookExW=Mock(side_effect=self._install if install else lambda *args: 0),
            CallNextHookEx=Mock(return_value=87),
            GetWindowRect=Mock(side_effect=self._rect),
            GetMessageW=Mock(side_effect=self._message),
            PostThreadMessageW=Mock(side_effect=self._post),
            UnhookWindowsHookEx=Mock(return_value=int(uninstall)),
        )
        self.kernel32 = SimpleNamespace(
            GetCurrentThreadId=Mock(return_value=12345),
            GetModuleHandleW=Mock(return_value=0x123456789),
        )

    def _install(self, kind, callback, module, thread_id):
        self.callback = callback
        return 0x234567891

    def _rect(self, handle, pointer):
        rect = pointer._obj
        rect.left, rect.top, rect.right, rect.bottom = -100, -100, 100, 100
        return 1

    def _message(self, *args):
        self.loop_entered.set()
        self.quit.wait(2)
        return 0

    def _peek(self, *args):
        return int(self.message_ready.is_set())

    def _wait(self, count, handles, wait_all, timeout_ms, wake_mask):
        self.loop_entered.set()
        return 0 if self.message_ready.wait(timeout_ms / 1000) else 258

    def _post(self, *args):
        self.quit.set()
        self.message_ready.set()
        return 1


def _native_hook(api, received):
    return _module()._MouseHook(123, 42, received.append, api=api)


def _native_event(api, kind, time_ms, x=-300, y=-200, code=0):
    module = _module()
    event = module._MouseData()
    event.pt.x, event.pt.y, event.time = x, y, time_ms
    return api.callback(code, kind, ctypes.addressof(event))


def test_native_hook_passes_all_messages_and_uses_physical_bounds():
    api, received = _FakeApi(), []
    hook = _native_hook(api, received)
    hook.start()
    try:
        for kind, time_ms in [(0x201, 100), (0x202, 130), (0x201, 300), (0x202, 330)]:
            assert _native_event(api, kind, time_ms) == 87
        assert received == [42]
        for kind, time_ms in [(0x201, 400), (0x202, 430), (0x201, 500), (0x202, 530)]:
            assert _native_event(api, kind, time_ms, 0, 0) == 87
        assert received == [42]
        assert api.callback(-1, 0x201, 0) == 87
        assert api.user32.CallNextHookEx.call_count == 9
        api.user32.SetThreadDpiAwarenessContext.assert_called_once_with(-4)
        assert api.user32.GetWindowRect.call_args.args[0] == 123
    finally:
        hook.close()
    assert not hook.thread.is_alive()
    api.user32.UnhookWindowsHookEx.assert_called_once_with(0x234567891)
    hook.close()
    assert api.user32.UnhookWindowsHookEx.call_count == 1
    assert hook.error is None


def test_native_callback_failure_still_passes_click_and_clears_history():
    api, received = _FakeApi(), []
    hook = _native_hook(api, received)
    hook.start()
    try:
        assert _native_event(api, 0x201, 100) == 87
        assert _native_event(api, 0x202, 130) == 87
        api.user32.GetWindowRect.side_effect = OSError("窗口已经关闭")
        assert _native_event(api, 0x201, 200) == 87
        api.user32.GetWindowRect.side_effect = api._rect
        assert _native_event(api, 0x202, 230) == 87
        assert not received
    finally:
        hook.close()


@pytest.mark.parametrize("install,uninstall", [(False, True), (True, False)])
def test_native_install_or_release_failure_has_error_and_no_live_thread(install, uninstall):
    api = _FakeApi(install=install, uninstall=uninstall)
    hook = _native_hook(api, [])
    hook.start()
    hook.close()
    assert hook.error
    assert not hook.thread.is_alive()
    assert api.user32.UnhookWindowsHookEx.call_count == int(install)


def test_native_missing_window_never_counts_as_outside():
    api, received = _FakeApi(), []
    api.user32.GetWindowRect.side_effect = None
    api.user32.GetWindowRect.return_value = 0
    hook = _native_hook(api, received)
    hook.start()
    try:
        for kind, time_ms in [(0x201, 100), (0x202, 130), (0x201, 300), (0x202, 330)]:
            assert _native_event(api, kind, time_ms) == 87
        assert not received
    finally:
        hook.close()


def test_dpi_failure_does_not_install_a_hook_with_mixed_coordinates():
    api = _FakeApi()
    api.user32.SetThreadDpiAwarenessContext.return_value = 0
    hook = _native_hook(api, [])
    hook.start()
    hook.close()
    assert hook.error
    assert not hook.thread.is_alive()
    assert api.user32.SetThreadDpiAwarenessContext.call_count == 2
    api.user32.SetWindowsHookExW.assert_not_called()


def test_message_loop_failure_unhooks_and_stops():
    api = _FakeApi()
    api.user32.GetMessageW.side_effect = None
    api.user32.GetMessageW.return_value = -1
    api.message_ready.set()
    hook = _native_hook(api, [])
    hook.start()
    hook.thread.join(1)
    hook.close()
    assert hook.error
    assert not hook.thread.is_alive()
    api.user32.UnhookWindowsHookEx.assert_called_once()


def test_failed_quit_post_cannot_leave_blocked_hooks_between_sessions():
    for _ in range(3):
        api = _FakeApi()
        release_blocked_message = threading.Event()

        def blocked_message(*args):
            api.loop_entered.set()
            release_blocked_message.wait()
            return 0

        api.user32.GetMessageW.side_effect = blocked_message
        api.user32.PostThreadMessageW.side_effect = None
        api.user32.PostThreadMessageW.return_value = 0
        hook = _native_hook(api, [])
        hook.start()
        try:
            assert api.loop_entered.wait(1)
            started = time.monotonic()
            hook.close()
            assert not hook.thread.is_alive(), "退出消息投递失败后不能遗留阻塞线程"
            assert time.monotonic() - started < 0.75
            api.user32.UnhookWindowsHookEx.assert_called_once()
            assert hook.error and "投递" in hook.error
            api.user32.GetMessageW.assert_not_called()
        finally:
            release_blocked_message.set()
            api.quit.set()
            hook.thread.join(2)


def test_native_wait_failure_unhooks_and_reports_error():
    api = _FakeApi()
    api.user32.MsgWaitForMultipleObjects.side_effect = None
    api.user32.MsgWaitForMultipleObjects.return_value = 0xFFFFFFFF
    hook = _native_hook(api, [])
    hook.start()
    hook.thread.join(1)
    hook.close()
    assert hook.error and "等待" in hook.error
    assert not hook.thread.is_alive()
    api.user32.UnhookWindowsHookEx.assert_called_once()


@pytest.mark.skipif(sys.platform != "win32", reason="真实 Windows ABI 签名验证")
def test_windows_pointer_signatures_preserve_64_bit_handles():
    module = _module()
    api = module._WinApi()
    assert ctypes.sizeof(module._Point) == 8
    assert ctypes.sizeof(module._Rect) == 16
    assert ctypes.sizeof(module._MouseData) == (32 if ctypes.sizeof(ctypes.c_void_p) == 8 else 24)
    assert api.user32.SetWindowsHookExW.restype is ctypes.c_void_p
    assert api.kernel32.GetModuleHandleW.restype is ctypes.c_void_p
    assert api.user32.CallNextHookEx.restype is ctypes.c_ssize_t
    assert api.user32.CallNextHookEx.argtypes[2:] == [ctypes.c_size_t, ctypes.c_ssize_t]
    assert api.user32.MsgWaitForMultipleObjects.restype is ctypes.c_uint32
    assert api.user32.MsgWaitForMultipleObjects.argtypes[1] == ctypes.POINTER(ctypes.c_void_p)
