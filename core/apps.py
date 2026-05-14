from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        # Import for side effect: connects the post_save receiver in signals.py.
        from . import signals  # noqa: F401
