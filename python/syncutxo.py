"""UTXO sync utility for hash-wallet.

Fetches current UTXOs and recent transactions from mempool.space (BTC) or 
litecoinspace.org (LTC) for every address stored in a wallet JSON file, 
and updates the file in place.

For Ethereum (eth/teth), fetches balance, nonce and transaction list from
Etherscan. Set ETHERSCAN_API_KEY env var for higher rate limits.
"""

import requests
import json
import os
import argparse


ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")


def _sync_eth(addrEL: dict, testnet: bool) -> int:
    """Sync balance, nonce and tx list for an ETH address. Returns balance in wei."""
    address = addrEL["address"]
    if testnet:
        base_url = "https://api-sepolia.etherscan.io/api"
    else:
        base_url = "https://api.etherscan.io/api"

    key_param = f"&apikey={ETHERSCAN_API_KEY}" if ETHERSCAN_API_KEY else ""

    # Balance (in wei)
    bal_url = f"{base_url}?module=account&action=balance&address={address}&tag=latest{key_param}"
    resp = requests.get(bal_url).json()
    if resp.get("status") != "1":
        raise ValueError(f"Etherscan balance error: {resp.get('message')}")
    balance_wei = int(resp["result"])

    # Nonce (transaction count)
    nonce_url = f"{base_url}?module=proxy&action=eth_getTransactionCount&address={address}&tag=latest{key_param}"
    resp = requests.get(nonce_url).json()
    nonce = int(resp["result"], 16)

    # Recent transactions (last 25)
    tx_url = (
        f"{base_url}?module=account&action=txlist&address={address}"
        f"&startblock=0&endblock=99999999&page=1&offset=25&sort=desc{key_param}"
    )
    resp = requests.get(tx_url).json()
    txs = resp.get("result", []) if resp.get("status") == "1" else []
    tx_list = [
        {"hash": t["hash"], "from": t["from"], "to": t["to"],
         "value": t["value"], "blockNumber": t["blockNumber"]}
        for t in txs
    ]

    addrEL["balance"] = balance_wei
    addrEL["nonce"] = nonce
    addrEL["transactions"] = tx_list

    balance_eth = balance_wei / 1e18
    print(f"  Balance : {balance_eth:.6f} {'tETH' if testnet else 'ETH'}")
    print(f"  Nonce   : {nonce}")
    print(f"  Txs     : {len(tx_list)} recent")
    return balance_wei


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
        elif currency in ("eth", "teth"):
            try:
                bal = _sync_eth(addrEL, testnet=(currency == "teth"))
                total_balance += bal
            except Exception as e:
                print(f"  ERROR: {e}")
            continue
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
    for addr in addresses:
        balance = addr.get("balance", 0)
        cur = addr["currency"]
        if cur in ("eth", "teth"):
            print(f"  [{cur.upper()}] {addr['address']}: {balance / 1e18:.6f} {cur.upper()}")
        else:
            print(f"  [{cur.upper()}] {addr['address']}: {balance} sats")


if __name__ == "__main__":
    main()
