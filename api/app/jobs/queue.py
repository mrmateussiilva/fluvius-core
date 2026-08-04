from redis import Redis
from rq import Queue

from app.config import settings

redis_connection = Redis.from_url(
    settings.redis_url,
    socket_connect_timeout=1,
    socket_timeout=2,
)
maintenance_queue = Queue("fluvius-maintenance", connection=redis_connection)
delivery_queue = Queue("fluvius-delivery", connection=redis_connection)
webhook_queue = Queue("fluvius-webhooks", connection=redis_connection)

# Compatibility alias for existing maintenance jobs.
default_queue = maintenance_queue
