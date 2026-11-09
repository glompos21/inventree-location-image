"""Database models for the stock location image plugin."""

import os
import uuid
from functools import partial

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

import structlog
from stdimage.models import StdImageField

logger = structlog.get_logger('inventree')

# Raster formats only: SVG is rejected because it can carry scripts
ALLOWED_EXTENSIONS = ['bmp', 'gif', 'jpeg', 'jpg', 'png', 'tif', 'tiff', 'webp']

IMAGE_VARIATIONS = {'thumbnail': (128, 128), 'preview': (256, 256)}


def rename_location_image(instance, filename):
    """Return the storage path for an uploaded stock location image.

    A random suffix is added so that a replaced image gets a new URL,
    which stops browsers from showing a cached copy of the old one.
    """
    ext = os.path.splitext(filename)[1].lower().lstrip('.')

    name = f'location_{instance.location_id}_{uuid.uuid4().hex[:8]}'

    if ext:
        name = f'{name}.{ext}'

    return os.path.join('location_images', name)


class LocationImage(models.Model):
    """An image linked to a single stock location.

    Attributes:
        location: The stock location which this image belongs to
        image: The uploaded image (with thumbnail and preview variations)
        uploaded_by: The user who uploaded the current image
        updated: When the image was last changed

    Both foreign keys use db_constraint=False. When the plugin is deactivated
    its model is unregistered, so Django no longer cascades deletes to this
    table: a database constraint would then make every delete of a stock
    location (or user) with an image fail. Rows left behind are removed by
    cleanup_orphans() when the plugin app next loads.
    """

    class Meta:
        """Model options."""

        app_label = 'inventree_location_image'
        verbose_name = _('Location Image')
        verbose_name_plural = _('Location Images')

    location = models.OneToOneField(
        'stock.StockLocation',
        on_delete=models.CASCADE,
        db_constraint=False,
        # No reverse accessor, so this cannot clash with a future core field
        related_name='+',
        verbose_name=_('Stock Location'),
    )

    image = StdImageField(
        upload_to=rename_location_image,
        variations=IMAGE_VARIATIONS,
        validators=[FileExtensionValidator(ALLOWED_EXTENSIONS)],
        # Stored files are removed by the post_delete handler below, once the
        # transaction commits (stdimage's delete_orphans removes them at once,
        # so a rollback would leave a row without its file)
        verbose_name=_('Image'),
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        db_constraint=False,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('Uploaded by'),
    )

    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))

    def __str__(self):
        """Text representation of this image."""
        return f'Image for stock location {self.location_id}'


def delete_image_files(name: str):
    """Delete a stored image file, and all of its variations, by name."""
    if not name:
        return

    field = LocationImage._meta.get_field('image')

    names = [
        field.attr_class.get_variation_name(name, variation)
        for variation in field.variations
    ]
    names.append(name)

    for file_name in names:
        try:
            default_storage.delete(file_name)
        except Exception:  # pragma: no cover
            logger.exception("Could not delete location image file '%s'", file_name)


def delete_image_files_on_commit(name: str):
    """Delete stored image files once the current transaction commits.

    If the transaction is rolled back the database row survives, so the
    file must survive too.
    """
    if name:
        transaction.on_commit(partial(delete_image_files, name))


@receiver(
    post_delete, sender=LocationImage, dispatch_uid='inventree_location_image_delete'
)
def location_image_deleted(sender, instance, **kwargs):
    """Remove the stored files when a LocationImage row is deleted.

    Runs for direct deletes, and for cascades from StockLocation.
    """
    delete_image_files_on_commit(instance.image.name)


def cleanup_orphans():
    """Remove images whose stock location no longer exists.

    These are left behind when a stock location is deleted while the plugin
    is inactive. Uploader references to deleted users are cleared as well.

    Returns:
        The number of orphaned images removed.
    """
    from django.contrib.auth import get_user_model
    from django.db.models import Exists, OuterRef

    from stock.models import StockLocation

    location_exists = Exists(StockLocation.objects.filter(pk=OuterRef('location_id')))
    orphans = LocationImage.objects.filter(~location_exists)

    # Delete one by one so that post_delete removes the stored files
    count = 0
    for orphan in orphans:
        orphan.delete()
        count += 1

    user_exists = Exists(get_user_model().objects.filter(pk=OuterRef('uploaded_by_id')))
    LocationImage.objects.filter(uploaded_by_id__isnull=False).filter(
        ~user_exists
    ).update(uploaded_by=None)

    if count:
        logger.info('Removed %s orphaned stock location images', count)

    return count
