# inventree-location-image

An [InvenTree](https://inventree.org) plugin that lets you upload and view an image for each stock location, such as a photo of a shelf, rack or bin.

It is a workaround for [InvenTree issue #9843](https://github.com/inventree/InvenTree/issues/9843). It does not change the core `StockLocation` model. Images are kept in the plugin's own table.

## Features

- An **Image** panel on every stock location detail page. It shows the current image, which opens full size in a new tab.
- An **Image** button in the page header of every stock location. It opens the same view in a dialog, so you can see the image without leaving *Location Details* or any other panel. Needs InvenTree 1.4 or newer.
- Upload, replace and remove buttons for users with the `stock_location` **change** role.
- Users with the **view** role see the image only.
- A thumbnail (128 px) and a preview (256 px) are generated for each image.
- When an image is replaced or removed, or its stock location is deleted, the stored files are removed too. This happens only once the database change commits, so a rolled-back change never loses its file.
- Only raster formats are accepted: PNG, JPEG, GIF, WebP, BMP and TIFF. The format is read from the file contents with Pillow, not taken from the extension. SVG is rejected because it can carry scripts, and EPS because Pillow would run Ghostscript on it.
- Images larger than 50 megapixels are rejected, because generating thumbnails decodes the full image into memory.
- The maximum upload size can be set in the plugin settings (default 10 MB).

## Requirements

- InvenTree 1.0 or newer (`MIN_VERSION`). The header button needs InvenTree 1.4 or newer; older versions show only the panel. So far it has only been tested on 1.8 (development).
- No extra Python packages. The plugin uses Django, Django REST Framework and django-stdimage, which InvenTree already provides.

## Installation

1. Install the package into the InvenTree Python environment:

   ```bash
   pip install git+https://github.com/glompos21/inventree-location-image.git
   # or, for development
   pip install -e /path/to/inventree-location-image
   ```

   You can also install it from the web interface under *Admin Center → Plugins → Install Plugin*. Fill in both fields:

   | Field | Value |
   |---|---|
   | Package Name | `inventree-location-image` |
   | Source URL | `git+https://github.com/glompos21/inventree-location-image.git` |

   The Source URL needs the `git+` prefix. Without it, InvenTree treats the URL as a package index and the install fails, for example with `You must give at least one requirement to install`. Fill in the Package Name too: InvenTree uses it to add the plugin to `plugins.txt`, so the plugin is reinstalled when the server is rebuilt (for example, a Docker image update).

2. In **Admin Center → Plugin Settings**, enable all three of these:
   - **Enable URL integration**, for the plugin's API endpoint
   - **Enable app integration**, for the plugin's database table
   - **Enable interface integration**, for the panel and the header button

3. Activate the **LocationImage** plugin in **Admin Center → Plugins**.

4. Restart the server and the background worker, then apply the migration and collect the static files:

   ```bash
   invoke migrate      # applies inventree_location_image.0001_initial
   invoke static       # copies the panel JavaScript into the static directory
   ```

   In Docker, run `docker compose run --rm inventree-server invoke update` instead.

5. Open any stock location. A new **Image** panel appears in its sidebar, and an **Image** button in its page header.

If a setting from step 2 is missing, the panel tells you which one.

## Settings

| Setting | Default | Description |
|---|---|---|
| Maximum image size (MB) | 10 | The largest image file that can be uploaded |

## API

All endpoints use the `stock_location` role: **view** to read, **change** to upload or remove. Plugin URLs are outside `/api/`, so they accept session or token authentication, but not HTTP basic auth.

| Method | URL | Description |
|---|---|---|
| `GET` | `/plugin/locationimage/location/<pk>/` | Image URLs for the location. Returns 404 if the location has no image. |
| `POST` | `/plugin/locationimage/location/<pk>/` | Upload or replace the image (multipart field `image`). Returns 201 when created, 200 when replaced. |
| `DELETE` | `/plugin/locationimage/location/<pk>/` | Remove the image. Returns 204. |

Example:

```bash
TOKEN=$(curl -s -u user:password "https://inventree.example.com/api/user/token/" | jq -r .token)

curl -H "Authorization: Token $TOKEN" \
     -F "image=@shelf.jpg" \
     https://inventree.example.com/plugin/locationimage/location/12/
```

Response:

```json
{
  "pk": 1,
  "location": 12,
  "uploaded_by": 3,
  "updated": "2026-11-08 22:19",
  "image": "/media/location_images/location_12_5e165c94.jpg",
  "thumbnail": "/media/location_images/location_12_5e165c94.thumbnail.jpg",
  "preview": "/media/location_images/location_12_5e165c94.preview.jpg"
}
```

## Deactivating and uninstalling

Stock locations can still be deleted while the plugin is deactivated. Their images stay in the database until the plugin is next loaded, then they are removed automatically along with their files.

To remove the plugin and all of its images:

1. With the plugin still active, delete the images, either one by one or in *Admin → Location Images*. Deleting them here also removes their files.
2. Drop the plugin's table: `python manage.py migrate inventree_location_image zero`
3. Deactivate the plugin and uninstall the package (`pip uninstall inventree-location-image`).
4. If you skipped step 1, delete the leftover files in `<media>/location_images/` by hand.

## Limitations

Because this is a plugin and not a core change:

- The image appears in its own panel and in a dialog opened from the page header, not inside the stock location's *Location Details* panel. Plugins cannot add fields to core detail panels.
- It is not shown in the location table or tree, or in search results.
- It is not part of the core `/api/stock/location/` serializer, and report templates can't access it directly.
- Images are not included in InvenTree's data export or import. They are included in database and media backups.

If the core image work tracked in [#9788](https://github.com/inventree/InvenTree/issues/9788) is merged, stock location images may become a core feature. You would then need to move existing images across from this plugin.

## Development

Run the tests from the InvenTree backend directory, with this package installed in the same environment:

```bash
cd InvenTree/src/backend/InvenTree
INVENTREE_PLUGIN_TESTING_SETUP=True python manage.py test inventree_location_image
```

The panel is plain JavaScript (`inventree_location_image/static/location_image_panel.js`), so it needs no build step.

## License

MIT
