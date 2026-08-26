import ctypes

from scientific_reading import __main__ as cli


class Call:
    def __init__(self, implementation):
        self.implementation = implementation

    def __call__(self, *args):
        return self.implementation(*args)


def test_cli_windows_pid_with_exit_code_is_not_alive(monkeypatch):
    closed = []

    def set_exit_code(_handle, pointer):
        pointer._obj.value = 0
        return 1

    kernel32 = type("Kernel32", (), {})()
    kernel32.OpenProcess = Call(lambda *_args: 123)
    kernel32.GetExitCodeProcess = Call(set_exit_code)
    kernel32.CloseHandle = Call(lambda handle: closed.append(handle) or 1)
    monkeypatch.setattr(cli.os, "name", "nt")
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel32)

    assert cli._pid_is_alive(4321) is False
    assert closed == [123]
