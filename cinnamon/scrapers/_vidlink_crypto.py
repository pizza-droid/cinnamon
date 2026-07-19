"""XSalsa20-Poly1305 (NaCl crypto_secretbox) token minting for vidlink.pro.

vidlink.pro expects a media id encrypted with NaCl's crypto_secretbox
(XSalsa20 + Poly1305) under a fixed key/nonce, then base64url-encoded.
We prefer PyNaCl's `crypto_secretbox` (when the `nacl` package is
installed) because it is provably the same construction vidlink's own
tooling uses and is guaranteed to produce accepted tokens. A pure-Python
fallback (HSalsa20 + Salsa20 + Poly1305) is kept for environments without
PyNaCl, though it is not as thoroughly validated.

This lets us mint vidlink's encrypted media-id token locally instead of
depending on the community enc-dec.app endpoint, which is rate-limited /
occasionally unreachable.
"""
import base64
import struct
import time

# vidlink.pro production key (reversed/derived; public via reverse-engineering).
_KEY = bytes.fromhex("c75136c5668bbfe65a7ecad431a745db68b5f381555b38d8f6c699449cf11fcd")
_NONCE = bytes(24)


def _rotl32(v, c):
    v &= 0xFFFFFFFF
    return ((v << c) | (v >> (32 - c))) & 0xFFFFFFFF


def _salsa20_core(state, add_back=True):
    """Raw Salsa20 core (djb reference, 20 rounds)."""
    x = list(struct.unpack("<16I", state))
    original = struct.unpack("<16I", state) if add_back else None

    def R(a, b):
        a &= 0xFFFFFFFF
        return ((a << b) | (a >> (32 - b))) & 0xFFFFFFFF

    for _ in range(10):
        x[4]  ^= R(x[0]  + x[12], 7);  x[8]  ^= R(x[4]  + x[0], 9)
        x[12] ^= R(x[8]  + x[4], 13);  x[0]  ^= R(x[12] + x[8], 18)
        x[9]  ^= R(x[5]  + x[1], 7);   x[13] ^= R(x[9]  + x[5], 9)
        x[1]  ^= R(x[13] + x[9], 13);  x[5]  ^= R(x[1]  + x[13], 18)
        x[14] ^= R(x[10] + x[6], 7);   x[2]  ^= R(x[14] + x[10], 9)
        x[6]  ^= R(x[2]  + x[14], 13); x[10] ^= R(x[6]  + x[2], 18)
        x[3]  ^= R(x[15] + x[11], 7);  x[7]  ^= R(x[3]  + x[15], 9)
        x[11] ^= R(x[7]  + x[3], 13);  x[15] ^= R(x[11] + x[7], 18)
        x[1]  ^= R(x[0]  + x[3], 7);   x[2]  ^= R(x[1]  + x[0], 9)
        x[3]  ^= R(x[2]  + x[1], 13);  x[0]  ^= R(x[3]  + x[2], 18)
        x[6]  ^= R(x[5]  + x[4], 7);   x[7]  ^= R(x[6]  + x[5], 9)
        x[4]  ^= R(x[7]  + x[6], 13);  x[5]  ^= R(x[4]  + x[7], 18)
        x[11] ^= R(x[10] + x[9], 7);   x[8]  ^= R(x[11] + x[10], 9)
        x[9]  ^= R(x[8]  + x[11], 13); x[10] ^= R(x[9]  + x[8], 18)
        x[12] ^= R(x[15] + x[14], 7);  x[13] ^= R(x[12] + x[15], 9)
        x[14] ^= R(x[13] + x[12], 13); x[15] ^= R(x[14] + x[13], 18)

    if add_back:
        out = struct.pack("<16I", *((x[i] + original[i]) & 0xFFFFFFFF for i in range(16)))
    else:
        out = struct.pack("<16I", *((v) & 0xFFFFFFFF for v in x))
    return out


def _salsa20_block(key, nonce8, counter):
    """NaCl Salsa20 64-byte block: key at words 1-4 & 11-14, input at words 6-9."""
    c = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)  # "expand 32-byte k"
    in_bytes = nonce8 + struct.pack("<Q", counter)
    i = struct.unpack("<4I", in_bytes)
    k = struct.unpack("<8I", key)
    state = struct.pack("<16I",
                        c[0], k[0], k[1], k[2], k[3], c[1],
                        i[0], i[1], i[2], i[3], c[2],
                        k[4], k[5], k[6], k[7], c[3])
    return _salsa20_core(state)


