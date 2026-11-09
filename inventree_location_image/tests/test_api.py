"""API and UI tests for the stock location image plugin.

Run from the InvenTree backend directory (src/backend/InvenTree):

    INVENTREE_PLUGIN_TESTING_SETUP=True python manage.py test inventree_location_image
"""

import os
import shutil
import tempfile
from io import BytesIO
from unittest import mock

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models.deletion import get_candidate_relations_to_delete
from django.test import RequestFactory, override_settings
from django.urls import reverse

from PIL import Image

from InvenTree.unit_test import InvenTreeAPITestCase
from plugin.registry import registry
from stock.models import StockLocation

from ..models import LocationImage, cleanup_orphans

TEMP_MEDIA = tempfile.mkdtemp(prefix='location_image_test_')


def make_image(name='shelf.png', fmt='PNG', size=(64, 48), noise=False):
    """Return an uploadable image file."""
    if noise:
        # Random pixels do not compress, so the file stays large
        img = Image.frombytes('RGB', size, os.urandom(size[0] * size[1] * 3))
    else:
        img = Image.new('RGB', size, 'red')

    buffer = BytesIO()
    img.save(buffer, fmt)

    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


def stored_files(obj):
    """Names of the stored image file and its variations."""
    field = obj._meta.get_field('image')
    name = obj.image.name

    return [name] + [
        field.attr_class.get_variation_name(name, variation)
        for variation in field.variations
    ]


