import sys
import threading
import time
from collections import deque


class ActionPerMinuteTracker:
    """Calculate a short-term input APM from the latest action window."""

    def __init__(self, window_seconds=60):
        self.window_seconds = window_seconds
        self._actions = deque()
        self._lock = threading.Lock()

    def record(self, timestamp=None):
        with self._lock:
            self._actions.append(time.monotonic() if timestamp is None else timestamp)

    def reset(self):
        with self._lock:
            self._actions.clear()

    def actions_per_minute(self, timestamp=None, active=True):
        """Return the current action rate, normalized to one minute."""

        now = time.monotonic() if timestamp is None else timestamp
        cutoff = now - self.window_seconds
        with self._lock:
            if not active:
                self._actions.clear()
                return 0
            while self._actions and self._actions[0] < cutoff:
                self._actions.popleft()
            return round(len(self._actions) * 60 / self.window_seconds)


class WindowsActionListener:
    """Passively record global key-down and mouse-button events on Windows."""

    def __init__(self, tracker):
        self.tracker = tracker
        self._thread = None
        self._keyboard_proc = None
        self._mouse_proc = None

    def start(self):
        if sys.platform != "win32" or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="apm-listener")
        self._thread.start()

    def _run(self):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hook_proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            hook_proc_type,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        keyboard_down_actions = {0x0100, 0x0104}
        keyboard_up_actions = {0x0101, 0x0105}
        mouse_actions = {0x0201, 0x0204, 0x0207, 0x020B}
        pressed_keys = set()

        class KeyboardHookData(ctypes.Structure):
            _fields_ = [
                ("virtual_key", wintypes.DWORD),
                ("scan_code", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("extra", ctypes.c_void_p),
            ]

        @hook_proc_type
        def keyboard_proc(code, message, lparam):
            if code >= 0:
                key = ctypes.cast(
                    lparam, ctypes.POINTER(KeyboardHookData)
                ).contents.virtual_key
                if message in keyboard_down_actions and key not in pressed_keys:
                    pressed_keys.add(key)
                    self.tracker.record()
                elif message in keyboard_up_actions:
                    pressed_keys.discard(key)
            return user32.CallNextHookEx(None, code, message, lparam)

        @hook_proc_type
        def mouse_proc(code, message, lparam):
            if code >= 0 and message in mouse_actions:
                self.tracker.record()
            return user32.CallNextHookEx(None, code, message, lparam)

        self._keyboard_proc = keyboard_proc
        self._mouse_proc = mouse_proc
        module = kernel32.GetModuleHandleW(None)
        keyboard_hook = user32.SetWindowsHookExW(13, keyboard_proc, module, 0)
        mouse_hook = user32.SetWindowsHookExW(14, mouse_proc, module, 0)
        if not keyboard_hook or not mouse_hook:
            if keyboard_hook:
                user32.UnhookWindowsHookEx(keyboard_hook)
            if mouse_hook:
                user32.UnhookWindowsHookEx(mouse_hook)
            return

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
