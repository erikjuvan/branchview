"""Cancellable operations whose results belong to one UI owner."""
from threading import Event
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from git_process import GitCancelled
from qt_jobs import emit_if_alive

_pool = QThreadPool()
_pool.setMaxThreadCount(2)


class Signals(QObject):
    result = Signal(object, object, object)
    progress = Signal(object, str)


class Job(QRunnable):
    def __init__(self, key, operation):
        super().__init__()
        self.key, self.operation = key, operation
        self.cancelled = Event()
        self.signals = Signals()

    def run(self):
        value = error = None
        try:
            value = self.operation(self.cancelled, lambda message: emit_if_alive(self.signals, 'progress', self.key, message))
        except GitCancelled:
            pass
        except Exception as exc:
            error = str(exc)
        emit_if_alive(self.signals, 'result', self.key, value, error)


class BackgroundTask(QObject):
    ready = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.serial = 0
        self.jobs = {}
        self.active = None
        if parent is not None:
            parent.destroyed.connect(self.cancel)

    def start(self, operation):
        self.cancel()
        self.serial += 1
        job = Job(self.serial, operation)
        self.active = job.key
        self.jobs[job.key] = job
        job.signals.result.connect(self.finished)
        job.signals.progress.connect(self.report)
        _pool.start(job)

    def report(self, key, message):
        if key == self.active:
            self.progress.emit(message)

    def finished(self, key, value, error):
        job = self.jobs.pop(key, None)
        if job is None or key != self.active or job.cancelled.is_set():
            return
        self.active = None
        if error is not None:
            self.failed.emit(error)
        else:
            self.ready.emit(value)

    def cancel(self):
        self.active = None
        for job in self.jobs.values():
            job.cancelled.set()