class ActivePluginMixin:
    """Activate the plugin for a test class.

    Plugins start inactive in the test database. Activating the plugin and
    reloading the registry also registers its URL patterns.
    """

    @classmethod
    def setUpTestData(cls):
        """Activate the plugin and reload the registry."""
        super().setUpTestData()

        registry.set_plugin_state('locationimage', True)
        registry.reload_plugins()


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class LocationImageAPITest(ActivePluginMixin, InvenTreeAPITestCase):
    """Tests for the /plugin/locationimage/location/<pk>/ endpoint."""

    roles = ['stock_location.view', 'stock_location.change']

    @classmethod
    def setUpTestData(cls):
        """Create stock locations for the tests."""
        super().setUpTestData()

        cls.location = StockLocation.objects.create(name='Shelf A')
        cls.other = StockLocation.objects.create(name='Shelf B')

    @classmethod
    def tearDownClass(cls):
        """Remove uploaded test files."""
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        """Resolve the endpoint URL for each test."""
        super().setUp()
        self.url = self.image_url(self.location.pk)

    @staticmethod
    def image_url(pk):
        """URL of the image endpoint for a stock location."""
        return reverse('plugin:locationimage:location-image', kwargs={'pk': pk})

    def upload(self, file=None, expected_code=201, pk=None):
        """Upload an image through the API, running on-commit callbacks."""
        with self.captureOnCommitCallbacks(execute=True):
            return self.post(
                self.image_url(pk or self.location.pk),
                {'image': file or make_image()},
                format='multipart',
                expected_code=expected_code,
            )

    def current(self):
        """The image row for the main test location."""
        return LocationImage.objects.get(location=self.location)

    def test_plugin_loaded(self):
        """The plugin is registered and active."""
        plugin = registry.get_plugin('locationimage')
        self.assertIsNotNone(plugin)
        self.assertTrue(plugin.is_active())

    def test_no_image(self):
        """A location without an image returns 404."""
        self.get(self.url, expected_code=404)

    def test_unknown_location(self):
        """A location which does not exist returns 404 for every method."""
        url = self.image_url(99999)

        self.get(url, expected_code=404)
        self.post(url, {'image': make_image()}, format='multipart', expected_code=404)
        self.delete(url, expected_code=404)

    def test_upload(self):
        """Uploading stores the image and its variations."""
        response = self.upload()

        data = response.data
        self.assertEqual(data['location'], self.location.pk)
        self.assertEqual(data['uploaded_by'], self.user.pk)

        for key in ['image', 'thumbnail', 'preview']:
            self.assertIn('location_images/', data[key])

        self.assertIn('.thumbnail.', data['thumbnail'])
        self.assertIn('.preview.', data['preview'])

        for name in stored_files(self.current()):
            self.assertTrue(default_storage.exists(name), name)

        # Read back
        response = self.get(self.url)
        self.assertEqual(response.data['image'], data['image'])

        # Other locations are unaffected
        self.get(self.image_url(self.other.pk), expected_code=404)

    def test_head(self):
        """HEAD requests from non-superusers do not fail (no entry in ACTION_MAP)."""
        self.upload()
        response = self.client.head(self.url)
        self.assertEqual(response.status_code, 200)

    def test_replace(self):
        """Uploading again replaces the image and removes the old files."""
        self.upload()
        old_files = stored_files(self.current())

        response = self.upload(make_image('new.jpg', 'JPEG'), expected_code=200)
        self.assertTrue(response.data['image'].endswith('.jpg'))

        self.assertEqual(
            LocationImage.objects.filter(location=self.location).count(), 1
        )

        for name in old_files:
            self.assertFalse(default_storage.exists(name), name)

        for name in stored_files(self.current()):
            self.assertTrue(default_storage.exists(name), name)

    def test_failed_replace_keeps_image(self):
        """A rejected upload leaves the existing image in place."""
        self.upload()
        files = stored_files(self.current())

        self.upload(make_image('bad.svg'), expected_code=400)

        self.assertEqual(stored_files(self.current()), files)

        for name in files:
            self.assertTrue(default_storage.exists(name), name)

    def test_delete(self):
        """Deleting removes the database row and the stored files."""
        self.upload()
        files = stored_files(self.current())

        with self.captureOnCommitCallbacks(execute=True):
            self.delete(self.url, expected_code=204)

        self.assertFalse(LocationImage.objects.filter(location=self.location).exists())

        for name in files:
            self.assertFalse(default_storage.exists(name), name)

        # Nothing left to delete
        self.delete(self.url, expected_code=404)

    def test_relation_registered(self):
        """Django knows to cascade StockLocation deletes to LocationImage."""
        # Compare labels: the registry reload re-imports the plugin models
        related = [
            rel.related_model._meta.label
            for rel in get_candidate_relations_to_delete(StockLocation._meta)
        ]
        self.assertIn(LocationImage._meta.label, related)

    def test_delete_location(self):
        """Deleting the stock location removes its image as well."""
        self.upload()
        files = stored_files(self.current())

        with self.captureOnCommitCallbacks(execute=True):
            StockLocation.objects.get(pk=self.location.pk).delete()

        self.assertEqual(LocationImage.objects.count(), 0)

        for name in files:
            self.assertFalse(default_storage.exists(name), name)

    def test_rollback_keeps_files(self):
        """Files are only deleted when the transaction commits."""
        self.upload()
        files = stored_files(self.current())

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    StockLocation.objects.get(pk=self.location.pk).delete()
                    raise RuntimeError('roll back')
            except RuntimeError:
                pass

        self.assertEqual(callbacks, [])
        self.assertTrue(LocationImage.objects.filter(location=self.location).exists())

        for name in files:
            self.assertTrue(default_storage.exists(name), name)

    def test_cleanup_orphans(self):
        """Images whose location no longer exists are removed by cleanup."""
        self.upload(pk=self.other.pk)
        orphan = LocationImage.objects.get(location=self.other)
        files = stored_files(orphan)

        # Simulate a delete made while the plugin was inactive (no cascade):
        # possible because the foreign key has no database constraint
        LocationImage.objects.filter(pk=orphan.pk).update(location_id=987654)

        self.upload()  # Not an orphan

        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(cleanup_orphans(), 1)

        self.assertFalse(LocationImage.objects.filter(pk=orphan.pk).exists())
        self.assertTrue(LocationImage.objects.filter(location=self.location).exists())

        for name in files:
            self.assertFalse(default_storage.exists(name), name)

        # Nothing left to clean
        self.assertEqual(cleanup_orphans(), 0)

    def test_invalid_files(self):
        """Files which are not valid raster images are rejected."""
        # Not an image at all
        fake = SimpleUploadedFile('fake.png', b'not an image', content_type='image/png')
        response = self.upload(fake, expected_code=400)
        self.assertIn('image', response.data)

        # SVG can carry scripts, so it is not accepted
        svg = SimpleUploadedFile(
            'drawing.svg',
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            content_type='image/svg+xml',
        )
        self.upload(svg, expected_code=400)

        # Valid image data, but a disallowed extension
        self.upload(make_image('shelf.exe'), expected_code=400)

        # PostScript disguised as PNG: would be rendered through Ghostscript
        response = self.upload(make_image('evil.png', 'EPS'), expected_code=400)
        self.assertIn('Unsupported image format', str(response.data['image']))

        # Missing file
        self.post(self.url, {}, format='multipart', expected_code=400)

        self.assertEqual(LocationImage.objects.count(), 0)

    def test_max_pixels(self):
        """Images with very large dimensions are rejected."""
        with mock.patch('inventree_location_image.serializers.MAX_PIXELS', 1000):
            response = self.upload(make_image(size=(50, 50)), expected_code=400)
            self.assertIn('dimensions', str(response.data['image']))

            self.upload(make_image(size=(20, 20)))

    def test_max_size(self):
        """Images larger than the MAX_IMAGE_SIZE setting are rejected."""
        plugin = registry.get_plugin('locationimage')
        plugin.set_setting('MAX_IMAGE_SIZE', 1)

        big = make_image('big.png', size=(1024, 1024), noise=True)
        self.assertGreater(big.size, 1024 * 1024)

        response = self.upload(big, expected_code=400)
        self.assertIn('too large', str(response.data['image']))

        # Small images are still accepted
        self.upload()

    def test_view_only_user(self):
        """Users with view access can read, but not change, the image."""
        self.upload()

        self.clearRoles()
        self.assignRole('stock_location.view')

        self.get(self.url, expected_code=200)
        self.upload(expected_code=403)
        self.delete(self.url, expected_code=403)

        self.assertEqual(LocationImage.objects.count(), 1)

    def test_no_role(self):
        """Users without the stock_location role cannot read the image."""
        self.clearRoles()
        self.get(self.url, expected_code=403)

    def test_anonymous(self):
        """Anonymous users are rejected."""
        self.logout()
        response = self.client.get(self.url)
        self.assertIn(response.status_code, [401, 403])