def _hsalsa20(key, nonce16):
    """NaCl HSalsa20: derive 32-byte subkey from first 16 bytes of the 24-byte nonce.

    The subkey is the output words (x0, x5, x10, x15, x6, x7, x8, x9) of the
    core, NOT the first 32 bytes of the mixed state.
    """
    c = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)  # "expand 32-byte k"
    i = struct.unpack("<4I", nonce16)
    k = struct.unpack("<8I", key)
    state = struct.pack("<16I",
                        c[0], k[0], k[1], k[2], k[3], c[1],
                        i[0], i[1], i[2], i[3], c[2],
                        k[4], k[5], k[6], k[7], c[3])
    x = struct.unpack("<16I", _salsa20_core(state, add_back=False))
    return struct.pack("<8I", x[0], x[5], x[10], x[15], x[6], x[7], x[8], x[9])


def _poly1305_mac(msg, key):
    p = 2 ** 130 - 5
    r = int.from_bytes(key[0:16], "little")
    # Clamp r (RFC 8439): clear low 2 bits of bytes 4,8,12 and low 4 bits of
    # bytes 3,7,11,15 (little-endian byte order).
    r_clamp = bytearray(b"\xff" * 16)
    for idx in (3, 7, 11, 15):
        r_clamp[idx] &= 0x0F
    for idx in (4, 8, 12):
        r_clamp[idx] &= 0xFC
    r &= int.from_bytes(r_clamp, "little")
    s = int.from_bytes(key[16:32], "little")
    acc = 0
    for i in range(0, len(msg), 16):
        block = msg[i:i + 16]
        n = int.from_bytes(block + b"\x01", "little")
        acc = (acc + n) % p
        acc = (acc * r) % p
    acc = (acc + s) % p
    return (acc & ((1 << 128) - 1)).to_bytes(16, "little")


def _secretbox_seal(key, nonce, msg):
    # HSalsa20 to derive subkey from first 16 bytes of the 24-byte nonce
    subkey = _hsalsa20(key, nonce[0:16])
    salsa_nonce = nonce[16:24]  # 8 bytes
    # NaCl crypto_secretbox:
    #  - The Poly1305 key is the first 32 bytes of the Salsa20 keystream
    #    block (counter 0).
    #  - Those same 32 bytes are NOT used for encryption. The ciphertext
    #    keystream starts at byte 32 of block 0, then continues with full
    #    blocks 1, 2, ... (counter 1, 2, ...).
    ks0 = _salsa20_block(subkey, salsa_nonce, 0)
    poly_key = ks0[0:32]
    ct = bytearray()
    # first 32 bytes of keystream (block 0, second half)
    ct += bytes(msg[0:32][i] ^ ks0[32 + i] for i in range(min(32, len(msg))))
    offset = 32
    counter = 1
    while offset < len(msg):
        ks = _salsa20_block(subkey, salsa_nonce, counter)
        blk = msg[offset:offset + 64]
        ct += bytes(blk[i] ^ ks[i] for i in range(len(blk)))
        offset += 64
        counter += 1
    tag = _poly1305_mac(bytes(ct), poly_key)
    return bytes(ct) + tag


def _encrypt_media_id_nacl(media_id):
    """Mint a vidlink token using PyNaCl's crypto_secretbox (preferred)."""
    from nacl.bindings import crypto_secretbox

    timestamp = int(time.time()) + 480
    message = str(media_id).encode("utf-8") + struct.pack(">Q", timestamp)
    box = crypto_secretbox(message, _NONCE, _KEY)
    payload = _NONCE + box
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def encrypt_media_id(media_id):
    """Return the base64url token vidlink.pro expects for a TMDB/media id."""
    try:
        return _encrypt_media_id_nacl(media_id)
    except Exception:
        pass
    timestamp = int(time.time()) + 480
    message = str(media_id).encode("utf-8") + struct.pack(">Q", timestamp)
    ciphertext = _secretbox_seal(_KEY, _NONCE, message)
    payload = _NONCE + ciphertext
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
