const p = require('@movie-web/providers');

// TMDB API to get episode and season tmdbIds
async function getTmdbIds(tmdbId, seasonNum, episodeNum) {
  const base = 'https://api.themoviedb.org/3';
  const key = process.env.TMDB_API_KEY;
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), 8000);

  const [seasonResp, episodeResp] = await Promise.all([
    fetch(`${base}/tv/${tmdbId}/season/${seasonNum}?api_key=${key}`, { signal: controller.signal }).then(r => r.json()),
    fetch(`${base}/tv/${tmdbId}/season/${seasonNum}/episode/${episodeNum}?api_key=${key}`, { signal: controller.signal }).then(r => r.json()),
  ]);

  clearTimeout(t);

  return {
    seasonTmdbId: String(seasonResp.id || tmdbId),
    episodeTmdbId: String(episodeResp.id || tmdbId),
  };
}

async function main() {
  const showTmdbId = '79744';
  const seasonNum = 1;
  const episodeNum = 1;

  // Get actual tmdbIds for season and episode
  let seasonTmdbId = showTmdbId;
  let episodeTmdbId = showTmdbId;
  try {
    const ids = await getTmdbIds(showTmdbId, seasonNum, episodeNum);
    seasonTmdbId = ids.seasonTmdbId;
    episodeTmdbId = ids.episodeTmdbId;
    console.log('seasonTmdbId:', seasonTmdbId, 'episodeTmdbId:', episodeTmdbId);
  } catch (e) {
    console.log('Failed to get TMDB IDs:', e.message);
  }

  // Create providers
  const r = p.buildProviders()
    .setTarget(p.targets.NATIVE)
    .setFetcher(p.makeStandardFetcher((url, opts) => {
      const controller = new AbortController();
      setTimeout(() => controller.abort(), 10000);
      return fetch(url, { ...opts, signal: controller.signal });
    }))
    .addBuiltinProviders()
    .build();

  const media = {
    type: 'show',
    title: 'The Rookie',
    tmdbId: showTmdbId,
    season: { number: seasonNum, tmdbId: seasonTmdbId },
    episode: { number: episodeNum, tmdbId: episodeTmdbId },
  };

  // Try specific sources known to work for shows
  const sourceIds = ['8stream', 'streambox', 'm4ufree', 'catflix', 'nites'];

  for (const sourceId of sourceIds) {
    try {
      const controller = new AbortController();
      setTimeout(() => controller.abort(), 15000);

      console.log(`\n=== Trying source: ${sourceId} ===`);
      const srcResult = await r.runSourceScraper({
        id: sourceId,
        media,
        signal: controller.signal,
      });

      if (srcResult?.embeds?.length) {
        console.log(`  Embeds found: ${srcResult.embeds.length}`);
        for (const emb of srcResult.embeds.slice(0, 3)) {
          console.log(`    ${emb.embedId}: ${emb.url.slice(0, 100)}`);
        }

        // Try to scrape the first embed
        const firstEmbed = srcResult.embeds[0];
        try {
          const embController = new AbortController();
          setTimeout(() => embController.abort(), 15000);

          const embResult = await r.runEmbedScraper({
            id: firstEmbed.embedId,
            url: firstEmbed.url,
            signal: embController.signal,
          });

          if (embResult?.stream?.length) {
            console.log(`  Stream found via ${firstEmbed.embedId}!`);
            for (const s of embResult.stream) {
              if (s.type === 'hls') {
                console.log(`    HLS playlist: ${s.playlist?.slice(0, 150)}`);
              } else if (s.type === 'file') {
                for (const [q, f] of Object.entries(s.qualities)) {
                  console.log(`    ${q}: ${f.url?.slice(0, 150)}`);
                }
              }
            }
          } else {
            console.log(`  No stream from embed ${firstEmbed.embedId}`);
          }
        } catch (e) {
          console.log(`  Embed scrape error: ${e.message?.slice(0, 100)}`);
        }
      } else {
        console.log(`  No embeds found`);
      }
    } catch (e) {
      console.log(`  Error: ${e.message?.slice(0, 150)}`);
    }
  }
}

main();