class LocationImagePanelTest(ActivePluginMixin, InvenTreeAPITestCase):
    """Tests for the stock location UI panel."""

    roles = ['stock_location.view']

    @classmethod
    def setUpTestData(cls):
        """Create a stock location for the tests."""
        super().setUpTestData()
        cls.location = StockLocation.objects.create(name='Rack 1')

    def setUp(self):
        """Prepare a request for the current user."""
        super().setUp()
        self.plugin = registry.get_plugin('locationimage')
        self.request = RequestFactory().get('/')
        self.request.user = self.user

    def panels(self, **context):
        """Return the panels for the given context."""
        return self.plugin.get_ui_panels(self.request, context)

    def test_panel(self):
        """The panel is shown on the stock location detail page."""
        panels = self.panels(target_model='stocklocation', target_id=self.location.pk)

        self.assertEqual(len(panels), 1)
        panel = panels[0]

        self.assertEqual(panel['key'], 'location-image')
        self.assertIn('location_image_panel.js', panel['source'])

        ctx = panel['context']
        self.assertIsNone(ctx['error'])
        self.assertEqual(
            ctx['api_url'],
            reverse(
                'plugin:locationimage:location-image', kwargs={'pk': self.location.pk}
            ),
        )
        # This user has view access only
        self.assertFalse(ctx['can_edit'])
        self.assertEqual(ctx['max_size_mb'], 10)

    def test_can_edit(self):
        """Users with change access can edit the image."""
        self.assignRole('stock_location.change')

        panels = self.panels(target_model='stocklocation', target_id=self.location.pk)
        self.assertTrue(panels[0]['context']['can_edit'])

    def test_hidden(self):
        """The panel is not shown on other pages, or without view access."""
        self.assertEqual(self.panels(target_model='part', target_id=1), [])
        self.assertEqual(self.panels(target_model='stocklocation'), [])
        self.assertEqual(self.panels(target_model='stocklocation', target_id='abc'), [])
        self.assertEqual(self.panels(), [])

        self.clearRoles()
        self.assertEqual(
            self.panels(target_model='stocklocation', target_id=self.location.pk), []
        )

    def actions(self, **context):
        """Return the page header buttons for the given context."""
        return self.plugin.get_ui_primary_actions(self.request, context)

    def test_primary_action(self):
        """An "Image" button is shown in the stock location page header."""
        actions = self.actions(target_model='stocklocation', target_id=self.location.pk)

        self.assertEqual(len(actions), 1)
        action = actions[0]

        self.assertEqual(action['key'], 'location-image-action')
        self.assertEqual(action['title'], 'Image')
        self.assertTrue(
            action['source'].endswith('location_image_panel.js:openLocationImageDialog')
        )

        # Same context as the panel
        panel = self.panels(target_model='stocklocation', target_id=self.location.pk)[0]
        self.assertEqual(action['context'], panel['context'])

    def test_primary_action_hidden(self):
        """The button is not shown on other pages, or without view access."""
        self.assertEqual(self.actions(target_model='part', target_id=1), [])
        self.assertEqual(self.actions(target_model='stocklocation'), [])
        self.assertEqual(self.actions(), [])

        self.clearRoles()
        self.assertEqual(
            self.actions(target_model='stocklocation', target_id=self.location.pk), []
        )

    def test_primary_action_api(self):
        """The button is served by the InvenTree UI feature API.

        The frontend sends the page context as query parameters, so the
        location id arrives as a string.
        """
        from common.models import InvenTreeSetting

        InvenTreeSetting.set_setting('ENABLE_PLUGINS_INTERFACE', True, change_user=None)

        url = reverse(
            'api-plugin-ui-feature-list', kwargs={'feature': 'primary_action'}
        )
        response = self.get(
            url, {'target_model': 'stocklocation', 'target_id': str(self.location.pk)}
        )

        actions = [a for a in response.data if a['plugin_name'] == 'locationimage']
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['key'], 'location-image-action')
        self.assertIn('api_url', actions[0]['context'])
