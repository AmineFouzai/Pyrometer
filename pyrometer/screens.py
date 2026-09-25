import ctypes
from ctypes import wintypes

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
MONITOR_DEFAULTTONEAREST = 2

user32 = ctypes.windll.user32


class MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def virtual_bounds():
    """Bounding box of all monitors; origin can be negative."""
    metric = user32.GetSystemMetrics
    return (metric(SM_XVIRTUALSCREEN), metric(SM_YVIRTUALSCREEN),
            metric(SM_CXVIRTUALSCREEN), metric(SM_CYVIRTUALSCREEN))


def work_area_at(x, y):
    """Usable area (excludes taskbar) of the monitor holding this point."""
    point = wintypes.POINT(int(x), int(y))
    handle = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(MonitorInfo)
    if not handle or not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        left, top, width, height = virtual_bounds()
        return left, top, width, height
    rect = info.rcWork
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
