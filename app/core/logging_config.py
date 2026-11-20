"""Central logging setup shared by the API and background worker processes."""

import logging
import logging.config


def configure_logging(level: str = "INFO") -> None:
    """Configure consistent console logging for the application."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                },
            },
            "root": {
                "level": level.upper(),
                "handlers": ["console"],
            },
        }
    )
