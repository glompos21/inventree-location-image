"""Django app configuration for the stock location image plugin."""

from django.apps import AppConfig, apps

import structlog

logger = structlog.get_logger('inventree')


class LocationImageConfig(AppConfig):
    """App config for the stock location image plugin."""

    name = 'inventree_location_image'
    label = 'inventree_location_image'
    verbose_name = 'Stock Location Images'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        """Run when the plugin app is registered with Django."""
        self.expire_model_caches()
        self.remove_orphans()

    @staticmethod
    def expire_model_caches():
        """Make core models aware of the LocationImage relations.

        InvenTree adds plugin apps after startup. Django caches each model's
        reverse relations on first use, and Apps.clear_cache() does not reset
        them while the registry is being repopulated. A stale cache means
        deleting a StockLocation (or a User) does not cascade to LocationImage.
        """
        for model in apps.get_models(include_auto_created=True):
            model._meta._expire_cache()

    @staticmethod
    def remove_orphans():
        """Remove images for stock locations deleted while the plugin was off."""
        from InvenTree.ready import canAppAccessDatabase

        # Not during migrations, backups, data import or tests
        if not canAppAccessDatabase():
            return

        from .models import cleanup_orphans

        try:
            cleanup_orphans()
        except Exception:
            # e.g. the table does not exist yet, before the first migration
            logger.warning('Could not clean up orphaned stock location images')
