"""仅在逗猫会话中观察窗口外双击，始终放行原软件的鼠标事件。"""

import ctypes
from ctypes import wintypes
import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal, Slot


class DoubleClickTracker:
    """两次完整点击才成立；拖动、长按及其他按钮会清除历史。"""

    def __init__(self, double_click_ms, double_click_size, drag_size):
        self.double_click_ms = double_click_ms
        self.double_click_size = double_click_size
        self.drag_size = drag_size
        self.reset()

    def reset(self):
        self._last_time = None
        self._down = None
        self._first = None
        self._second = False

    def _clear_clicks(self):
        self._down = self._first = None
        self._second = False

    def _dragged(self, x, y):
        return (abs(x - self._down[1]) > self.drag_size[0]
                or abs(y - self._down[2]) > self.drag_size[1])

    def feed(self, kind, time_ms, x, y, inside=False):
        # Win32 时间戳精度为毫秒，同一毫秒的有序事件仍然有效。
        if self._last_time is not None and time_ms < self._last_time:
            self.reset()
            return False
        self._last_time = time_ms
        if inside or kind not in {"down", "up", "move"}:
            self._clear_clicks()
            return False
        if kind == "move":
            if self._down is not None and self._dragged(x, y):
                self._clear_clicks()
            return False
        if kind == "down":
            if self._down is not None:
                self._clear_clicks()
            first = self._first
            self._second = bool(
                first is not None and 0 <= time_ms - first[0] <= self.double_click_ms
                and abs(x - first[1]) * 2 <= self.double_click_size[0]
                and abs(y - first[2]) * 2 <= self.double_click_size[1]
            )
            if not self._second:
                self._first = None
            self._down = (time_ms, x, y)
            return False
        if (self._down is None or self._dragged(x, y)
                or time_ms - self._down[0] > self.double_click_ms):
            self._clear_clicks()
            return False
        if self._second:
            self.reset()
            return True
        self._first, self._down = self._down, None
        return False


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class _Rect(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int32) for name in ("left", "top", "right", "bottom")]


class _MouseData(ctypes.Structure):
    _fields_ = [("pt", _Point), ("mouseData", ctypes.c_uint32),
                ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32),
                ("dwExtraInfo", ctypes.c_size_t)]


_HookProc = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
)


