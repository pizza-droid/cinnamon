const { makeProviders, makeTargetFilter, targetLanguages } = require('@movie-web/providers');

const providers = makeProviders({
  targetLanguage: targetLanguages.ENGLISH,
  fetcher: (url, options) => fetch(url, options).then(r => r.text()),
  targetFilter: makeTargetFilter({

  }),
});

const tmdbId = process.argv[2];
const season = parseInt(process.argv[3]);
const episode = parseInt(process.argv[4]);

async function main() {
  try {
    const result = await providers.queryMedia({
      type: 'show',
      title: '',
      tmdbId: tmdbId,
      season: { number: season },
      episode: { number: episode },
    });
    console.log(JSON.stringify(result, null, 2));
  } catch (e) {
    console.error('Error:', e.message);
    process.exit(1);
  }
}

main();
