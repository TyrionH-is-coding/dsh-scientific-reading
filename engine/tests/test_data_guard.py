import multiprocessing
import time

import pytest

from scientific_reading.data_guard import DataRootBusy, data_root_freeze, data_root_operation


def _hold_operation(root, ready, release):
    with data_root_operation(root):
        ready.set()
        release.wait(10)


def _hold_freeze(root, entered, release):
    with data_root_freeze(root, timeout=5):
        entered.set()
        release.wait(10)


def _hold_until_killed(root, ready):
    with data_root_operation(root):
        ready.set()
        time.sleep(30)


def test_operation_reentrant_and_freeze_refuses_upgrade(tmp_path):
    with data_root_operation(tmp_path):
        with data_root_operation(tmp_path):
            with pytest.raises(DataRootBusy):
                with data_root_freeze(tmp_path, timeout=0):
                    pytest.fail("must not upgrade an active operation")
    with data_root_freeze(tmp_path):
        with pytest.raises(DataRootBusy, match="data_root_frozen"):
            with data_root_operation(tmp_path):
                pytest.fail("an operation must not run inside a freeze")


def test_backup_waits_for_writer_and_blocks_new_operations(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    ready, release, frozen, finish = (ctx.Event() for _ in range(4))
    writer = ctx.Process(target=_hold_operation, args=(tmp_path, ready, release))
    backup = ctx.Process(target=_hold_freeze, args=(tmp_path, frozen, finish))
    writer.start()
    try:
        assert ready.wait(5)
        backup.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with data_root_operation(tmp_path):
                    pass
            except DataRootBusy:
                break
            time.sleep(0.01)
        else:
            pytest.fail("backup did not close admission")
        assert not frozen.is_set(), "backup entered during an active writer"
        release.set()
        assert frozen.wait(5)
        with pytest.raises(DataRootBusy):
            with data_root_operation(tmp_path):
                pytest.fail("new writer entered a frozen root")
    finally:
        release.set()
        finish.set()
        writer.join(5)
        if backup.pid:
            backup.join(5)
        for child in (writer, backup):
            if child.pid and child.is_alive():
                child.terminate()
                child.join(5)
    assert writer.exitcode == backup.exitcode == 0
    with data_root_operation(tmp_path):
        pass


def test_timeout_and_crash_release_os_lock(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    writer = ctx.Process(target=_hold_until_killed, args=(tmp_path, ready))
    writer.start()
    try:
        assert ready.wait(5)
        with pytest.raises(DataRootBusy):
            with data_root_freeze(tmp_path, timeout=0.05):
                pytest.fail("active writer must prevent backup")
        writer.terminate()
        writer.join(5)
        with data_root_freeze(tmp_path, timeout=1):
            pass
    finally:
        if writer.is_alive():
            writer.terminate()
        writer.join(5)
