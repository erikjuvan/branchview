"""Background repository reads and initial graph preparation."""
from threading import Event
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from git_reader import read_repository
from git_process import GitCancelled
from graph import build_graph
from layout import layout, branch_layout
from qt_jobs import emit_if_alive


_pool = QThreadPool()
_pool.setMaxThreadCount(2)


class LoadSignals(QObject):
    progress = Signal(object, str)
    finished = Signal(object, object, object, object, object)


class LoadJob(QRunnable):
    def __init__(self, key, path, options):
        super().__init__()
        self.key, self.path, self.options = key, path, options
        self.cancelled = Event()
        self.signals = LoadSignals()

    def run(self):
        repo = graph = positions = error = None
        try:
            repo = read_repository(self.path, **self.options, cancelled=self.cancelled,
                                   progress=lambda phase: emit_if_alive(self.signals, 'progress', self.key, phase))
            if self.cancelled.is_set():
                raise GitCancelled()
            emit_if_alive(self.signals, 'progress', self.key, 'Preparing graph and layout')
            graph = build_graph(repo, cancelled=self.cancelled)
            positions = (branch_layout(graph, cancelled=self.cancelled) if repo.branches_only else
                         layout(graph, cancelled=self.cancelled))
        except GitCancelled:
            pass
        except Exception as exc:
            error = str(exc)
        emit_if_alive(self.signals, 'finished', self.key, repo, graph, positions, error)


class RepositoryLoader(QObject):
    progress = Signal(str)
    ready = Signal(object, object, object, object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.serial = 0
        self.active = None
        self.jobs = {}

    def start(self, path, **options):
        self.cancel()
        self.serial += 1
        key = self.serial
        self.active = key
        job = LoadJob(key, path, options)
        self.jobs[key] = job
        job.signals.progress.connect(self.report)
        job.signals.finished.connect(self.finished)
        _pool.start(job)

    def cancel(self):
        for job in self.jobs.values():
            job.cancelled.set()
        self.active = None

    @Slot(object, str)
    def report(self, key, phase):
        if key == self.active:
            self.progress.emit(phase)

    @Slot(object, object, object, object, object)
    def finished(self, key, repo, graph, positions, error):
        job = self.jobs.pop(key, None)
        if job is None or key != self.active or job.cancelled.is_set():
            return
        self.active = None
        if error is not None:
            self.failed.emit(error)
        elif repo is not None:
            self.ready.emit(repo, graph, positions, job.options)
