import contextvars
import logging
import uuid

request_id_var = contextvars.ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


class RequestIdFilter(logging.Filter):
    """Adds the current request id to every log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging() -> None:
    logger = logging.getLogger("app")
    if any(getattr(h, "_punch_handler", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler._punch_handler = True
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
