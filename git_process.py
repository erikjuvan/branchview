"""Bounded, read-only Git commands with cooperative process cancellation."""
import os
import subprocess
from time import monotonic


class GitCancelled(Exception):
    pass


def run_git(path, args, cancelled=None, input_bytes=None, timeout=120):
    command = ['git', '--no-replace-objects', '-C', path, *args]
    env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'}
    if cancelled is None:
        result = subprocess.run(command, input=input_bytes, capture_output=True, timeout=timeout, env=env)
        if result.returncode:
            raise RuntimeError(result.stderr.decode('utf-8', errors='replace').strip() or 'Git command failed')
        return result.stdout
    if cancelled.is_set():
        raise GitCancelled()
    deadline = monotonic()+timeout
    with subprocess.Popen(command, stdin=subprocess.PIPE if input_bytes is not None else None,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
        pending_input = input_bytes
        while True:
            if cancelled.is_set():
                process.kill()
                process.communicate()
                raise GitCancelled()
            if monotonic() >= deadline:
                process.kill()
                process.communicate()
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                output, error = process.communicate(input=pending_input, timeout=.1)
                break
            except subprocess.TimeoutExpired:
                pending_input = None
        if process.returncode:
            raise RuntimeError(error.decode('utf-8', errors='replace').strip() or 'Git command failed')
        if cancelled.is_set():
            raise GitCancelled()
        return output