class _WinApi:
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("全局鼠标监听仅支持 Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer, integer = ctypes.c_void_p, ctypes.c_int
        unsigned, word, long = ctypes.c_uint32, ctypes.c_size_t, ctypes.c_ssize_t
        for library, name, arguments, result in [
            (self.user32, "SetThreadDpiAwarenessContext", [pointer], pointer),
            (self.user32, "SetWindowsHookExW", [integer, _HookProc, pointer, unsigned], pointer),
            (self.user32, "CallNextHookEx", [pointer, integer, word, long], long),
            (self.user32, "UnhookWindowsHookEx", [pointer], integer),
            (self.user32, "GetWindowRect", [pointer, ctypes.POINTER(_Rect)], integer),
            (self.user32, "GetDoubleClickTime", [], unsigned),
            (self.user32, "GetSystemMetrics", [integer], integer),
            (self.user32, "PeekMessageW", [ctypes.POINTER(wintypes.MSG), pointer, unsigned, unsigned, unsigned], integer),
            (self.user32, "GetMessageW", [ctypes.POINTER(wintypes.MSG), pointer, unsigned, unsigned], integer),
            (self.user32, "MsgWaitForMultipleObjects", [unsigned, ctypes.POINTER(pointer), integer, unsigned, unsigned], unsigned),
            (self.user32, "PostThreadMessageW", [unsigned, unsigned, word, long], integer),
            (self.kernel32, "GetCurrentThreadId", [], unsigned),
            (self.kernel32, "GetModuleHandleW", [ctypes.c_wchar_p], pointer),
        ]:
            function = getattr(library, name)
            function.argtypes, function.restype = arguments, result


def _windows_error(message):
    return f"{message}（Windows 错误 {ctypes.get_last_error()}）"


class _MouseHook:
    """专用线程维护低级钩子；回调只判断手势并排队通知 Qt。"""

    def __init__(self, window_handle, generation, on_double_click, api=None):
        self.window_handle = window_handle
        self.generation = generation
        self.on_double_click = on_double_click
        self.error = None
        self._api = api
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread_id = 0
        self._handle = None
        self._callback_ref = None
        self.thread = threading.Thread(target=self._run, name="安安逗猫双击监听", daemon=True)

    def start(self):
        self.thread.start()
        if not self._ready.wait(2):
            self.error = "鼠标监听线程启动超时"
            self.close()

    def close(self):
        self._stop.set()
        if self.thread.is_alive() and self._thread_id:
            if not self._api.user32.PostThreadMessageW(self._thread_id, 0x12, 0, 0):
                self.error = _windows_error("鼠标监听退出消息投递失败")
        if self.thread.ident is not None:
            self.thread.join(2)
            if self.thread.is_alive():
                self.error = "鼠标监听线程未及时结束"

    def _run(self):
        try:
            self._api = self._api or _WinApi()
            user32, kernel32 = self._api.user32, self._api.kernel32
            # 低级钩子与窗口矩形都使用物理屏幕坐标，不混用 Qt 逻辑坐标。
            if not user32.SetThreadDpiAwarenessContext(-4):
                if not user32.SetThreadDpiAwarenessContext(-3):
                    raise OSError(_windows_error("无法启用物理屏幕坐标"))
            message = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(message), None, 0x400, 0x400, 0)
            self._thread_id = kernel32.GetCurrentThreadId()
            self._tracker = DoubleClickTracker(
                user32.GetDoubleClickTime(),
                (user32.GetSystemMetrics(36), user32.GetSystemMetrics(37)),
                (abs(user32.GetSystemMetrics(68)), abs(user32.GetSystemMetrics(69))),
            )
            self._callback_ref = _HookProc(self._callback)
            if self._stop.is_set():
                return
            self._handle = user32.SetWindowsHookExW(
                14, self._callback_ref, kernel32.GetModuleHandleW(None), 0
            )
            if not self._handle:
                raise OSError(_windows_error("无法安装全局鼠标监听"))
            self._ready.set()
            while not self._stop.is_set():
                # 输入立即唤醒；有界等待确保退出消息投递失败也能检查停止标记。
                if user32.MsgWaitForMultipleObjects(0, None, False, 100, 0x4FF) == 0xFFFFFFFF:
                    raise OSError(_windows_error("鼠标监听输入等待失败"))
                # 系统事件也能唤醒等待，空队列不能直接进入阻塞的 GetMessage。
                while not self._stop.is_set() and user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0):
                    status = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                    if status <= 0:
                        if status < 0:
                            self.error = _windows_error("鼠标监听消息循环失败")
                        return
        except Exception as error:
            self.error = str(error)
        finally:
            if self._handle:
                if not self._api.user32.UnhookWindowsHookEx(self._handle):
                    self.error = _windows_error("无法卸载鼠标监听")
                self._handle = None
            self._ready.set()

    def _callback(self, code, message, parameter):
        if code >= 0 and not self._stop.is_set():
            try:
                event = ctypes.cast(parameter, ctypes.POINTER(_MouseData)).contents
                rect = _Rect()
                if self._api.user32.GetWindowRect(self.window_handle, ctypes.byref(rect)):
                    inside = rect.left <= event.pt.x < rect.right and rect.top <= event.pt.y < rect.bottom
                    kind = {0x201: "down", 0x202: "up", 0x200: "move"}.get(message, "other")
                    if self._tracker.feed(kind, event.time, event.pt.x, event.pt.y, inside):
                        self.on_double_click(self.generation)
                else:
                    self._tracker.reset()
            except Exception:
                self._tracker.reset()
        # 包括忽略、失败及负 nCode，始终把原事件交还系统及其他钩子。
        return self._api.user32.CallNextHookEx(None, code, message, parameter)


class TeaserExitMonitor(QObject):
    double_clicked = Signal(int)
    _detected = Signal(int)

    def __init__(self, window_handle: int, parent=None, native=True):
        super().__init__(parent)
        self.generation = 0
        self.enabled = False
        self.error = None
        self._window_handle = window_handle
        self._native = native
        self._closed = False
        self._hook = None
        self._detected.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if self._closed or enabled == self.enabled:
            return
        self.generation += 1
        self.enabled = enabled
        self.error = None
        if self._hook is not None:
            self._hook.close()
            self.error = self._hook.error
            self._hook = None
        if enabled and self._native:
            self._hook = _MouseHook(self._window_handle, self.generation, self._detected.emit)
            self._hook.start()
            self.error = self._hook.error

    @Slot(int)
    def _deliver(self, generation):
        if self.enabled and generation == self.generation and not self._closed:
            self.double_clicked.emit(generation)

    def close(self):
        if not self._closed:
            self.set_enabled(False)
            self._closed = True
