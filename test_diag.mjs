import WebTorrent from 'webtorrent';

const magnet = 'magnet:?xt=urn:btih:255e2890a1a724bcdd93b1120dd08a5a8e11b949';
const port = 12345;

const client = new WebTorrent({ dht: true, dhtPort: port + 1, torrentPort: port + 2 });

function dump(label) {
  const d = client.dht;
  if (!d) { console.log(label, 'no dht'); return; }
  const nodes = d.nodes ? (d.nodes.toArray ? d.nodes.toArray().length : '?') : '?';
  const bootstrap = d._rpc ? JSON.stringify(d._rpc.bootstrap) : 'no _rpc';
  console.log(`[${label}] ready=${d.ready} nodes=${nodes} listening=${d.listening} dhtPort=${client.dhtPort} bootstrap=${bootstrap}`);
}

client.on('error', e => console.error('Client error:', e.message));

setTimeout(() => {
  dump('after 3s (no torrent)');
  console.log('Adding torrent...');
  const torrent = client.add(magnet);
  torrent.on('warning', e => console.warn('Torrent warning:', e.message));
  torrent.on('error', e => console.error('Torrent error:', e.message));
  torrent.on('metadata', () => {
    console.log('METADATA RECEIVED, name=', torrent.name);
    process.exit(0);
  });
  setTimeout(() => dump('after add +2s'), 2000);
  setTimeout(() => dump('after add +10s'), 10000);
  setTimeout(() => { dump('final'); process.exit(0); }, 30000);
}, 3000);
