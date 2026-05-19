import argparse
import hashlib
import json
import os
import sys
import hmac
import copy
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from assets.crypto_utils import decrypt_private_key

# --- Cryptography & Math Utilities ---

def generate_k_rfc6979(private_key_int, message_hash_int):
    n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    priv_bytes = private_key_int.to_bytes(32, 'big')
    msg_bytes = message_hash_int.to_bytes(32, 'big')

    v = b'\x01' * 32
    k_hmac = b'\x00' * 32

    k_hmac = hmac.new(k_hmac, v + b'\x00' + priv_bytes + msg_bytes, hashlib.sha256).digest()
    v = hmac.new(k_hmac, v, hashlib.sha256).digest()
    k_hmac = hmac.new(k_hmac, v + b'\x01' + priv_bytes + msg_bytes, hashlib.sha256).digest()
    v = hmac.new(k_hmac, v, hashlib.sha256).digest()

    while True:
        v = hmac.new(k_hmac, v, hashlib.sha256).digest()
        k = int.from_bytes(v, 'big')
        if 1 <= k < n:
            return k
        k_hmac = hmac.new(k_hmac, v + b'\x00', hashlib.sha256).digest()
        v = hmac.new(k_hmac, v, hashlib.sha256).digest()

def double_sha256(hex_str):
    binary = bytes.fromhex(hex_str)
    return hashlib.sha256(hashlib.sha256(binary).digest()).digest().hex()

def get_hash160(pubkey_hex):
    sha = hashlib.sha256(bytes.fromhex(pubkey_hex)).digest()
    h = hashlib.new('ripemd160')
    h.update(sha)
    return h.hexdigest()

def get_r_from_k(k):
    P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
    N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    G = (
        0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
        0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
    )

    def point_add(P1, P2):
        if not P1: return P2
        if not P2: return P1
        x1, y1 = P1
        x2, y2 = P2
        if x1 == x2 and y1 != y2: return None
        if x1 == x2:
            m = (3 * x1 * x1 * pow(2 * y1, P - 2, P)) % P
        else:
            m = ((y2 - y1) * pow((x2 - x1) % P, P - 2, P)) % P
        x3 = (m * m - x1 - x2) % P
        y3 = (m * (x1 - x3) - y1) % P
        return (x3, y3)

    R = None
    base = G
    while k:
        if k & 1: R = point_add(R, base)
        base = point_add(base, base)
        k >>= 1
    return R[0] % N

# --- Transaction Parsing & Serialization ---

def read_varint(data, offset):
    prefix = data[offset]
    if prefix < 0xfd: return prefix, 1
    elif prefix == 0xfd: return int.from_bytes(data[offset+1:offset+3], 'little'), 3
    elif prefix == 0xfe: return int.from_bytes(data[offset+1:offset+5], 'little'), 5
    else: return int.from_bytes(data[offset+1:offset+9], 'little'), 9

def write_varint(value):
    if value < 0xfd: return bytes([value]).hex()
    elif value <= 0xffff: return 'fd' + value.to_bytes(2, 'little').hex()
    elif value <= 0xffffffff: return 'fe' + value.to_bytes(4, 'little').hex()
    else: return 'ff' + value.to_bytes(8, 'little').hex()

def parse_tx(hex_str):
    cursor = 0
    tx = bytes.fromhex(hex_str)
    version = tx[cursor:cursor+4].hex()
    cursor += 4

    is_segwit = False
    if tx[cursor:cursor+2] == b'\x00\x01':
        is_segwit = True
        cursor += 2

    input_count, bytes_read = read_varint(tx, cursor)
    cursor += bytes_read

    inputs = []
    for _ in range(input_count):
        outpoint = tx[cursor:cursor+36].hex()
        cursor += 36
        script_len, bytes_read = read_varint(tx, cursor)
        cursor += bytes_read
        script_sig = tx[cursor:cursor+script_len].hex()
        cursor += script_len
        sequence = tx[cursor:cursor+4].hex()
        cursor += 4
        inputs.append({'outpoint': outpoint, 'script_sig': script_sig, 'sequence': sequence})

    output_count, bytes_read = read_varint(tx, cursor)
    cursor += bytes_read

    outputs = []
    for _ in range(output_count):
        amount = tx[cursor:cursor+8].hex()
        cursor += 8
        script_len, bytes_read = read_varint(tx, cursor)
        cursor += bytes_read
        script_pubkey = tx[cursor:cursor+script_len].hex()
        cursor += script_len
        outputs.append({'amount': amount, 'script_pubkey': script_pubkey})

    witnesses = []
    if is_segwit:
        for _ in range(input_count):
            witness_count, bytes_read = read_varint(tx, cursor)
            cursor += bytes_read
            witness_items = []
            for _ in range(witness_count):
                item_len, bytes_read = read_varint(tx, cursor)
                cursor += bytes_read
                item = tx[cursor:cursor+item_len].hex()
                cursor += item_len
                witness_items.append(item)
            witnesses.append(witness_items)
    else:
        witnesses = [[] for _ in range(input_count)]

    locktime = tx[cursor:cursor+4].hex()
    return {'version': version, 'inputs': inputs, 'outputs': outputs, 'witnesses': witnesses, 'locktime': locktime}

