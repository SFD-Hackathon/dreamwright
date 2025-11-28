// Get chapter segments for reading
export async function onRequest(context) {
  const { env, params } = context;
  // [[path]] returns an array in Pages Functions
  const pathParts = Array.isArray(params.path) ? params.path : params.path.split('/');

  // Expected: webtoonId/chapterNum
  if (pathParts.length < 2) {
    return new Response(JSON.stringify({ error: 'Invalid path' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  const webtoonId = pathParts[0];
  const chapterNum = parseInt(pathParts[1]);

  try {
    // Get webtoon metadata
    const metaObj = await env.WEBTOONS_BUCKET.get(`${webtoonId}/webtoon.json`);

    if (!metaObj) {
      return new Response(JSON.stringify({ error: 'Webtoon not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const meta = await metaObj.json();
    const chapter = meta.chapters?.[chapterNum - 1];

    if (!chapter) {
      return new Response(JSON.stringify({ error: 'Chapter not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Collect all segments first
    const segmentData = [];
    for (const scene of chapter.scenes || []) {
      for (const segment of scene.segments || []) {
        segmentData.push({ segment, scene });
      }
    }

    // Check all images in parallel for speed (try both .png and .jpg)
    const imageChecks = await Promise.all(
      segmentData.map(async ({ segment }) => {
        const pngPath = `${webtoonId}/assets/chapters/ch${chapterNum}/${segment.id}.png`;
        const jpgPath = `${webtoonId}/assets/chapters/ch${chapterNum}/${segment.id}.jpg`;
        const pngObj = await env.WEBTOONS_BUCKET.head(pngPath);
        if (pngObj) {
          return { id: segment.id, exists: true, path: pngPath };
        }
        const jpgObj = await env.WEBTOONS_BUCKET.head(jpgPath);
        return { id: segment.id, exists: !!jpgObj, path: jpgPath };
      })
    );

    // Create lookup map
    const imageMap = new Map(imageChecks.map(c => [c.id, c]));

    // Build segments with image info
    const segments = segmentData.map(({ segment, scene }) => {
      const imgInfo = imageMap.get(segment.id);
      return {
        id: segment.id,
        sequence: segment.sequence,
        type: segment.segment_type,
        description: segment.description,
        characters: segment.characters,
        dialogues: segment.dialogues,
        narration: segment.narration,
        sfx: segment.sfx,
        shot_type: segment.shot_type,
        mood: segment.mood,
        scroll_pacing: segment.scroll_pacing,
        height_hint: segment.height_hint,
        scene_id: scene.id,
        scene_title: scene.title,
        image_url: imgInfo?.exists ? `/api/image/${imgInfo.path}` : null,
        has_image: imgInfo?.exists || false
      };
    });

    return new Response(JSON.stringify({
      webtoon_id: webtoonId,
      webtoon_title: meta.title,
      chapter_number: chapterNum,
      chapter_title: chapter.title,
      chapter_summary: chapter.summary,
      total_chapters: meta.chapters?.length || 0,
      segments: segments
    }), {
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'public, max-age=300'
      }
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
