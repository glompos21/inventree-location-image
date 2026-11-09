"""API views for the stock location image plugin.

The plugin models are imported inside the view methods, not at module level:
UrlsMixin loads this module when the plugin is created, which can happen
before AppMixin has registered the plugin app with Django.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from InvenTree.permissions import RolePermission
from stock.models import StockLocation


class LocationImageView(APIView):
    """Read, upload, replace or remove the image for one stock location.

    - GET: Return the image URLs (404 if the location has no image)
    - POST: Upload an image (multipart field 'image'), replacing any existing one
    - DELETE: Remove the image

    Access uses the 'stock_location' role: 'view' to read, 'change' to modify.
    """

    # Set by LocationImagePlugin.setup_urls via as_view(plugin=...)
    plugin = None

    permission_classes = [permissions.IsAuthenticated, RolePermission]
    role_required = 'stock_location'
    # Changing a location's image counts as editing the location.
    # HEAD is listed because InvenTree's default map has no entry for it.
    rolemap = {'HEAD': 'view', 'POST': 'change', 'PUT': 'change', 'DELETE': 'change'}
    parser_classes = [MultiPartParser, FormParser]

    def get_serializer_context(self):
        """Context passed to the serializer."""
        return {
            'request': self.request,
            'max_size': self.plugin.max_image_size() if self.plugin else None,
        }

    def get(self, request, pk):
        """Return the image for this stock location."""
        from .models import LocationImage
        from .serializers import LocationImageSerializer

        location = get_object_or_404(StockLocation, pk=pk)
        instance = get_object_or_404(LocationImage, location=location)

        return Response(
            LocationImageSerializer(
                instance, context=self.get_serializer_context()
            ).data
        )

    def post(self, request, pk):
        """Upload a new image for this stock location, replacing any existing one."""
        from .models import LocationImage, delete_image_files_on_commit
        from .serializers import LocationImageSerializer

        with transaction.atomic():
            # Locking the location serializes concurrent uploads for it
            location = get_object_or_404(
                StockLocation.objects.select_for_update(), pk=pk
            )
            instance = LocationImage.objects.filter(location=location).first()
            old_name = instance.image.name if instance else None

            serializer = LocationImageSerializer(
                instance, data=request.data, context=self.get_serializer_context()
            )
            serializer.is_valid(raise_exception=True)
            saved = serializer.save(location=location, uploaded_by=request.user)

            # Remove the replaced file only once the new one is committed
            if old_name and old_name != saved.image.name:
                delete_image_files_on_commit(old_name)

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if instance is None else status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        """Remove the image for this stock location."""
        from .models import LocationImage

        with transaction.atomic():
            location = get_object_or_404(
                StockLocation.objects.select_for_update(), pk=pk
            )
            instance = get_object_or_404(LocationImage, location=location)

            # The post_delete handler removes the stored files after commit
            instance.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)
