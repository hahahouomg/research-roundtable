"""Process and file helpers shared by local CLI adapters."""
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

PROCESS_GROUP = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                 else {"start_new_session": True})


def process_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def stop_process(proc, force=False):
    if proc.returncode is not None:
        return
    try:
        if os.name == "nt":
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            subprocess.run([str(taskkill), "/PID", str(proc.pid), "/T", "/F"], timeout=3,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if proc.returncode is None:
                proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        pass
    except (PermissionError, subprocess.SubprocessError):
        proc.kill()


def write_text(path, value):
    # Readers see a complete version even if another process is exporting the same record.
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as out:
        staged = Path(out.name)
        try:
            out.write(value)
            out.close()
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def show_folder(path):
    if not path.is_dir():
        raise ValueError("文件夹已不存在")
    if os.name == "nt":
        os.startfile(str(path))
    else:
        opener = "/usr/bin/open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(path)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
