// Serve images from R2
export async function onRequest(context) {
  const { env, params } = context;
  // [[path]] returns an array in Pages Functions, join with /
  const imagePath = Array.isArray(params.path) ? params.path.join('/') : params.path;

  try {
    const object = await env.WEBTOONS_BUCKET.get(imagePath);

    if (!object) {
      return new Response('Image not found', { status: 404 });
    }

    // Determine content type
    let contentType = 'image/jpeg';
    if (imagePath.endsWith('.png')) {
      contentType = 'image/png';
    } else if (imagePath.endsWith('.webp')) {
      contentType = 'image/webp';
    } else if (imagePath.endsWith('.gif')) {
      contentType = 'image/gif';
    }

    return new Response(object.body, {
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'public, max-age=31536000',
        'Access-Control-Allow-Origin': '*'
      }
    });
  } catch (error) {
    return new Response(`Error: ${error.message}`, { status: 500 });
  }
}
