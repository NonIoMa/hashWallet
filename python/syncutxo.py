"""UTXO sync utility for hash-wallet.

Fetches current UTXOs and recent transactions from mempool.space (BTC) or 
litecoinspace.org (LTC) for every address stored in a wallet JSON file, 
and updates the file in place.
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
    total_balance = 0

    for addrEL in addresses:
        address = addrEL["address"]
        currency = addrEL["currency"]
        print(f"Checking {address} ({currency.upper()})")

        # Select API Provider based on currency
        if currency == "btc":
            base_url = "https://mempool.space/api"
        elif currency == "testnet4":
            base_url = "https://mempool.space/testnet4/api"
        elif currency == "ltc":
            base_url = "https://litecoinspace.org/api"
        elif currency == "tltc":
            base_url = "https://litecoinspace.org/testnet/api"
        else:
            print(f"  WARNING: Unknown currency '{currency}', skipping.")
            continue

        utxo_url = f"{base_url}/address/{address}/utxo"
        tx_url = f"{base_url}/address/{address}/txs"

        try:
            utxos = requests.get(utxo_url).json()
            txs = requests.get(tx_url).json()
        except Exception as e:
            print(f"  ERROR: Failed to fetch data for {address}: {e}")
            continue

        addrEL["UTXO"] = utxos
        addrEL["transactions"] = [t["txid"] for t in txs]

        # Build txid -> tx lookup for fast matching
        tx_by_id = {t["txid"]: t for t in txs}

        # Calculate balance for this address
        address_balance = sum(utxo.get("value", 0) for utxo in utxos)
        addrEL["balance"] = address_balance
        total_balance += address_balance

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
                tx_detail_url = f"{base_url}/tx/{utxo_txid}"
                try:
                    tx_detail = requests.get(tx_detail_url).json()
                    utxo["scriptpubkey"] = tx_detail["vout"][utxo_vout]["scriptpubkey"]
                    print(f"  UTXO {utxo_txid[:8]}...:{utxo_vout} -> {utxo['scriptpubkey']}")
                except (IndexError, KeyError, Exception):
                    print(f"  WARNING: Could not find vout {utxo_vout} in fetched tx {utxo_txid[:8]}...")

    # Update wallet-level balance
    if "wallet" not in wallet_data:
        wallet_data["wallet"] = {}
    wallet_data["wallet"]["balance"] = total_balance

    with open(file, "w") as f:
        json.dump(wallet_data, f, indent=2)

    print()
    print("--- SUMMARY ---")
    print(f"  Total balance: {total_balance} units")
    for addr in addresses:
        balance = addr.get("balance", 0)
        print(f"  [{addr['currency'].upper()}] {addr['address']}: {balance}")


if __name__ == "__main__":
    main()
