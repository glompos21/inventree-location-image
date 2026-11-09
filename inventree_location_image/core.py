"""Stock location image plugin for InvenTree.

Adds an image to each stock location (InvenTree issue #9843), without
changing the core StockLocation model:

- AppMixin: stores images in the plugin's own LocationImage table
- UrlsMixin: API endpoint at /plugin/locationimage/location/<pk>/
- UserInterfaceMixin: an "Image" panel and an "Image" header button on the
  stock location detail page
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

    def location_context(self, request, context):
        """Build the frontend context for a stock location detail page.

        Returns None when the page is not a single stock location, or the
        user may not view stock locations.
        """
        context = context or {}

        if context.get('target_model') != 'stocklocation':
            return None

        try:
            location_id = int(context.get('target_id'))
        except (TypeError, ValueError):
            # Location index page (no specific location)
            return None

        user = request.user

        if not check_user_role(user, 'stock_location', 'view'):
            return None

        location_context = {
            'api_url': None,
            'can_edit': check_user_role(user, 'stock_location', 'change'),
            'max_size_mb': self.max_image_size() // (1024 * 1024),
            'error': None,
        }

        if not apps.is_installed(APP_NAME):
            location_context['error'] = (
                'App integration is disabled. Enable "App integration" in the '
                'plugin settings, restart the server and run database migrations.'
            )
        else:
            try:
                location_context['api_url'] = reverse(
                    f'plugin:{self.SLUG}:location-image', kwargs={'pk': location_id}
                )
            except NoReverseMatch:
                location_context['error'] = (
                    'URL integration is disabled. Enable "URL integration" in the '
                    'plugin settings and restart the server.'
                )

        return location_context

    def get_ui_panels(self, request, context, **kwargs):
        """Add an image panel to the stock location detail page."""
        location_context = self.location_context(request, context)

        if location_context is None:
            return []

        return [
            {
                'key': 'location-image',
                'title': 'Image',
                'description': 'Image of this stock location',
                'icon': 'ti:photo:outline',
                'source': self.plugin_static_file(
                    'location_image_panel.js:renderLocationImagePanel'
                ),
                'context': location_context,
            }
        ]

    def get_ui_primary_actions(self, request, context, **kwargs):
        """Add an "Image" button to the stock location page header.

        The button opens the image in a dialog, so it can be seen from any
        panel, including Location Details. Needs InvenTree 1.4 or newer;
        older versions never call this method.
        """
        location_context = self.location_context(request, context)

        if location_context is None:
            return []

        return [
            {
                'key': 'location-image-action',
                'title': 'Image',
                'description': 'Show the image of this stock location',
                'icon': 'ti:photo:outline',
                'source': self.plugin_static_file(
                    'location_image_panel.js:openLocationImageDialog'
                ),
                'context': location_context,
            }
        ]
