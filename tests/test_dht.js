const DHT = require('C:\\Users\\Administraitor\\AppData\\Roaming\\npm\\node_modules\\webtorrent-cli\\node_modules\\bittorrent-dht').default;

console.log('=== DHT Bootstrap Test with explicit IPv4 ===');
const dht = new DHT({
  bootstrap: [
    '67.215.246.10:6881',    // router.bittorrent.com
    '82.221.103.244:6881',   // router.utorrent.com
    '87.98.162.88:6881',     // dht.transmissionbt.com (vm4)
    '212.129.33.59:6881',    // dht.transmissionbt.com (vm5)
  ],
});

dht.on('ready', () => {
  const count = dht.nodes ? dht.nodes.size : '0';
  console.log(`DHT READY - nodes in routing table: ${count}`);
  
  const infoHash = Buffer.from('255e2890a1a724bcdd93b1120dd08a5a8e11b949', 'hex');
  console.log('Looking up peers for torrent infoHash...');
  dht.lookup(infoHash);
});

dht.on('peer', (peer, infoHash) => {
  console.log(`>>> PEER FOUND: ${peer.host}:${peer.port} for hash ${infoHash.toString('hex').slice(0,8)}...`);
});

dht.on('node', (node) => {
  console.log(`DHT node: ${node.host}:${node.port}`);
});

dht.on('warning', (err) => {
  console.log(`WARNING: ${err.message || err}`);
});

dht.on('error', (err) => {
  console.log(`ERROR: ${err.message || err}`);
});

setTimeout(() => {
  const count = dht.nodes ? dht.nodes.size : '0';
  console.log(`\n=== After 30s ===`);
  console.log(`DHT nodes in table: ${count}`);
  console.log(`DHT ready: ${dht.ready}`);
  
  console.log('\n=== Conclusion ===');
  if (count > 0) {
    console.log('DHT bootstrap SUCCESSFUL with explicit IPv4 addresses!');
    console.log('Root cause: DNS resolution of DHT bootstrap hostnames likely returned IPv6');
    console.log('addresses, but Node.js UDP socket was bound to IPv4, causing silent failure.');
    console.log('Fix: Use explicit IPv4 addresses for DHT bootstrap nodes.');
  } else {
    console.log('DHT bootstrap FAILED even with IPv4 addresses.');
    console.log('Network-level UDP blocking is suspected.');
  }
  
  process.exit(0);
}, 30000);
