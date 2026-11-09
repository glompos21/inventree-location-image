/**
 * Stock location image panel for the InvenTree "LocationImage" plugin.
 *
 * Loaded by the InvenTree frontend as a plugin panel on the stock location
 * detail page. Plain JavaScript, so no build step is needed.
 *
 * Server context (from LocationImagePlugin.get_ui_panels):
 *   api_url      API endpoint for this location's image
 *   can_edit     True if the user may upload / remove the image
 *   max_size_mb  Maximum upload size in MB
 *   error        Configuration problem to show instead of the panel
 */

const ACCEPTED_TYPES =
  'image/png,image/jpeg,image/gif,image/webp,image/bmp,image/tiff';

const COLORS = {
  dimmed: 'var(--mantine-color-dimmed, #868e96)',
  error: 'var(--mantine-color-red-text, #e03131)',
  success: 'var(--mantine-color-green-text, #2f9e44)',
  border: 'var(--mantine-color-default-border, #dee2e6)',
  primary: 'var(--mantine-color-blue-filled, #228be6)',
  onPrimary: 'var(--mantine-color-white, #fff)'
};

const BUTTON_BASE = {
  font: 'inherit',
  fontSize: '14px',
  padding: '6px 14px',
  borderRadius: 'var(--mantine-radius-sm, 4px)',
  cursor: 'pointer'
};

/** Create a DOM element. Text children are always added as text, never HTML. */
function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);

  for (const [key, value] of Object.entries(props)) {
    if (key === 'style') {
      Object.assign(node.style, value);
    } else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value !== undefined && value !== null && value !== false) {
      node.setAttribute(key, value === true ? '' : String(value));
    }
  }

  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(
      typeof child === 'string' ? document.createTextNode(child) : child
    );
  }

  return node;
}

/** Resolve a (possibly relative) media URL against the InvenTree server host. */
function absoluteUrl(url, host) {
  if (!url) return '';

  try {
    return new URL(url, host || window.location.origin).toString();
  } catch {
    return url;
  }
}

/** Extract a readable message from an axios error. */
function errorMessage(error) {
  const data = error?.response?.data;

  if (data && typeof data === 'object') {
    for (const key of ['image', 'detail', 'non_field_errors']) {
      if (data[key]) return [].concat(data[key]).join(' ');
    }
  }

  if (error?.response?.status === 403) {
    return 'You do not have permission to do this.';
  }

  return error?.message || 'Request failed.';
}

function button(label, variant, onClick) {
  const style =
    variant === 'danger'
      ? {
          ...BUTTON_BASE,
          background: 'transparent',
          color: COLORS.error,
          border: `1px solid ${COLORS.error}`
        }
      : {
          ...BUTTON_BASE,
          background: COLORS.primary,
          color: COLORS.onPrimary,
          border: `1px solid ${COLORS.primary}`
        };

  return el('button', { type: 'button', style, onClick }, label);
}

// The frontend calls the render function again whenever its context changes
// (e.g. the location is reloaded), possibly while an upload is still running.
// Track the pending change per panel container, so that a new render waits
// for it before loading the image.
const pendingChanges = new WeakMap();

