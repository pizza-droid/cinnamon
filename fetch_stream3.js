const p = require('@movie-web/providers');

function createFetcher(fetchFn) {
  return async (url, ops) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);

    try {
      const fullUrl = ops.baseUrl ? new URL(url, ops.baseUrl).toString() : url;
      const headers = { ...ops.headers };
      let body = ops.body;

      let queryStr = '';
      if (ops.query && Object.keys(ops.query).length) {
        const params = new URLSearchParams(ops.query);
        queryStr = '?' + params.toString();
      }

      const resp = await fetchFn(fullUrl + queryStr, {
        method: ops.method || 'GET',
        headers,
        body: typeof body === 'object' ? JSON.stringify(body) : body,
        signal: controller.signal,
      });

      clearTimeout(timeout);

      const text = await resp.text();

      return {
        statusCode: resp.status,
        headers: resp.headers,
        finalUrl: resp.url,
        body: text,
      };
    } catch (e) {
      clearTimeout(timeout);
      throw e;
    }
  };
}

async function main() {
  const showTmdbId = '79744';
  const seasonNum = 1;
  const episodeNum = 1;

  // Get episode TMDB ID with longer timeout
  let seasonTmdbId = '36203';
  let episodeTmdbId = '36204';
  try {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 10000);
    const resp = await fetch(
      `https://api.themoviedb.org/3/tv/${showTmdbId}/season/${seasonNum}/episode/${episodeNum}?api_key=process.env.TMDB_API_KEY`,
      { signal: controller.signal }
    );
    const data = await resp.json();
    if (data.id) episodeTmdbId = String(data.id);
    console.log('Got episode tmdbId:', episodeTmdbId);

    const resp2 = await fetch(
      `https://api.themoviedb.org/3/tv/${showTmdbId}/season/${seasonNum}?api_key=process.env.TMDB_API_KEY`,
      { signal: controller.signal }
    );
    const data2 = await resp2.json();
    if (data2.id) seasonTmdbId = String(data2.id);
    console.log('Got season tmdbId:', seasonTmdbId);
  } catch (e) {
    console.log('Using fallback tmdbIds:', e.message);
  }

  const r = p.buildProviders()
    .setTarget(p.targets.NATIVE)
    .setFetcher(createFetcher((url, opts) => fetch(url, opts)))
    .addBuiltinProviders()
    .build();

  const media = {
    type: 'show',
    title: 'The Rookie',
    tmdbId: showTmdbId,
    season: { number: seasonNum, tmdbId: seasonTmdbId },
    episode: { number: episodeNum, tmdbId: episodeTmdbId },
  };

  // Try sources one by one
  const sources = r.listSources().filter(s => s.mediaTypes.includes('show'));

  for (const src of sources) {
    try {
      console.log(`\n=== ${src.name} (${src.id}) ===`);
      const srcResult = await r.runSourceScraper({ id: src.id, media });

      if (srcResult?.embeds?.length) {
        for (const emb of srcResult.embeds.slice(0, 3)) {
          console.log(`  Embed: ${emb.embedId} -> ${emb.url.slice(0, 120)}`);

          try {
            const embResult = await r.runEmbedScraper({ id: emb.embedId, url: emb.url });
            if (embResult?.stream?.length) {
              for (const s of embResult.stream) {
                if (s.type === 'hls') {
                  console.log(`  >>> HLS: ${s.playlist}`);
                } else if (s.type === 'file') {
                  for (const [q, f] of Object.entries(s.qualities)) {
                    console.log(`  >>> ${q}: ${f.url}`);
                  }
                }
              }
              console.log('\n*** SUCCESS! Found working stream ***\n');
              return;
            } else {
              console.log(`  No stream`);
            }
          } catch (e) {
            console.log(`  Embed error: ${e.message?.slice(0, 100)}`);
          }
        }
      } else if (srcResult?.stream?.length) {
        for (const s of srcResult.stream) {
          if (s.type === 'hls') console.log(`  >>> HLS: ${s.playlist}`);
          else if (s.type === 'file') {
            for (const [q, f] of Object.entries(s.qualities)) {
              console.log(`  >>> ${q}: ${f.url}`);
            }
          }
        }
      } else {
        console.log(`  No result`);
      }
    } catch (e) {
      console.log(`  Error: ${e.message?.slice(0, 100)}`);
    }
  }
}

main();
