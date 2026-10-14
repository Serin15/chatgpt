"""Redact env credentials and authenticated bot paths from installed log handlers."""

import logging
import os
import re

from app.credentials import SECRET_VALUES


def redact(message):
    message = str(message)
    for key in (
        "PULSE_AI_API_KEY",
        "OPENAI_API_KEY",
        "JUPITER_API_KEY",
        "GOPLUS_ACCESS_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "PULSE_AUTH_PASSWORD",
    ):
        value = os.getenv(key)
        if value:
            message = message.replace(value, "[REDACTED]")
    for value in SECRET_VALUES:
        message = message.replace(value, "[REDACTED]")
    message = re.sub(
        r"([?&](?:api[-_]?key|token|access_token|auth|signature)=)[^&\s]+",
        r"\1[REDACTED]",
        message,
        flags=re.I,
    )
    return re.sub(r"/bot[^/\s]+/", "/bot[REDACTED]/", message)


class RedactSecrets(logging.Filter):
    def filter(self, record):
        # AccessFormatter needs its original five positional arguments and their types.
        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(v) if isinstance(v, str) else v for v in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()
            }
        return True


class SafeFormatter(logging.Formatter):
    def __init__(self, original):
        super().__init__()
        self.original = original or logging.Formatter()

    def format(self, record):
        result = redact(self.original.format(record))
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return result


def install_redaction():
    redaction = RedactSecrets()
    loggers = [logging.getLogger()] + [
        v for v in logging.Logger.manager.loggerDict.values() if isinstance(v, logging.Logger)
    ]
    for logger in loggers:
        for handler in logger.handlers:
            handler.addFilter(redaction)
            if not isinstance(handler.formatter, SafeFormatter):
                handler.setFormatter(SafeFormatter(handler.formatter))
