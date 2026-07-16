import WebTorrent from 'webtorrent';

const magnet = process.argv[2];
const port = parseInt(process.argv[3]) || 0;
const dhtPort = port ? port + 1 : 0;
const torrentPort = port ? port + 2 : 0;

const client = new WebTorrent({ dht: true, dhtPort, torrentPort });

let torrent = null;
let server = null;

function log(msg) {
  process.stdout.write(JSON.stringify(msg) + '\n');
}

client.on('warning', e => log({ type: 'warn', msg: e.message }));
client.on('error', e => log({ type: 'error', msg: e.message }));

async function waitForDHT(timeout = 30000) {
  const start = Date.now();
  return new Promise((resolve) => {
    const check = () => {
      if (!client.dht) { setTimeout(check, 500); return; }
      const nodes = client.dht.nodes ? client.dht.nodes.toArray().length : 0;
      if (client.dht.ready && nodes >= 1) {
        resolve();
      } else if (Date.now() - start > timeout) {
        resolve(); // proceed anyway
      } else {
        setTimeout(check, 500);
      }
    };
    check();
  });
}

async function main() {
  log({ status: 'dht_bootstrapping' });

  // The DHT from a cold start needs ~5-10s to bootstrap.
  // Do an initial lookup to speed bootstrap.
  if (client.dht) {
    client.dht.on('node', n => {
      // nodes being discovered — progress
    });
  }

  await waitForDHT(25000);

  // Get the actual listening port if we used 0
  const actualDhtPort = client.dht && client.dht.address ? client.dht.address().port : dhtPort;
  log({ status: 'dht_ready', nodes: client.dht ? client.dht.nodes.toArray().length : 0, port: actualDhtPort });

  log({ status: 'adding_torrent' });
  torrent = client.add(magnet);

  await new Promise((resolve, reject) => {
    torrent.on('metadata', resolve);
    torrent.on('error', reject);
    torrent.on('warning', e => log({ type: 'warn', msg: e.message }));
  });

  const file = torrent.files[0];
  log({
    status: 'metadata',
    name: torrent.name,
    infoHash: torrent.infoHash,
    files: torrent.files.map(f => ({ name: f.name, length: f.length })),
  });

  // Create HTTP server
  const usePort = port || (torrentPort || 0);
  server = client.createServer({ pathname: '/' });
  server.listen(usePort, () => {
    const addr = server.address();
    const streamUrl = `http://127.0.0.1:${addr.port}/${torrent.infoHash}/${file.name}`;
    log({
      status: 'ready',
      streamUrl,
      port: addr.port,
      infoHash: torrent.infoHash,
      file: file.name,
      length: file.length,
    });
  });
}

main().catch(e => {
  log({ type: 'fatal', msg: e.message });
  process.exit(1);
});

// Keep alive and report progress
setInterval(() => {
  if (torrent && !torrent.destroyed) {
    log({
      status: 'progress',
      progress: torrent.progress,
      downloaded: torrent.downloaded,
      downloadSpeed: torrent.downloadSpeed,
      uploadSpeed: torrent.uploadSpeed,
      numPeers: torrent.numPeers,
    });
  }
}, 5000);

process.on('SIGINT', () => {
  if (server) server.close();
  client.destroy(() => process.exit(0));
});
