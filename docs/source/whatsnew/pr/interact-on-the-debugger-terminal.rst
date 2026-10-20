``interact`` follows the debugger's terminal
============================================

The debugger's ``interact`` command now opens its IPython shell on the same
terminal the debugger prompts on. When ``TerminalPdb`` is given its own
prompt_toolkit input and output through ``pt_session_options`` (a pty, a
remote debugger such as madbg) in a process whose stdin and stdout are not a
terminal, the embedded shell used to prompt on that stdin instead and never
appeared; it now prompts, completes and prints where the debugger does, and
``input()`` inside it reads from there too.
