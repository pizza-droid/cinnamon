import WebTorrent from 'webtorrent';
import http from 'http';

const magnet = process.argv[2] || 'magnet:?xt=urn:btih:255e2890a1a724bcdd93b1120dd08a5a8e11b949';
const port = parseInt(process.argv[3]) || 12345;

console.log('Creating WebTorrent client...');
const client = new WebTorrent({
  dht: true,
  dhtPort: port + 1,
  torrentPort: port + 2,
});

client.on('error', (err) => console.error('Client error:', err.message));
client.on('warning', (err) => console.warn('Client warning:', err.message));

console.log(`Adding magnet: ${magnet}`);
const torrent = client.add(magnet);

torrent.on('infoHash', () => {
  console.log('Info hash:', torrent.infoHash);
});

torrent.on('metadata', () => {
  console.log('\n*** METADATA RECEIVED! ***');
  console.log('Name:', torrent.name);
  console.log('Files:', torrent.files.map((f, i) => `  [${i}] ${f.name} (${(f.length / 1024 / 1024).toFixed(1)} MB)`));
  
  // Create HTTP server to stream
  console.log(`\nStarting HTTP server on port ${port}...`);
  const server = torrent.createServer({ port, origin: false });
  server.listen(port, () => {
    console.log(`HTTP server listening at http://127.0.0.1:${port}`);
    console.log(`Stream URL: http://127.0.0.1:${port}/${torrent.infoHash}/${torrent.files[0].name}`);
    
    // Verify the server is accessible
    http.get(`http://127.0.0.1:${port}`, (res) => {
      console.log(`Server health check: HTTP ${res.statusCode}`);
      res.resume();
    }).on('error', (err) => {
      console.error('Health check failed:', err.message);
    });
  });
  
  server.on('error', (err) => {
    console.error('Server error:', err.message);
  });
});

torrent.on('done', () => {
  console.log('\nDownload complete!');
});

torrent.on('download', (bytes) => {
  if (torrent.progress > 0) {
    console.log(`Downloaded ${(torrent.downloaded / 1024 / 1024).toFixed(1)} MB / ${(torrent.length / 1024 / 1024).toFixed(1)} MB (${(torrent.progress * 100).toFixed(1)}%)`);
  }
});

torrent.on('error', (err) => console.error('Torrent error:', err.message));
torrent.on('warning', (err) => console.warn('Torrent warning:', err.message));

// Show peer info
torrent.on('wire', (wire, addr) => {
  console.log('Connected to peer:', addr);
  wire.on('download', (bytes) => {
    // just to track connections
  });
});

// Monitor DHT
if (client.dht) {
  client.dht.on('node', (node) => {
    // silent
  });
  client.dht.on('peer', (peer, infoHash) => {
    console.log(`DHT: found peer ${peer.host}:${peer.port}`);
  });
}

// Timeout after 2 minutes
setTimeout(() => {
  console.log('\nTimeout reached');
  console.log(`Progress: ${(torrent.progress * 100).toFixed(1)}%`);
  console.log(`Peers: ${torrent.numPeers}`);
  client.destroy(() => process.exit(0));
}, 120000);