def serialize_tx(parsed_tx, include_witness=True):
    res = parsed_tx['version']
    has_witness = include_witness and any(len(w) > 0 for w in parsed_tx['witnesses'])
    if has_witness: res += "0001"
    res += write_varint(len(parsed_tx['inputs']))
    for inp in parsed_tx['inputs']:
        res += inp['outpoint']
        res += write_varint(len(inp['script_sig']) // 2)
        res += inp['script_sig']
        res += inp['sequence']
    res += write_varint(len(parsed_tx['outputs']))
    for out in parsed_tx['outputs']:
        res += out['amount']
        res += write_varint(len(out['script_pubkey']) // 2)
        res += out['script_pubkey']
    if has_witness:
        for w in parsed_tx['witnesses']:
            res += write_varint(len(w))
            for item in w:
                res += write_varint(len(item) // 2)
                res += item
    res += parsed_tx['locktime']
    return res

# --- Signature Generation ---

def get_legacy_sighash(parsed_tx, input_idx, script_pubkey, sighash_type):
    tx_copy = copy.deepcopy(parsed_tx)
    for i, inp in enumerate(tx_copy['inputs']):
        inp['script_sig'] = script_pubkey if i == input_idx else ""
    raw_tx = serialize_tx(tx_copy, include_witness=False)
    raw_tx += sighash_type.to_bytes(4, 'little').hex()
    return double_sha256(raw_tx)

def get_segwit_sighash(parsed_tx, input_idx, script_code, amount_sats, sighash_type):
    version = parsed_tx['version']
    hashPrevouts = double_sha256("".join([inp['outpoint'] for inp in parsed_tx['inputs']]))
    hashSequence = double_sha256("".join([inp['sequence'] for inp in parsed_tx['inputs']]))
    outpoint = parsed_tx['inputs'][input_idx]['outpoint']
    amount_hex = amount_sats.to_bytes(8, 'little').hex()
    nSequence = parsed_tx['inputs'][input_idx]['sequence']
    hashOutputs = double_sha256("".join([
        out['amount'] + write_varint(len(out['script_pubkey']) // 2) + out['script_pubkey']
        for out in parsed_tx['outputs']
    ]))
    locktime = parsed_tx['locktime']
    # BIP143 / BCH requires 4-byte little endian sighash
    sighash_hex = (sighash_type).to_bytes(4, 'little').hex()

    preimage = (
        version + hashPrevouts + hashSequence + outpoint + script_code +
        amount_hex + nSequence + hashOutputs + locktime + sighash_hex
    )
    return double_sha256(preimage)

def prepare_signature(r, s, sighash_type):
    header = '30'
    integer_marker = '02'
    def format_der_int(val):
        h = hex(val)[2:]
        if len(h) % 2 != 0: h = '0' + h
        if int(h[:2], 16) >= 0x80: h = '00' + h
        return h
    r_hex = format_der_int(r)
    s_hex = format_der_int(s)
    r_len = f"{len(r_hex) // 2:02x}"
    s_len = f"{len(s_hex) // 2:02x}"
    signature_body = integer_marker + r_len + r_hex + integer_marker + s_len + s_hex
    sig_len = f"{len(signature_body) // 2:02x}"
    # Use only 1 byte for the sighash flag in the actual scriptSig/Witness
    return header + sig_len + signature_body + f"{(sighash_type & 0xff):02x}"

def sign_hash(z_hex, private_key_enc, password, sighash_type):
    n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    z = int(z_hex, 16)
    dA = int(decrypt_private_key(bytes.fromhex(private_key_enc), password).hex(), 16)
    k = generate_k_rfc6979(dA, z)
    r = get_r_from_k(k)
    s = (pow(k, -1, n) * (z + (r * dA))) % n
    if s > n // 2: s = n - s
    return prepare_signature(r, s, sighash_type)

# --- Core Processor ---

def find_input_wallet(txid, vout, filePath):
    with open(filePath, "r") as f:
        wallet_data = json.load(f)
    for address_obj in wallet_data["wallet"]["addresses"]:
        for utxo in address_obj.get("UTXO", []):
            utxo_vout = utxo.get("vout")
            if utxo["txid"] == txid and (utxo_vout is None or int(utxo_vout) == vout):
                return (
                    address_obj["private-key-enc"],
                    address_obj["public-key"],
                    utxo["scriptpubkey"],
                    address_obj["type"],
                    int(utxo["value"]),
                    address_obj.get("currency", "btc") # Default to btc if missing
                )
    raise ImportError(f'Input UTXO {txid}:{vout} not found in wallet')

def decode_transaction(raw_hex, filePath, sighash_type, password):
    parsed_tx = parse_tx(raw_hex)
    total = len(parsed_tx['inputs'])
    print(f"Parsed transaction: {total} input(s), {len(parsed_tx['outputs'])} output(s)")

    for i, inp in enumerate(parsed_tx['inputs']):
        txid_le = inp['outpoint'][:64]
        vout_le = inp['outpoint'][64:72]
        txid = bytes.fromhex(txid_le)[::-1].hex()
        vout = int.from_bytes(bytes.fromhex(vout_le), 'little')

        if inp['script_sig'] == '' and len(parsed_tx['witnesses'][i]) == 0:
            try:
                private_key_enc, public_key, prev_script, addr_type, amount, currency = find_input_wallet(txid, vout, filePath)
                
                is_bch = currency in ["bch", "tbch"]
                
                # Detect actual script type
                if prev_script.startswith("0014") and len(prev_script) == 44:
                    addr_type = "p2wpkh"
                elif prev_script.startswith("76a914") and prev_script.endswith("88ac"):
                    addr_type = "p2pkh"

                print(f"--- Signing Input {i}/{total} [{addr_type.upper()}] | Currency: {currency.upper()} ---")

                if addr_type == "p2pkh":
                    if is_bch:
                        bch_sighash = sighash_type | 0x41
                        script_code = write_varint(len(prev_script) // 2) + prev_script  # use actual UTXO scriptpubkey
                        z_hex = get_segwit_sighash(parsed_tx, i, script_code, amount, bch_sighash)
                        sig_der = sign_hash(z_hex, private_key_enc, password, bch_sighash)
                    else:
                        z_hex = get_legacy_sighash(parsed_tx, i, prev_script, sighash_type)
                        sig_der = sign_hash(z_hex, private_key_enc, password, sighash_type)
                    
                    sig_push = write_varint(len(sig_der) // 2) + sig_der
                    pub_push = write_varint(len(public_key) // 2) + public_key
                    parsed_tx['inputs'][i]['script_sig'] = sig_push + pub_push
                    print(f"  OK: script_sig set")

                elif addr_type == "p2wpkh":
                    script_code = "1976a914" + get_hash160(public_key) + "88ac"
                    z_hex = get_segwit_sighash(parsed_tx, i, script_code, amount, sighash_type)
                    sig_der = sign_hash(z_hex, private_key_enc, password, sighash_type)
                    parsed_tx['witnesses'][i] = [sig_der, public_key]
                    print(f"  OK: witness set")

            except ImportError as e:
                print(f"--- Skipping Input {i}: {e} ---")

    return serialize_tx(parsed_tx)

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sign a raw transaction")
    parser.add_argument("transaction", help="Raw unsigned transaction (hex)")
    parser.add_argument("name", help="Name of the wallet")
    parser.add_argument("-p", "--password", required=True, help="Password", type=str)
    parser.add_argument("-s", "--sighash", help="Sighash (default: 1)", default=1, type=int)
    return parser.parse_args()

def main():
    args = _parse_args()
    file = os.path.join("..", "wallets", args.name + ".json")
    print("--- CONFIG ---")
    print(f"  Wallet: {args.name} | Sighash: {args.sighash}")
    print()
    tx = decode_transaction(args.transaction, file, args.sighash, args.password)
    print('--- FINAL SIGNED TX ---')
    print(tx)

if __name__ == "__main__":
    main()