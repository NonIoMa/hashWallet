"""Create a raw unsigned Bitcoin/Litecoin transaction for hash-wallet.

Builds a serialized unsigned transaction from a list of inputs (txid:vout)
and outputs (address:amount_sats). Supports P2PKH, P2SH, P2WPKH, and P2WSH
output scripts. The result is a raw hex string ready to be signed with
signtransaction.py.
"""

"""Build a raw unsigned Bitcoin/Litecoin transaction from inputs and outputs.

Accepts inputs as txid:vout pairs and outputs as address:amount_sats pairs.
Produces a serialized unsigned transaction hex ready to be passed to
signtransaction.py. Supports P2PKH, P2SH, P2WPKH, and P2WSH output scripts.

Usage:
    python createtransaction.py -i <txid:vout,...> -o <address:sats,...> [-v version] [-l locktime] [-s sequence] [-r]
"""

import base58
import argparse
import sys
import bech32
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))


def string_to_json(arg, type):
    label = arg.split(',')
    for i, x in enumerate(label):
        values = x.split(':')
        if type == "input":
            if len(values) != 2:
                raise ValueError(f"Invalid input format: '{x}' (expected txid:vout)")
            label[i] = {"txid": values[0], "vout": values[1]}
        elif type == "output":
            if len(values) != 2:
                raise ValueError(f"Invalid output format: '{x}' (expected address:amount)")
            label[i] = {"address": values[0], "amount": values[1]}
    return label


def to_compact_size(n):
    n = int(n)
    if n < 253:
        return n.to_bytes(1, 'little').hex()
    elif n <= 0xFFFF:
        return "fd" + n.to_bytes(2, 'little').hex()
    elif n <= 0xFFFFFFFF:
        return "fe" + n.to_bytes(4, 'little').hex()
    else:
        return "ff" + n.to_bytes(8, 'little').hex()


def make_script_pubkey(address):
    # P2PKH: '1'=BTC, 'm'/'n'=Testnet (BTC/LTC), 'L'=LTC Mainnet
    if address[0] in ('1', 'm', 'n', 'L'):
        return '76a914' + base58.b58decode(address)[1:21].hex() + '88ac'

    # P2SH: '3'=BTC/LTC, 'M'=LTC Mainnet, '2'=Testnet P2SH
    elif address[0] in ('3', 'M', '2'):
        return 'a914' + base58.b58decode(address)[1:21].hex() + '87'

    # P2WPKH / P2WSH: native SegWit addresses (BTC and LTC)
    elif address.startswith(('bc1q', 'tb1q', 'bcrt1q', 'ltc1q', 'tltc1q')):
        hrp, data = bech32.bech32_decode(address)
        decoded_bytes = bech32.convertbits(data[1:], 5, 8, False)

        if len(decoded_bytes) == 20:
            # P2WPKH
            return '0014' + bytes(decoded_bytes).hex()
        elif len(decoded_bytes) == 32:
            # P2WSH
            return '0020' + bytes(decoded_bytes).hex()

    raise ValueError(f"Unknown or unsupported address type: {address}")


def make_locktime(lock_time):
    return lock_time.to_bytes(4, byteorder='little').hex()


def make_header(version):
    return version.to_bytes(4, byteorder='little').hex()


def make_inputs(inputs, sequence):
    raw = to_compact_size(len(inputs))
    seq_bytes = int(sequence, 16).to_bytes(4, byteorder='little').hex()
    print(f"Inputs: {len(inputs)}")

    for i, x in enumerate(inputs):
        prev_hash = bytes.fromhex(x['txid'])[::-1].hex()
        prev_index = int(x['vout']).to_bytes(4, 'little').hex()
        script_len = to_compact_size(0)
        raw += prev_hash + prev_index + script_len + seq_bytes
        print(f"  Input {i}: {x['txid'][:8]}...:{x['vout']}")

    return raw


def make_outputs(outputs):
    raw = to_compact_size(len(outputs))
    print(f"Outputs: {len(outputs)}")

    for i, x in enumerate(outputs):
        value = int(x['amount']).to_bytes(8, 'little').hex()
        script_pubkey = make_script_pubkey(x['address'])
        script_len = to_compact_size(len(bytes.fromhex(script_pubkey)))
        raw += value + script_len + script_pubkey
        print(f"  Output {i}: {x['amount']} sats -> {x['address']}")

    return raw


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a raw unsigned Bitcoin/Litecoin transaction")
    parser.add_argument("-i", "--inputs", required=True, help="Inputs format: txid:vout[,txid:vout,...]")
    parser.add_argument("-o", "--outputs", required=True, help="Outputs format: address:amount_sats[,...]")
    parser.add_argument("-v", "--version", type=int, default=2, help="Transaction version (default: 2)")
    parser.add_argument("-l", "--locktime", type=int, default=0, help="Transaction locktime (default: 0)")
    parser.add_argument("-s", "--sequence", type=str, default='ffffffff', help="Input sequence (default: ffffffff)")
    parser.add_argument("-r", "--replace", action="store_true", help="Enable Replace-By-Fee (sets sequence to fffffffd)")
    return parser.parse_args()


def main():
    args = _parse_args()

    inputs = string_to_json(args.inputs, 'input')
    outputs = string_to_json(args.outputs, 'output')

    if args.replace and int(args.sequence, 16) > 0xfffffffe:
        args.sequence = 'fffffffd'

    if len(args.sequence) != 8:
        raise ValueError(f"Invalid sequence length: '{args.sequence}' (expected 8 hex chars)")

    print("--- CONFIG ---")
    print(f"  Version  : {args.version}")
    print(f"  Locktime : {args.locktime}")
    print(f"  Sequence : {args.sequence}")
    print(f"  RBF      : {'enabled' if args.replace else 'disabled'}")
    print()

    raw_tx = (
        make_header(args.version)
        + make_inputs(inputs, args.sequence)
        + make_outputs(outputs)
        + make_locktime(args.locktime)
    )

    print('--- FINAL TX ---')
    print(raw_tx)


if __name__ == "__main__":
    main()
