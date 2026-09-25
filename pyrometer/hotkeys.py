import ctypes
import queue
import threading
from ctypes import wintypes

WM_HOTKEY, WM_QUIT, MOD_NOREPEAT = 0x0312, 0x0012, 0x4000
MODS = {"alt": 1, "ctrl": 2, "control": 2, "shift": 4, "win": 8}
VKS = {c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"}
VKS.update({f"f{n}": 0x6F + n for n in range(1, 13)})

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]


def parse(spec):
    mods, key = 0, None
    for part in spec.lower().replace(" ", "").split("+"):
        if part in MODS:
            mods |= MODS[part]
        else:
            key = VKS.get(part)
    return (mods, key) if mods and key else None


class HotkeyListener(threading.Thread):
    def __init__(self, bindings):
        super().__init__(daemon=True, name="PyrometerHotkeys")
        self.bindings = bindings
        self.events = queue.SimpleQueue()
        self.failed = []
        self.thread_id = 0
        self.ready = threading.Event()

    def run(self):
        registered = {}
        for ident, (action, spec) in enumerate(self.bindings.items(), 1):
            combo = parse(spec)
            if combo and user32.RegisterHotKey(None, ident, combo[0] | MOD_NOREPEAT, combo[1]):
                registered[ident] = action
            else:
                self.failed.append(spec)
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self.ready.set()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == WM_HOTKEY and message.wParam in registered:
                self.events.put(registered[message.wParam])
        for ident in registered:
            user32.UnregisterHotKey(None, ident)

    def pop(self):
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return None

    def close(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
