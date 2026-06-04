import argparse


# ============================================================
# Validation
# ============================================================

def validate_address(addr: str) -> bytes:
    if not addr.startswith("0x"):
        raise ValueError("Address must start with 0x")

    addr = addr[2:]

    if len(addr) != 40:
        raise ValueError("Ethereum address must be 20 bytes")

    try:
        return bytes.fromhex(addr)
    except ValueError:
        raise ValueError("Invalid address hex")


def parse_hex_data(data: str | None) -> bytes:
    if not data:
        return b""

    if data.startswith("0x"):
        data = data[2:]

    if len(data) % 2:
        raise ValueError("Hex data length must be even")

    try:
        return bytes.fromhex(data)
    except ValueError:
        raise ValueError("Invalid calldata hex")


# ============================================================
# RLP
# ============================================================

def int_to_bytes(value: int) -> bytes:
    if value < 0:
        raise ValueError("Negative integers not supported")

    if value == 0:
        return b""

    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def rlp_encode(item):
    if isinstance(item, int):
        return rlp_encode(int_to_bytes(item))

    if isinstance(item, bytes):
        length = len(item)

        # single byte < 0x80
        if length == 1 and item[0] < 0x80:
            return item

        if length <= 55:
            return bytes([0x80 + length]) + item

        length_bytes = int_to_bytes(length)

        return (
            bytes([0xB7 + len(length_bytes)])
            + length_bytes
            + item
        )

    if isinstance(item, list):
        payload = b"".join(rlp_encode(x) for x in item)

        length = len(payload)

        if length <= 55:
            return bytes([0xC0 + length]) + payload

        length_bytes = int_to_bytes(length)

        return (
            bytes([0xF7 + len(length_bytes)])
            + length_bytes
            + payload
        )

    raise TypeError(f"Unsupported type: {type(item)}")


# ============================================================
# Transaction Builders
# ============================================================

def build_type0(args) -> bytes:
    tx = [
        args.nonce,
        args.gasprice,
        args.gaslimit,
        validate_address(args.output),
        args.amount,
        parse_hex_data(args.message),

        # EIP-155 unsigned payload
        args.chain,
        0,
        0,
    ]

    return rlp_encode(tx)


def build_type2(args) -> bytes:
    payload = [
        args.chain,
        args.nonce,
        args.maxPriorityFeePerGas,
        args.maxFeePerGas,
        args.gaslimit,
        validate_address(args.output),
        args.amount,
        parse_hex_data(args.message),

        # access list
        [],
    ]

    return b"\x02" + rlp_encode(payload)


# ============================================================
# CLI
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Create unsigned Ethereum transactions"
    )

    parser.add_argument(
        "-t",
        "--type",
        required=True,
        choices=["0", "2"],
        help="Transaction type"
    )

    parser.add_argument(
        "-c",
        "--chain",
        type=int,
        default=1,
        help="Chain ID"
    )

    parser.add_argument(
        "-n",
        "--nonce",
        required=True,
        type=int,
        help="Account nonce"
    )

    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Destination address"
    )

    parser.add_argument(
        "-a",
        "--amount",
        required=True,
        type=int,
        help="Amount in wei"
    )

    parser.add_argument(
        "-m",
        "--message",
        default="0x",
        help="Calldata hex"
    )

    # Type 0
    parser.add_argument(
        "-p",
        "--gasprice",
        type=int
    )

    # Shared
    parser.add_argument(
        "-l",
        "--gaslimit",
        type=int
    )

    # Type 2
    parser.add_argument(
        "-f",
        "--maxFeePerGas",
        type=int
    )

    parser.add_argument(
        "-P",
        "--maxPriorityFeePerGas",
        type=int
    )

    return parser.parse_args()


# ============================================================
# Main
# ============================================================

def main():
    args = parse_args()

    if args.type == "0":
        if args.gasprice is None:
            raise ValueError(
                "Type 0 requires --gasprice"
            )

        if args.gaslimit is None:
            raise ValueError(
                "Type 0 requires --gaslimit"
            )

        tx = build_type0(args)

    elif args.type == "2":
        if args.maxFeePerGas is None:
            raise ValueError(
                "Type 2 requires --maxFeePerGas"
            )

        if args.maxPriorityFeePerGas is None:
            raise ValueError(
                "Type 2 requires --maxPriorityFeePerGas"
            )

        if args.gaslimit is None:
            raise ValueError(
                "Type 2 requires --gaslimit"
            )

        tx = build_type2(args)

    else:
        raise RuntimeError("Impossible state")

    print("Unsigned transaction:")
    print(tx.hex())


if __name__ == "__main__":
    main()