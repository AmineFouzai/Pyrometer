import os
import threading

from .settings import app_dir, log_error, resource_dir

SKIP = (
    "Distance to TjMax", "Temperature Sensor Resolution", "Thermal Sensor Low",
    "Thermal Sensor High", "Thermal Sensor Critical", "Warning Temperature",
    "Critical Temperature",
)
NAMES = {
    "Cpu": "CPU", "GpuNvidia": "GPU", "GpuAmd": "GPU", "GpuIntel": "GPU",
    "Motherboard": "MB", "SuperIO": "MB", "Storage": "DISK", "Memory": "RAM",
}
HINTS = {
    "Cpu": ("cpu package", "core (tctl/tdie)", "core average", "cpu cores"),
    "GpuNvidia": ("gpu core",), "GpuAmd": ("gpu core", "gpu edge"),
    "GpuIntel": ("gpu core",), "Storage": ("temperature",),
}


def primary(group):
    available = [sensor for sensor in group["sensors"] if sensor[1] is not None]
    if not available:
        return group["sensors"][0] if group["sensors"] else None
    hints = HINTS.get(group["type"], ())
    for exact in (True, False):
        for hint in hints:
            for sensor in available:
                name = sensor[0].lower()
                if (name == hint) if exact else (hint in name):
                    return sensor
    return max(available, key=lambda sensor: sensor[1])


class SensorReader(threading.Thread):
    """LibreHardwareMonitor worker. Sleeps while the widget is hidden."""

    def __init__(self, refresh):
        super().__init__(daemon=True, name="PyrometerSensors")
        self.refresh = refresh
        self.snapshot = ()
        self.revision = 0
        self.error = None
        self.missing = []
        self._computer = None
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self.paused = False

    def open(self):
        try:
            import clr  # noqa: F401  (boots the CLR so System.* is importable)
            from System.Reflection import Assembly

            self._install_assembly_resolver()
            dll = self._locate("LibreHardwareMonitorLib.dll")
            if not dll:
                raise FileNotFoundError(
                    "LibreHardwareMonitorLib.dll not found in "
                    + " or ".join(self._search_dirs()))
            # AddReference rejects absolute paths in frozen builds; LoadFrom
            # takes the file directly and still registers the namespace.
            Assembly.LoadFrom(dll)
            from LibreHardwareMonitor import Hardware
        except Exception as exc:
            self.error = str(exc).splitlines()[0]
            log_error(f"assembly load failed: {exc}")
            return False

        groups = ("IsCpuEnabled", "IsGpuEnabled", "IsMotherboardEnabled",
                  "IsStorageEnabled", "IsMemoryEnabled")
        enabled = set(groups)
        culprits = (("RAMSPDToolkit", "IsMemoryEnabled"),
                    ("DiskInfoToolkit", "IsStorageEnabled"))
        while enabled:
            computer = Hardware.Computer()
            for name in groups:
                setattr(computer, name, name in enabled)
            try:
                computer.Open()
                self._computer = computer
                self.error = None
                return True
            except Exception as exc:
                message = str(exc).splitlines()[0]
                dropped = next((group for dll, group in culprits
                                if dll.lower() in message.lower() and group in enabled), None)
                try:
                    computer.Close()
                except Exception:
                    pass
                if not dropped:
                    self.error = message
                    log_error(f"Computer.Open failed: {exc}")
                    return False
                enabled.remove(dropped)
                self.missing.append(dropped[2:-7].lower())
        return False

    @staticmethod
    def _search_dirs():
        """Bundle extraction folder, the app folder, then its parent — the
        last one covers source runs where the DLLs sit beside the project."""
        dirs = [resource_dir(), app_dir(), os.path.dirname(app_dir())]
        return [d for i, d in enumerate(dirs) if d and d not in dirs[:i]]

    def _locate(self, filename):
        for directory in self._search_dirs():
            candidate = os.path.join(directory, filename)
            if os.path.exists(candidate):
                return candidate
        return None

    def _install_assembly_resolver(self):
        """Frozen builds extract the .NET DLLs somewhere other than the folder
        the CLR probes, so resolve LHM's dependencies by hand."""
        from System import AppDomain, ResolveEventHandler
        from System.Reflection import Assembly, AssemblyName

        def resolve(_sender, args):
            dll = self._locate(AssemblyName(args.Name).Name + ".dll")
            return Assembly.LoadFrom(dll) if dll else None

        # Kept on the instance: the CLR only holds a weak reference to it.
        self._resolver = ResolveEventHandler(resolve)
        AppDomain.CurrentDomain.AssemblyResolve += self._resolver

    def run(self):
        while not self._stop_event.is_set():
            if not self.paused:
                try:
                    self.snapshot = self._poll()
                    self.error = None
                    self.revision += 1
                except Exception as exc:
                    self.error = str(exc).splitlines()[0]
                    self.revision += 1
            self._wake.wait(self.refresh)
            self._wake.clear()

    def _poll(self):
        groups = []
        for hardware in self._computer.Hardware:
            hardware.Update()
            for child in hardware.SubHardware:
                child.Update()
            found = []
            self._scan(hardware, found)
            if found:
                groups.append({"name": str(hardware.Name),
                               "type": str(hardware.HardwareType),
                               "sensors": tuple(found)})
        return tuple(groups)

    def _scan(self, hardware, found):
        for sensor in hardware.Sensors:
            if str(sensor.SensorType) != "Temperature":
                continue
            name = str(sensor.Name)
            if any(item in name for item in SKIP):
                continue
            value = sensor.Value
            found.append((name, float(value) if value is not None else None))
        for child in hardware.SubHardware:
            self._scan(child, found)

    def set_paused(self, paused):
        self.paused = paused
        self._wake.set()

    def close(self):
        self._stop_event.set()
        self._wake.set()
        if self._computer:
            try:
                self._computer.Close()
            except Exception:
                pass
