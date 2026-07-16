import WebTorrent from 'webtorrent';

const client = new WebTorrent({ dht: true, dhtPort: 18081, torrentPort: 18082 });
console.log('DHT created:', !!client.dht);

client.dht.on('node', (node) => {
  console.log('DHT node discovered:', node.host + ':' + node.port);
});

client.dht.on('peer', (peer, infoHash) => {
  console.log('DHT peer found:', peer.host + ':' + peer.port, 'for', infoHash.toString('hex').slice(0, 8));
});

client.dht.on('warning', (err) => {
  console.log('DHT warning:', err.message || err);
});

let count = 0;
const iv = setInterval(() => {
  count++;
  if (client.dht) {
    const nodes = client.dht.nodes ? (client.dht.nodes.toArray ? client.dht.nodes.toArray().length : '?') : 'N/A';
    console.log(`[${count}s] ready: ${client.dht.ready}, nodes in table: ${nodes}`);
  }
}, 3000);

setTimeout(() => { 
  clearInterval(iv); 
  console.log('\n=== Summary ===');
  if (client.dht) {
    const nodes = client.dht.nodes ? (client.dht.nodes.toArray ? client.dht.nodes.toArray().length : '?') : 'N/A';
    console.log(`Final node count: ${nodes}`);
    console.log('Events received during run: check above');
  }
  client.destroy(() => process.exit()); 
}, 20000);
