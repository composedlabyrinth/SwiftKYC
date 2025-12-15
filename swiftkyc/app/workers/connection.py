import redis
from rq import Queue

from app.core.config import settings

redis_conn = redis.Redis.from_url(settings.REDIS_URL)

# Single queue for document validation for now
document_queue = Queue("document_validation", connection=redis_conn)
selfie_queue = Queue("selfie_validation", connection=redis_conn)
