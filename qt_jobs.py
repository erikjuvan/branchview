"""Safe delivery when a background job outlives Qt application shutdown."""
from shiboken6 import isValid


def emit_if_alive(source, name, *args):
    if not isValid(source):
        return
    try:
        getattr(source, name).emit(*args)
    except RuntimeError:
        if isValid(source):
            raise
