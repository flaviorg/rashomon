"""A minimal in-process job queue. Jobs are plain callables run by a worker thread."""

import queue
import threading

_jobs: "queue.Queue[tuple]" = queue.Queue()


def enqueue(fn, *args):
    _jobs.put((fn, args))


def _worker():
    while True:
        fn, args = _jobs.get()
        fn(*args)


threading.Thread(target=_worker, daemon=True).start()
