// Get single webtoon metadata
export async function onRequest(context) {
  const { env, params } = context;
  const { id } = params;

  try {
    const metaObj = await env.WEBTOONS_BUCKET.get(`${id}/webtoon.json`);

    if (!metaObj) {
      return new Response(JSON.stringify({ error: 'Webtoon not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const meta = await metaObj.json();

    return new Response(JSON.stringify({
      id: id,
      title: meta.title,
      description: meta.description,
      premise: meta.premise,
      genre: meta.genre,
      tags: meta.tags,
      style: meta.style,
      characters: meta.characters,
      chapters: meta.chapters
    }), {
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
