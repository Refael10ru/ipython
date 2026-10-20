"""``interact`` must prompt on the debugger's own terminal.

A ``TerminalPdb`` can be handed a terminal of its own through
``pt_session_options`` (a pty here, as madbg or any remote debugger does),
in a process whose stdin and stdout are not a terminal. The embedded IPython
shell behind ``interact`` has to show up on that terminal, not on the
process's stdin, or ``interact`` never comes back.
"""

import atexit
import gc
import os
import re
import sys
import threading
import time

import pytest

from IPython.core.history import HistoryManager
from IPython.terminal.debugger import TerminalPdb

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[=>]|\x1b\][^\x07]*\x07")


@pytest.fixture
def _embedded_shell_allowed(monkeypatch):
    """``interact`` creates an embedded shell next to the session's one; let it,
    and release it afterwards (as tests/test_embed.py does)."""
    monkeypatch.setattr(HistoryManager, "_max_inst", float("inf"))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # the embed replaces it
    before = set(HistoryManager._instances)
    yield
    for hm in set(HistoryManager._instances) - before:
        if hm.save_thread is not None:
            atexit.unregister(hm.save_thread.stop)
        if hm.shell is not None:
            atexit.unregister(hm.shell.atexit_operations)
        hm.close()
        HistoryManager._instances.discard(hm)
    gc.collect()


@pytest.mark.skipif(sys.platform == "win32", reason="needs a pty")
@pytest.mark.usefixtures("_embedded_shell_allowed")
def test_interact_prompts_on_the_debugger_terminal(monkeypatch):
    monkeypatch.setenv("PROMPT_TOOLKIT_NO_CPR", "1")  # nobody answers cursor requests
    from prompt_toolkit.input.vt100 import Vt100Input
    from prompt_toolkit.output.vt100 import Vt100_Output

    master, slave = os.openpty()
    slave_in = os.fdopen(slave, "r", buffering=1, encoding="utf-8", errors="replace")
    slave_out = os.fdopen(
        os.dup(slave), "w", buffering=1, encoding="utf-8", errors="replace"
    )
    dbg = TerminalPdb(
        stdin=slave_in,
        stdout=slave_out,
        nosigint=True,
        readrc=False,
        pt_session_options={
            "input": Vt100Input(slave_in),
            "output": Vt100_Output.from_pty(slave_out),
        },
    )
    dbg.use_rawinput = True

    seen = bytearray()

    def expect(needle, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if needle in ANSI.sub("", seen.decode("utf-8", "replace")):
                return True
            time.sleep(0.05)
        return False

    def read_master():
        while True:
            try:
                data = os.read(master, 65536)
            except OSError:
                return
            if not data:
                return
            seen.extend(data)

    outcome = {}

    def drive():
        outcome["ipdb"] = expect("ipdb>")
        os.write(master, b"interact\r")
        outcome["shell"] = expect("In [1]:")
        if outcome["shell"]:
            os.write(master, b"answer + 1\r")  # a local of the frame
            outcome["result"] = expect("Out[1]: 43")
            os.write(master, b"\x04")  # Ctrl-D: leave the shell
            if expect("really want to exit", 3):  # confirm_exit, read via input()
                os.write(master, b"y\r")
            outcome["back"] = expect("ipdb>")
        os.write(master, b"c\r")

    threading.Thread(target=read_master, daemon=True).start()
    driver = threading.Thread(target=drive, daemon=True)
    driver.start()

    answer = 42  # noqa: F841 - read by the shell through the frame's locals
    dbg.set_trace()
    driver.join(timeout=15)

    assert outcome == {"ipdb": True, "shell": True, "result": True, "back": True}, (
        outcome,
        bytes(seen),
    )
