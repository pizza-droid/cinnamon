import WebTorrent from 'webtorrent';

const magnet = 'magnet:?xt=urn:btih:255e2890a1a724bcdd93b1120dd08a5a8e11b949';
const infoHash = Buffer.from('255e2890a1a724bcdd93b1120dd08a5a8e11b949', 'hex');

const client = new WebTorrent({ dht: true, dhtPort: 12346, torrentPort: 12347 });

let peerCount = 0;
client.dht.on('peer', (peer, ih) => {
  if (ih.toString('hex') === infoHash.toString('hex')) {
    peerCount++;
    console.log('PEER', peer.host + ':' + peer.port, 'total', peerCount);
  }
});
client.dht.on('node', n => console.log('NODE', n.host + ':' + n.port));

setTimeout(() => {
  console.log('nodes before lookup:', client.dht.nodes.toArray().length);
  console.log('Doing manual lookup...');
  client.dht.lookup(infoHash);
}, 4000);

setTimeout(() => {
  console.log('FINAL peers found:', peerCount, 'nodes:', client.dht.nodes.toArray().length);
  process.exit(0);
}, 25000);
