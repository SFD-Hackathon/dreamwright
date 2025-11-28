// List all webtoons from R2
export async function onRequest(context) {
  const { env } = context;

  try {
    // List objects at root level to find webtoon directories
    const listed = await env.WEBTOONS_BUCKET.list({ delimiter: '/' });

    const webtoons = [];

    for (const prefix of listed.delimitedPrefixes || []) {
      const webtoonId = prefix.replace('/', '');

      // Try to get webtoon.json for metadata
      const metaObj = await env.WEBTOONS_BUCKET.get(`${webtoonId}/webtoon.json`);

      if (metaObj) {
        const meta = await metaObj.json();
        webtoons.push({
          id: webtoonId,
          title: meta.title || webtoonId,
          description: meta.description || '',
          premise: meta.premise || '',
          genre: meta.genre || '',
          tags: meta.tags || [],
          cover: `/api/image/${webtoonId}/assets/covers/series_cover.jpg`,
          chapters: (meta.chapters || []).map((ch, idx) => ({
            number: idx + 1,
            title: ch.title || `Chapter ${idx + 1}`,
            summary: ch.summary || ''
          }))
        });
      }
    }

    return new Response(JSON.stringify(webtoons), {
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
