import WebTorrent from 'webtorrent';
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

// === Self-patch k-rpc bootstrap nodes to use IPv4 (avoids silent IPv6 DNS resolution bug) ===
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const krpcPath = path.resolve(__dirname, '..', 'node_modules', 'k-rpc', 'index.js');
try {
  let krpcSrc = fs.readFileSync(krpcPath, 'utf8');
  const patched = krpcSrc.replace(
    /BOOTSTRAP_NODES\s*=\s*\[[\s\S]*?\]/,
    `BOOTSTRAP_NODES = [
  { host: '67.215.246.10', port: 6881 },
  { host: '82.221.103.244', port: 6881 },
  { host: '87.98.162.88', port: 6881 },
  { host: '212.129.33.59', port: 6881 },
  { host: '204.83.124.186', port: 6881 },
  { host: '185.19.93.52', port: 6881 }
]`
  );
  if (krpcSrc !== patched) {
    fs.writeFileSync(krpcPath, patched);
  }
} catch { /* k-rpc might not exist if running from a different cwd */ }

// === Parse CLI args ===
const magnet = process.argv[2];
const port = parseInt(process.argv[3]) || 0;
const dhtPort = port ? port + 1 : 0;
const torrentPort = port ? port + 2 : 0;

const selectSeason = process.argv[4] ? parseInt(process.argv[4]) : null;
const selectEpisode = process.argv[5] ? parseInt(process.argv[5]) : null;

const client = new WebTorrent({ dht: true, dhtPort, torrentPort });

function log(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

client.on('warning', e => log({ type: 'warn', msg: e.message }));
client.on('error', e => log({ type: 'error', msg: e.message }));

// === DHT bootstrap wait ===
async function waitForDHT(timeout = 30000) {
  const start = Date.now();
  return new Promise((resolve) => {
    const check = () => {
      if (!client.dht) { setTimeout(check, 500); return; }
      const nodes = client.dht.nodes ? client.dht._rpc.nodes.toArray().length : 0;
      if (client.dht.ready && nodes >= 1) {
        resolve();
      } else if (Date.now() - start > timeout) {
        resolve();
      } else {
        setTimeout(check, 500);
      }
    };
    check();
  });
}

async function waitForMoreNodes(minNodes = 16, timeout = 25000) {
  const start = Date.now();
  return new Promise((resolve) => {
    const check = async () => {
      if (!client.dht) { setTimeout(check, 500); return; }
      let nodes = client.dht._rpc.nodes.toArray().length;
      if (nodes >= minNodes) return resolve(nodes);
      if (Date.now() - start > timeout) return resolve(nodes);
      // If nodes are too few, force a lookup to populate routing table
      if (nodes < 8) {
        await new Promise(resolveClosest => {
          const t = crypto.randomBytes(20);
          client.dht._rpc.closest(t, { q: 'find_node', a: { id: client.dht._rpc.id, target: t } }, () => true, resolveClosest);
        });
        nodes = client.dht._rpc.nodes.toArray().length;
      }
      setTimeout(check, 1500);
    };
    check();
  });
}

async function ensureDHTLookup() {
  const randomTarget = crypto.randomBytes(20);
  return new Promise((resolve) => {
    client.dht.lookup(randomTarget, (err) => {
      const nodes = client.dht._rpc.nodes.toArray().length;
      resolve(nodes);
    });
  });
}

// === Select the correct file in a multi-file torrent ===
function selectFile(torrent, season, episode) {
  const pad = n => String(n).padStart(2, '0');
  const patterns = season != null && episode != null
    ? [
        new RegExp(`[Ss]${pad(season)}[Ee]${pad(episode)}`),
        new RegExp(`[Ss]${season}[Ee]${episode}`),
        new RegExp(`${season}x${pad(episode)}`),
        new RegExp(`Season[. ]${season}.*[Ee]pisode[. ]${episode}`, 'i'),
      ]
    : [];

  for (const file of torrent.files) {
    for (const pattern of patterns) {
      if (pattern.test(file.name)) return file;
    }
  }

  return torrent.files[0];
}

// === Main ===
async function main() {
  log({ status: 'dht_bootstrapping' });
  await waitForDHT(25000);
  let dhtNodes = client.dht ? client.dht._rpc.nodes.toArray().length : 0;

  // Force a DHT lookup to populate routing table with more nodes
  if (dhtNodes < 16) {
    await ensureDHTLookup();
    dhtNodes = client.dht ? client.dht._rpc.nodes.toArray().length : 0;
  }

  dhtNodes = await waitForMoreNodes(8, 15000);
  log({ status: 'dht_ready', nodes: dhtNodes });

  log({ status: 'adding_torrent' });
  const torrent = client.add(magnet);

  await new Promise((resolve, reject) => {
    torrent.on('metadata', resolve);
    torrent.on('error', reject);
    torrent.on('warning', e => log({ type: 'warn', msg: e.message }));
  });

  // Run our own DHT announce loop at 8s intervals (torrent-discovery uses 15min by default)
  let announceCount = 0;
  const dhtAnnounceInterval = setInterval(() => {
    if (torrent.destroyed || !client.dht) { clearInterval(dhtAnnounceInterval); return; }
    announceCount++;
    client.dht.announce(torrent.infoHash, client.torrentPort || 0, (err) => {
      if (err && announceCount % 3 === 0) {
        log({ type: 'warn', msg: `DHT announce #${announceCount}: ${err.message}` });
      }
    });
  }, 8000);

  const file = selectFile(torrent, selectSeason, selectEpisode);
  log({
    status: 'metadata',
    name: torrent.name,
    infoHash: torrent.infoHash,
    numFiles: torrent.files.length,
    selectedFile: file.name,
    selectedFileIndex: torrent.files.indexOf(file),
  });

  // Start HTTP server immediately (so it's ready to serve, but don't report ready yet)
  const usePort = port || (torrentPort || 0);
  const server = client.createServer({ pathname: '/' });
  const addr = await new Promise((resolve, reject) => {
    server.listen(usePort, () => resolve(server.address()));
  });

  const streamUrl = `http://127.0.0.1:${addr.port}/${torrent.infoHash}/${encodeURIComponent(file.name)}`;
  log({ status: 'server_started', streamUrl, port: addr.port, file: file.name, length: file.length });

  // Wait for at least 1 peer to connect before declaring "ready"
  const hadPeer = await new Promise((resolve) => {
    const check = () => {
      if (torrent.numPeers > 0 || torrent.downloaded > 0) return resolve(true);
    };
    check();
    torrent.on('wire', () => { if (!resolve.called) { resolve.called = true; resolve(true); } });
    torrent.on('peer', () => { if (!resolve.called) { resolve.called = true; resolve(true); } });
    // After 30 seconds, give up and start anyway
    setTimeout(() => { if (!resolve.called) { resolve.called = true; resolve(false); } }, 30000);
  });

  log({
    status: 'ready',
    streamUrl,
    port: addr.port,
    infoHash: torrent.infoHash,
    file: file.name,
    length: file.length,
    hadPeer,
  });
}

main().catch(e => {
  log({ type: 'fatal', msg: e.message });
  process.exit(1);
});

// Progress reporting
setInterval(() => {
  const t = client.torrents[0];
  if (t && !t.destroyed) {
    log({
      status: 'progress',
      progress: t.progress,
      downloaded: t.downloaded,
      downloadSpeed: t.downloadSpeed,
      numPeers: t.numPeers,
    });
  }
}, 10000);

function shutdown() {
  client.destroy(() => process.exit(0));
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
process.on('SIGBREAK', shutdown);
