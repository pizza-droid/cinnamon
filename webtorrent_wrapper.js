// Patch k-rpc bootstrap nodes to use IPv4 addresses before loading webtorrent
const path = require('path');
const fs = require('fs');

// Patch the k-rpc module's BOOTSTRAP_NODES
const krpcPath = require.resolve('k-rpc', {
  paths: [path.join(require('os').homedir(), 'AppData/Roaming/npm/node_modules/webtorrent-cli/node_modules')]
});
const krpcContent = fs.readFileSync(krpcPath, 'utf8');

// Patch the BOOTSTRAP_NODES
const patchedContent = krpcContent.replace(
  /var BOOTSTRAP_NODES = \[[\s\S]*?\]/,
  `var BOOTSTRAP_NODES = [
  { host: '67.215.246.10', port: 6881 },    // router.bittorrent.com
  { host: '82.221.103.244', port: 6881 },    // router.utorrent.com
  { host: '87.98.162.88', port: 6881 },      // dht.transmissionbt.com (vm4)
  { host: '212.129.33.59', port: 6881 }       // dht.transmissionbt.com (vm5)
]`
);

if (patchedContent !== krpcContent) {
  console.log('Patched k-rpc bootstrap nodes');
  // Write to a temp file and swap
  fs.writeFileSync(krpcPath + '.patched', patchedContent);
  fs.renameSync(krpcPath, krpcPath + '.bak');
  fs.renameSync(krpcPath + '.patched', krpcPath);
}

// Now require webtorrent (will use patched k-rpc)
const WebTorrent = require('webtorrent');

const url = process.argv[2] || 'magnet:?xt=urn:btih:255e2890a1a724bcdd93b1120dd08a5a8e11b949';
const port = parseInt(process.argv[3]) || 18080;

const client = new WebTorrent({
  dht: true,
  dhtPort: port + 1,
  torrentPort: port + 2,
});

client.on('error', (err) => console.error('ERROR:', err.message));
client.on('warning', (err) => console.warn('WARN:', err.message));

// Log DHT bootstrap events
client.on('dht', (info) => console.log('DHT event:', typeof info === 'string' ? info : JSON.stringify(info)));

console.log('DHT:', client.dht ? 'created' : 'not created');

// Check DHT status periodically
const checkInterval = setInterval(() => {
  if (client.dht) {
    console.log('DHT ready:', client.dht.ready, 'nodeId:', client.dht.nodeId ? client.dht.nodeId.toString('hex').slice(0, 8) : 'N/A');
    if (client.dht.nodes) {
      console.log('DHT nodes:', client.dht.nodes.size || client.dht.nodes.toArray().length || 0);
    }
  }
}, 5000);

console.log(`Adding torrent: ${url}`);
client.add(url, { announce: [] }, (torrent) => {
  clearInterval(checkInterval);
  console.log('\nTorrent metadata received!');
  console.log('Name:', torrent.name);
  console.log('Info hash:', torrent.infoHash);
  console.log('Files:', torrent.files.map(f => f.name));
  console.log('Server:', torrent.server ? torrent.server.listening ? `http://127.0.0.1:${port}` : 'not listening' : 'no server');
  
  // Start the HTTP server
  torrent.on('listening', (serverUrl) => {
    console.log('HTTP server listening at:', serverUrl || `http://127.0.0.1:${port}`);
  });
  
  torrent.on('error', (err) => console.error('Torrent error:', err.message));
  torrent.on('warning', (err) => console.warn('Torrent warning:', err.message));
  
  torrent.on('done', () => {
    console.log('Download complete!');
  });
  
  // Start streaming
  const server = torrent.createServer({ port });
  server.listen(port, () => {
    console.log(`Stream available at http://127.0.0.1:${port}`);
  });
});

setTimeout(() => {
  console.log('\nTimeout reached. Exiting...');
  client.destroy(() => process.exit(0));
}, 60000);
