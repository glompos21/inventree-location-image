"""Stock location image plugin for InvenTree.

Adds an image to each stock location (InvenTree issue #9843), without
changing the core StockLocation model:

- AppMixin: stores images in the plugin's own LocationImage table
- UrlsMixin: API endpoint at /plugin/locationimage/location/<pk>/
- UserInterfaceMixin: an "Image" panel on the stock location detail page
"""

from django.apps import apps
from django.core.validators import MinValueValidator
from django.urls import NoReverseMatch, path, reverse

import structlog

from plugin import InvenTreePlugin
from plugin.mixins import AppMixin, SettingsMixin, UrlsMixin, UserInterfaceMixin
from users.permissions import check_user_role

from . import PLUGIN_VERSION

logger = structlog.get_logger('inventree')

APP_NAME = 'inventree_location_image'
DEFAULT_MAX_SIZE_MB = 10


class LocationImagePlugin(
    AppMixin, SettingsMixin, UrlsMixin, UserInterfaceMixin, InvenTreePlugin
):
    """Upload and display an image for each stock location."""

    NAME = 'LocationImage'
    SLUG = 'locationimage'
    TITLE = 'Stock Location Images'
    DESCRIPTION = 'Upload and display an image for each stock location'
    VERSION = PLUGIN_VERSION
    AUTHOR = 'glompos21'
    LICENSE = 'MIT'
    MIN_VERSION = '1.0.0'

    SETTINGS = {
        'MAX_IMAGE_SIZE': {
            'name': 'Maximum image size (MB)',
            'description': 'Largest image file that can be uploaded for a stock location',
            'default': DEFAULT_MAX_SIZE_MB,
            'validator': [int, MinValueValidator(1)],
        }
    }

    def setup_urls(self):
        """URL patterns for this plugin (mounted at /plugin/locationimage/)."""
        from .views import LocationImageView

        return [
            path(
                'location/<int:pk>/',
                LocationImageView.as_view(plugin=self),
                name='location-image',
            )
        ]

    def max_image_size(self) -> int:
        """Return the maximum upload size, in bytes."""
        try:
            size_mb = int(self.get_setting('MAX_IMAGE_SIZE'))
        except (TypeError, ValueError):
            size_mb = DEFAULT_MAX_SIZE_MB

        return max(size_mb, 1) * 1024 * 1024

    def get_ui_panels(self, request, context, **kwargs):
        """Add an image panel to the stock location detail page."""
        context = context or {}

        if context.get('target_model') != 'stocklocation':
            return []

        try:
            location_id = int(context.get('target_id'))
        except (TypeError, ValueError):
            # Location index page (no specific location)
            return []

        user = request.user

        if not check_user_role(user, 'stock_location', 'view'):
            return []

        panel_context = {
            'api_url': None,
            'can_edit': check_user_role(user, 'stock_location', 'change'),
            'max_size_mb': self.max_image_size() // (1024 * 1024),
            'error': None,
        }

        if not apps.is_installed(APP_NAME):
            panel_context['error'] = (
                'App integration is disabled. Enable "App integration" in the '
                'plugin settings, restart the server and run database migrations.'
            )
        else:
            try:
                panel_context['api_url'] = reverse(
                    f'plugin:{self.SLUG}:location-image', kwargs={'pk': location_id}
                )
            except NoReverseMatch:
                panel_context['error'] = (
                    'URL integration is disabled. Enable "URL integration" in the '
                    'plugin settings and restart the server.'
                )

        return [
            {
                'key': 'location-image',
                'title': 'Image',
                'description': 'Image of this stock location',
                'icon': 'ti:photo:outline',
                'source': self.plugin_static_file(
                    'location_image_panel.js:renderLocationImagePanel'
                ),
                'context': panel_context,
            }
        ]