export function renderLocationImagePanel(target, data) {
  if (!target) {
    console.error('LocationImage: no target provided to panel');
    return;
  }

  const ctx = data?.context ?? {};
  const api = data?.api;

  const root = el('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '12px' }
  });
  target.replaceChildren(root);

  if (ctx.error || !ctx.api_url || !api) {
    root.append(
      el(
        'p',
        { style: { color: COLORS.error, margin: 0 } },
        ctx.error || 'Location image plugin is not configured correctly.'
      )
    );
    return;
  }

  const imageArea = el('div');
  const controls = el('div', {
    style: {
      display: 'flex',
      gap: '8px',
      flexWrap: 'wrap',
      alignItems: 'center'
    }
  });
  const status = el('p', {
    role: 'status',
    'aria-live': 'polite',
    style: { margin: 0, fontSize: '14px' }
  });

  root.append(imageArea, controls, status);

  const fileInput = el('input', {
    type: 'file',
    accept: ACCEPTED_TYPES,
    style: { display: 'none' }
  });

  let current = null; // Image data from the API, or null if there is no image
  let busy = false;

  function setStatus(text, kind) {
    status.textContent = text || '';
    status.style.color =
      kind === 'error'
        ? COLORS.error
        : kind === 'success'
          ? COLORS.success
          : COLORS.dimmed;
  }

  function renderImage() {
    imageArea.replaceChildren();

    if (!current) {
      imageArea.append(
        el(
          'p',
          { style: { color: COLORS.dimmed, margin: 0 } },
          'No image uploaded for this location.'
        )
      );
      return;
    }

    const fullUrl = absoluteUrl(current.image, data.host);

    imageArea.append(
      el(
        'a',
        {
          href: fullUrl,
          target: '_blank',
          rel: 'noopener noreferrer',
          title: 'Open full size image'
        },
        el('img', {
          src: fullUrl,
          alt: 'Stock location image',
          style: {
            display: 'block',
            maxWidth: '100%',
            maxHeight: '480px',
            objectFit: 'contain',
            border: `1px solid ${COLORS.border}`,
            borderRadius: 'var(--mantine-radius-sm, 4px)'
          }
        })
      )
    );

    if (current.updated) {
      imageArea.append(
        el(
          'p',
          { style: { color: COLORS.dimmed, fontSize: '12px', margin: '4px 0 0' } },
          // Shown as sent: the server's date format is not ISO 8601, so
          // Date() parsing differs between browsers
          `Updated ${current.updated}`
        )
      );
    }
  }

  function renderControls() {
    controls.replaceChildren();

    if (!ctx.can_edit) return;

    const upload = button(
      current ? 'Replace image' : 'Upload image',
      'primary',
      () => fileInput.click()
    );
    upload.disabled = busy;
    controls.append(upload);

    if (current) {
      const remove = button('Remove image', 'danger', removeImage);
      remove.disabled = busy;
      controls.append(remove);
    }

    controls.append(
      el(
        'span',
        { style: { color: COLORS.dimmed, fontSize: '12px' } },
        `Max ${ctx.max_size_mb} MB`
      ),
      fileInput
    );
  }

  // False once this render has been replaced by a newer one
  const isCurrent = () => root.isConnected;

  function render() {
    if (!isCurrent()) return;
    renderImage();
    renderControls();
  }

  function run(request, successText) {
    busy = true;
    renderControls();
    setStatus('Working…');

    const change = request
      .then(() => isCurrent() && setStatus(successText, 'success'))
      .catch((error) => isCurrent() && setStatus(errorMessage(error), 'error'))
      .finally(() => {
        busy = false;
        fileInput.value = '';
        render();
      });

    pendingChanges.set(target, change);
    return change;
  }

  function uploadImage(file) {
    if (ctx.max_size_mb && file.size > ctx.max_size_mb * 1024 * 1024) {
      setStatus(`Image is too large (maximum size is ${ctx.max_size_mb} MB)`, 'error');
      fileInput.value = '';
      return;
    }

    const form = new FormData();
    form.append('image', file, file.name);

    run(
      api.post(ctx.api_url, form).then((response) => {
        current = response.data;
      }),
      'Image uploaded.'
    );
  }

  function removeImage() {
    if (!window.confirm('Remove the image for this location?')) return;

    run(
      api.delete(ctx.api_url).then(() => {
        current = null;
      }),
      'Image removed.'
    );
  }

  fileInput.addEventListener('change', () => {
    const file = fileInput.files?.[0];
    if (file) uploadImage(file);
  });

  setStatus('Loading…');

  // Wait for any change started by a previous render of this panel
  Promise.resolve(pendingChanges.get(target))
    .then(() => api.get(ctx.api_url))
    .then((response) => {
      current = response.data;
      if (isCurrent()) setStatus('');
    })
    .catch((error) => {
      current = null;

      if (!isCurrent()) return;

      if (error?.response?.status === 404) {
        setStatus('');
      } else {
        setStatus(errorMessage(error), 'error');
      }
    })
    .finally(render);
}
