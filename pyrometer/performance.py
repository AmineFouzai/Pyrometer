import ctypes


class ResourceGovernor:
    """Ask Windows to favor foreground apps and reclaim us under pressure."""

    BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

    @staticmethod
    def enable():
        kernel32 = ctypes.windll.kernel32
        handle = ctypes.c_void_p(-1)
        kernel32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        kernel32.SetPriorityClass(handle, ResourceGovernor.BELOW_NORMAL_PRIORITY_CLASS)

        # PROCESS_MEMORY_PRIORITY_INFORMATION: 1=lowest, 5=normal.
        priority = ctypes.c_ulong(2)
        try:
            kernel32.SetProcessInformation(
                handle, 0, ctypes.byref(priority), ctypes.sizeof(priority))
        except Exception:
            pass

    @staticmethod
    def trim():
        """Release unused resident pages after the widget is hidden."""
        try:
            empty = ctypes.windll.psapi.EmptyWorkingSet
            empty.argtypes = (ctypes.c_void_p,)
            empty(ctypes.c_void_p(-1))
        except Exception:
            pass
