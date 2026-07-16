// Minimal test: create WebTorrent client and add a magnet
const WebTorrent = require('C:\\Users\\Administraitor\\AppData\\Roaming\\npm\\node_modules\\webtorrent-cli\\node_modules\\webtorrent');

const client = new WebTorrent({
  dht: true,
  dhtPort: 12350,
  torrentPort: 12351,
});

client.on('error', (err) => console.log('ERROR:', err.message));
client.on('warning', (err) => console.log('WARN:', err.message));
client.on('dht', (info) => console.log('DHT:', info));

console.log('Client created. Adding magnet...');

client.add('magnet:?xt=urn:btih:255e2890a1a724bcdd93b1120dd08a5a8e11b949', (torrent) => {
  console.log('Torrent added!');
  console.log('Name:', torrent.name);
  console.log('InfoHash:', torrent.infoHash);
  console.log('Files:', torrent.files.length);
  
  torrent.on('metadata', () => {
    console.log('Metadata received!');
    console.log('Files:', torrent.files.map(f => f.name));
  });
  
  torrent.on('done', () => {
    console.log('Torrent download complete!');
  });
  
  torrent.on('warning', (err) => console.log('Torrent WARN:', err.message));
  torrent.on('error', (err) => console.log('Torrent ERROR:', err.message));
});

// Check DHT status periodically
setInterval(() => {
  if (client.dht) {
    console.log('DHT ready:', client.dht.ready);
    console.log('DHT nodes:', client.dht.nodes ? client.dht.nodes.size || 0 : 0);
    console.log('DHT address:', client.dht.address ? JSON.stringify(client.dht.address()) : 'N/A');
  }
}, 5000);

setTimeout(() => {
  console.log('\nTime out. Destroying client...');
  client.destroy(() => {
    console.log('Destroyed');
    process.exit(0);
  });
}, 30000);
