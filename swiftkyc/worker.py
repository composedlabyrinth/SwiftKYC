from rq import SimpleWorker, Queue, Connection
from app.workers.connection import redis_conn

listen = ["document_validation", "selfie_validation"]


class NoOpDeathPenalty:
    """Windows-safe death penalty that does nothing."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


if __name__ == "__main__":
    with Connection(redis_conn):
        # Make workers for each queue
        queues = [Queue(name, connection=redis_conn) for name in listen]

        worker = SimpleWorker(queues)
        worker.death_penalty_class = NoOpDeathPenalty

        worker.work(with_scheduler=False)
