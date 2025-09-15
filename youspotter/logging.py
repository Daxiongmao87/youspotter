import logging
import uuid


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s [cid=%(cid)s attempt=%(attempt)s]: %(message)s')
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def with_context(logger: logging.Logger, attempt: int = 0, cid: str | None = None):
    if cid is None:
        cid = uuid.uuid4().hex[:8]
    extra = {'cid': cid, 'attempt': attempt}
    return logging.LoggerAdapter(logger, extra), cid

