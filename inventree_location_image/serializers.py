"""API serializers for the stock location image plugin.

Note: this module imports the plugin models, so it must only be imported
lazily (inside view methods), after the plugin app has been registered.
"""

from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers

from .models import ALLOWED_EXTENSIONS, LocationImage

MEGABYTE = 1024 * 1024

# Formats as reported by Pillow. The extension alone is not enough: a
# PostScript (EPS) file named 'x.png' would otherwise be decoded via Ghostscript.
# MPO is how Pillow opens many phone camera JPEGs.
ALLOWED_FORMATS = {'BMP', 'GIF', 'JPEG', 'MPO', 'PNG', 'TIFF', 'WEBP'}

# Upper limit on image dimensions. Thumbnail generation decodes the full
# bitmap, so a small but highly compressed file could otherwise use a lot of
# memory. 50 megapixels covers current phone and camera photos.
MAX_PIXELS = 50_000_000


def image_urls(image) -> dict:
    """Return the media URLs of an image and its variations.

    Built from the storage backend directly (instead of InvenTree helpers,
    whose signature differs between InvenTree versions).
    """
    if not image:
        return {'image': None, 'thumbnail': None, 'preview': None}

    storage = image.storage
    name = image.name
    get_variation_name = image.field.attr_class.get_variation_name

    return {
        'image': storage.url(name),
        'thumbnail': storage.url(get_variation_name(name, 'thumbnail')),
        'preview': storage.url(get_variation_name(name, 'preview')),
    }


class LocationImageSerializer(serializers.ModelSerializer):
    """Serializer for a stock location image.

    Input: 'image' is an uploaded file.
    Output: 'image', 'thumbnail' and 'preview' are media URLs.

    Pass 'max_size' (in bytes) in the serializer context to limit upload size.
    """

    class Meta:
        """Serializer options."""

        model = LocationImage
        fields = ['pk', 'location', 'image', 'uploaded_by', 'updated']
        read_only_fields = ['pk', 'location', 'uploaded_by', 'updated']

    image = serializers.ImageField(
        write_only=True,
        allow_empty_file=False,
        validators=[FileExtensionValidator(ALLOWED_EXTENSIONS)],
        label=_('Image'),
    )

    def validate_image(self, value):
        """Check the image size, format and dimensions."""
        max_size = self.context.get('max_size')

        if max_size and value.size > max_size:
            raise serializers.ValidationError(
                _('Image is too large (maximum size is {size} MB)').format(
                    size=max_size // MEGABYTE
                )
            )

        # Set by Django's image validation; reading these does not decode the image
        img = getattr(value, 'image', None)

        if img is None or img.format not in ALLOWED_FORMATS:
            raise serializers.ValidationError(
                _('Unsupported image format. Use PNG, JPEG, GIF, WebP, BMP or TIFF.')
            )

        if img.width * img.height > MAX_PIXELS:
            raise serializers.ValidationError(
                _('Image dimensions are too large (maximum is {mp} megapixels)').format(
                    mp=MAX_PIXELS // 1_000_000
                )
            )

        return value

    def to_representation(self, instance):
        """Return media URLs for the image and its variations."""
        data = super().to_representation(instance)
        data.update(image_urls(instance.image))
        return data
