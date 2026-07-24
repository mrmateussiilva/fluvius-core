from redis import Redis
from rq import Queue

from app.config import settings


redis_connection = Redis.from_url(settings.redis_url)
default_queue = Queue("fluvius", connection=redis_connection)
