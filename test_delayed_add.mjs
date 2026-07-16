import WebTorrent from 'webtorrent';

const magnet = process.argv[2] || 'magnet:?xt=urn:btih:255e2890a1a724bcdd93b1120dd08a5a8e11b949';
const port = parseInt(process.argv[3]) || 12345;

const client = new WebTorrent({
  dht: true,
  dhtPort: port + 1,
  torrentPort: port + 2,
});

client.on('error', (err) => console.error('Client error:', err.message));
client.on('warning', (err) => console.warn('Client warning:', err.message));

// Wait for DHT to bootstrap before adding torrent
console.log('Waiting 5s for DHT bootstrap...');
setTimeout(() => {
  // Check DHT status
  if (client.dht) {
    const nodes = client.dht.nodes ? (client.dht.nodes.toArray ? client.dht.nodes.toArray().length : '?') : '?';
    console.log(`DHT status after 5s: ready=${client.dht.ready}, nodes=${nodes}`);
  }
  
  console.log(`\nAdding magnet: ${magnet}`);
  const torrent = client.add(magnet);
  
  torrent.on('infoHash', () => {
    console.log('Info hash:', torrent.infoHash);
  });

  torrent.on('metadata', () => {
    console.log('\n*** METADATA RECEIVED! ***');
    console.log('Name:', torrent.name);
    console.log('Files:', torrent.files.map((f, i) => `  [${i}] ${f.name} (${(f.length / 1024 / 1024).toFixed(1)} MB)`));
    console.log(`\nStarting HTTP server on port ${port}...`);
    const server = torrent.createServer({ port });
    server.listen(port, () => {
      console.log(`Stream URL: http://127.0.0.1:${port}/${torrent.infoHash}/${torrent.files[0].name}`);
    });
  });

  torrent.on('done', () => {
    console.log('\n*** DOWNLOAD COMPLETE! ***');
    process.exit(0);
  });

  torrent.on('download', () => {
    if (torrent.progress > 0.01) {
      console.log(`Progress: ${(torrent.progress * 100).toFixed(1)}% (${torrent.numPeers} peers)`);
    }
  });

  torrent.on('error', (err) => console.error('Torrent error:', err.message));
  torrent.on('warning', (err) => console.warn('Torrent warning:', err.message));
  
  // Show peer connections
  torrent.on('wire', (wire, addr) => {
    console.log('Connected to peer:', addr);
  });

  // Monitor
  const iv = setInterval(() => {
    if (client.dht) {
      const nodes = client.dht.nodes ? (client.dht.nodes.toArray ? client.dht.nodes.toArray().length : '?') : '?';
      console.log(`Status: progress=${(torrent.progress * 100).toFixed(1)}%, peers=${torrent.numPeers}, dhtNodes=${nodes}`);
    }
  }, 5000);
  
  setTimeout(() => {
    clearInterval(iv);
    console.log('\nTimeout reached');
    if (client.dht) {
      const nodes = client.dht.nodes ? (client.dht.nodes.toArray ? client.dht.nodes.toArray().length : '?') : '?';
      console.log(`Final DHT nodes: ${nodes}`);
    }
    console.log(`Final progress: ${(torrent.progress * 100).toFixed(1)}%, peers: ${torrent.numPeers}`);
    client.destroy(() => process.exit(0));
  }, 90000);
}, 5000);
