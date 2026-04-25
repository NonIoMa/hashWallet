"""UTXO sync utility for hash-wallet.

Fetches current UTXOs and recent transactions from mempool.space for every
address stored in a wallet JSON file, and updates the file in place.
The scriptpubkey for each UTXO is resolved by matching against the creating
transaction, fetching it directly from the API if not found in recent history.
"""

import requests
import json
import os
import argparse


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync UTXOs for all addresses in a wallet")
    parser.add_argument("name", help="Wallet name")
    return parser.parse_args()


def main():
    args = _parse_args()
    file = os.path.join("..", "wallets", args.name + ".json")

    print("--- CONFIG ---")
    print(f"  Wallet   : {args.name}")
    print(f"  File     : {file}")
    print()

    with open(file, "r") as f:
        wallet_data = json.load(f)

    addresses = wallet_data["wallet"]["addresses"]

    for addrEL in addresses:
        address = addrEL["address"]
        currency = addrEL["currency"]
        print(f"Checking {address}")

        if currency == "btc":
            prefix = ''
        elif currency == "testnet4":
            prefix = 'testnet4/'
        else:
            print(f"  WARNING: Unknown currency '{currency}', skipping.")
            continue

        utxo_url = f"https://mempool.space/{prefix}api/address/{address}/utxo"
        tx_url = f"https://mempool.space/{prefix}api/address/{address}/txs"

        utxos = requests.get(utxo_url).json()
        txs = requests.get(tx_url).json()

        addrEL["UTXO"] = utxos
        addrEL["transactions"] = [t["txid"] for t in txs]

        # Build txid -> tx lookup for fast matching
        tx_by_id = {t["txid"]: t for t in txs}

        for utxo in utxos:
            utxo_txid = utxo["txid"]
            utxo_vout = utxo["vout"]

            tx = tx_by_id.get(utxo_txid)
            if tx:
                try:
                    utxo["scriptpubkey"] = tx["vout"][utxo_vout]["scriptpubkey"]
                    print(f"  UTXO {utxo_txid[:8]}...:{utxo_vout} -> {utxo['scriptpubkey']}")
                except (IndexError, KeyError):
                    print(f"  WARNING: Could not find vout {utxo_vout} in tx {utxo_txid[:8]}...")
            else:
                # Creating tx not in recent history, fetch directly
                print(f"  Fetching tx {utxo_txid[:8]}... directly")
                tx_detail_url = f"https://mempool.space/{prefix}api/tx/{utxo_txid}"
                tx_detail = requests.get(tx_detail_url).json()
                try:
                    utxo["scriptpubkey"] = tx_detail["vout"][utxo_vout]["scriptpubkey"]
                    print(f"  UTXO {utxo_txid[:8]}...:{utxo_vout} -> {utxo['scriptpubkey']}")
                except (IndexError, KeyError):
                    print(f"  WARNING: Could not find vout {utxo_vout} in fetched tx {utxo_txid[:8]}...")

    with open(file, "w") as f:
        json.dump(wallet_data, f, indent=2)


if __name__ == "__main__":
    main()
