#!/usr/bin/env python3
"""
hashWallet Terminal UI
Multi-page curses interface for the hashWallet crypto wallet system.
"""

import curses
import json
import os
import re
import sys
import subprocess
import textwrap
import getpass
from pathlib import Path

# Add python/ and assets/ to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "python"))

WALLETS_DIR = BASE_DIR / "wallets"
PYTHON_DIR = BASE_DIR / "python"
TRANSACTIONS_DIR = BASE_DIR / "transactions"

# ─── Color pair IDs ──────────────────────────────────────────────────────────
CP_NORMAL    = 0
CP_TITLE     = 1
CP_SELECTED  = 2
CP_HIGHLIGHT = 3
CP_SUCCESS   = 4
CP_ERROR     = 5
CP_DIM       = 6
CP_BORDER    = 7
CP_KEY       = 8
CP_CURRENCY  = 9

CURRENCIES = {
    "btc":      {"name": "Bitcoin",        "symbol": "₿",  "icon": "●"},
    "testnet4": {"name": "Bitcoin Testnet","symbol": "tBTC","icon": "○"},
}

SUPPORTED_CURRENCIES = list(CURRENCIES.keys())

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(CP_TITLE,     curses.COLOR_YELLOW,  -1)
    curses.init_pair(CP_SELECTED,  curses.COLOR_BLACK,   curses.COLOR_CYAN)
    curses.init_pair(CP_HIGHLIGHT, curses.COLOR_CYAN,    -1)
    curses.init_pair(CP_SUCCESS,   curses.COLOR_GREEN,   -1)
    curses.init_pair(CP_ERROR,     curses.COLOR_RED,     -1)
    curses.init_pair(CP_DIM,       curses.COLOR_WHITE,   -1)
    curses.init_pair(CP_BORDER,    curses.COLOR_CYAN,    -1)
    curses.init_pair(CP_KEY,       curses.COLOR_MAGENTA, -1)
    curses.init_pair(CP_CURRENCY,  curses.COLOR_YELLOW,  -1)

def draw_box(win, y, x, h, w, title="", color=CP_BORDER):
    attr = curses.color_pair(color)
    try:
        win.attron(attr)
        win.addch(y,     x,     curses.ACS_ULCORNER)
        win.addch(y,     x+w-1, curses.ACS_URCORNER)
        win.addch(y+h-1, x,     curses.ACS_LLCORNER)
        win.addch(y+h-1, x+w-1, curses.ACS_LRCORNER)
        for i in range(1, w-1):
            win.addch(y,     x+i, curses.ACS_HLINE)
            win.addch(y+h-1, x+i, curses.ACS_HLINE)
        for i in range(1, h-1):
            win.addch(y+i, x,     curses.ACS_VLINE)
            win.addch(y+i, x+w-1, curses.ACS_VLINE)
        win.attroff(attr)
    except curses.error:
        pass
    if title:
        label = f" {title} "
        tx = x + max(1, (w - len(label)) // 2)
        try:
            win.attron(curses.color_pair(CP_TITLE) | curses.A_BOLD)
            win.addstr(y, tx, label)
            win.attroff(curses.color_pair(CP_TITLE) | curses.A_BOLD)
        except curses.error:
            pass

def safe_addstr(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    max_len = w - x - 1
    if max_len <= 0:
        return
    try:
        win.addstr(y, x, text[:max_len], attr)
    except curses.error:
        pass

def draw_header(win, title):
    h, w = win.getmaxyx()
    safe_addstr(win, 0, 0, "─" * w, curses.color_pair(CP_BORDER))
    logo = "⬡ hashWallet"
    safe_addstr(win, 0, 2, logo, curses.color_pair(CP_TITLE) | curses.A_BOLD)
    if title:
        safe_addstr(win, 0, 2 + len(logo) + 2, f"› {title}", curses.color_pair(CP_DIM))

def draw_footer(win, hints):
    h, w = win.getmaxyx()
    safe_addstr(win, h-1, 0, "─" * w, curses.color_pair(CP_BORDER))
    x = 2
    for key, desc in hints:
        if x >= w - 2:
            break
        key_str = f" {key} "
        desc_str = f" {desc}  "
        safe_addstr(win, h-1, x, key_str, curses.color_pair(CP_KEY) | curses.A_REVERSE)
        x += len(key_str)
        safe_addstr(win, h-1, x, desc_str, curses.color_pair(CP_DIM))
        x += len(desc_str)

def input_field(win, y, x, width, prompt, secret=False, prefill=""):
    """Simple inline input. Returns (value, cancelled)."""
    h, w = win.getmaxyx()
    safe_addstr(win, y, x, prompt, curses.color_pair(CP_HIGHLIGHT))
    px = x + len(prompt)
    field_w = max(width - len(prompt), 0)
    buf = list(prefill)
    cursor = len(buf)
    curses.curs_set(1)
    while True:
        disp = ("*" * len(buf)) if secret else "".join(buf)
        field_str = disp.ljust(field_w)[:field_w] if field_w > 0 else ""
        if field_w > 0:
            safe_addstr(win, y, px, field_str, curses.color_pair(CP_SELECTED))
            # ior
            ci = min(cursor, field_w - 1)
            if ci < 0:
                ci = 0
            ch = field_str[ci] if 0 <= ci < len(field_str) else " "
            safe_addstr(win, y, px + ci, ch, curses.color_pair(CP_SELECTED) | curses.A_BLINK)
        win.refresh()
        k = win.getch()
        if k in (curses.KEY_ENTER, 10, 13):
            break
        elif k == 27:
            curses.curs_set(0)
            return "", True
        elif k in (curses.KEY_BACKSPACE, 127, 8):
            if cursor > 0:
                buf.pop(cursor - 1)
                cursor -= 1
        elif k == curses.KEY_DC:
            if cursor < len(buf):
                buf.pop(cursor)
        elif k == curses.KEY_LEFT:
            cursor = max(0, cursor - 1)
        elif k == curses.KEY_RIGHT:
            cursor = min(len(buf), cursor + 1)
        elif k == curses.KEY_HOME:
            cursor = 0
        elif k == curses.KEY_END:
            cursor = len(buf)
        elif 32 <= k <= 126:
            buf.insert(cursor, chr(k))
            cursor += 1
    curses.curs_set(0)
    return "".join(buf), False

def modal_message(win, title, lines, color=CP_SUCCESS, wait=True):
    """Show a centered modal message box."""
    h, w = win.getmaxyx()
    mw = min(60, w - 4)
    mh = len(lines) + 4
    my = (h - mh) // 2
    mx = (w - mw) // 2
    # Shadow
    for r in range(mh):
        safe_addstr(win, my + r + 1, mx + 2, " " * mw)
    draw_box(win, my, mx, mh, mw, title, color)
    for i, line in enumerate(lines):
        safe_addstr(win, my + 2 + i, mx + 2, line[:mw - 4], curses.color_pair(color))
    if wait:
        safe_addstr(win, my + mh - 1, mx + mw - 14, " press any key ", curses.color_pair(CP_DIM))
        win.refresh()
        win.getch()

def confirm_modal(win, title, lines):
    """Returns True if user presses y/Y/Enter, False for n/N/Esc."""
    h, w = win.getmaxyx()
    mw = min(60, w - 4)
    mh = len(lines) + 5
    my = (h - mh) // 2
    mx = (w - mw) // 2
    for r in range(mh):
        safe_addstr(win, my + r + 1, mx + 2, " " * mw)
    draw_box(win, my, mx, mh, mw, title, CP_HIGHLIGHT)
    for i, line in enumerate(lines):
        safe_addstr(win, my + 2 + i, mx + 2, line[:mw - 4], curses.color_pair(CP_DIM))
    safe_addstr(win, my + mh - 2, mx + 2, "[Y]es / [N]o", curses.color_pair(CP_KEY) | curses.A_BOLD)
    win.refresh()
    while True:
        k = win.getch()
        if k in (ord('y'), ord('Y'), 10, 13):
            return True
        if k in (ord('n'), ord('N'), 27):
            return False

def run_script(script_name, args_list):
    """Run a python script from PYTHON_DIR, return (stdout, stderr, returncode)."""
    cmd = [sys.executable, str(PYTHON_DIR / script_name)] + [str(a) for a in args_list]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PYTHON_DIR))
    return result.stdout, result.stderr, result.returncode

def get_wallets():
    WALLETS_DIR.mkdir(exist_ok=True)
    return sorted([f.stem for f in WALLETS_DIR.glob("*.json")])

def load_wallet(name):
    path = WALLETS_DIR / f"{name}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def get_addresses_by_currency(wallet_data, currency):
    addrs = wallet_data.get("wallet", {}).get("addresses", [])
    return [a for a in addrs if a.get("currency") == currency]

def format_sats(sats):
    if sats is None:
        return "? sats"
    sats = int(sats)
    btc = sats / 1e8
    if abs(btc) < 0.001:
        return f"{sats:,} sats"
    return f"{btc:.8f} BTC ({sats:,} sats)"

# ════════════════════════════════════════════════════════════════════════════
# PAGE 1: Wallet selector
# ════════════════════════════════════════════════════════════════════════════

def page_select_wallet(stdscr):
    curses.curs_set(0)
    sel = 0
    msg = ""

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, "Select Wallet")
        draw_footer(stdscr, [("↑↓", "Navigate"), ("Enter", "Open"), ("N", "New Wallet"), ("Q", "Quit")])

        wallets = get_wallets()

        draw_box(stdscr, 2, 2, h - 4, w - 4, "Wallets")

        if not wallets:
            safe_addstr(stdscr, 5, 6, "No wallets found.", curses.color_pair(CP_DIM) | curses.A_ITALIC)
            safe_addstr(stdscr, 6, 6, "Press N to create a new wallet.", curses.color_pair(CP_DIM))
        else:
            for i, name in enumerate(wallets):
                y = 4 + i
                if y >= h - 5:
                    break
                data = load_wallet(name)
                addrs = data.get("wallet", {}).get("addresses", [])
                bal = data.get("wallet", {}).get("balance", None)
                bal_str = format_sats(bal) if bal is not None else "not synced"
                line = f"  {name:<24} {len(addrs)} addr(s)   {bal_str}"
                if i == sel:
                    safe_addstr(stdscr, y, 4, " " * (w - 10), curses.color_pair(CP_SELECTED))
                    safe_addstr(stdscr, y, 4, line, curses.color_pair(CP_SELECTED) | curses.A_BOLD)
                else:
                    safe_addstr(stdscr, y, 4, line)

        if msg:
            safe_addstr(stdscr, h - 3, 4, msg, curses.color_pair(CP_ERROR))

        stdscr.refresh()
        k = stdscr.getch()

        if k in (ord('q'), ord('Q')):
            return None

        elif k == curses.KEY_UP:
            if wallets:
                sel = (sel - 1) % len(wallets)

        elif k == curses.KEY_DOWN:
            if wallets:
                sel = (sel + 1) % len(wallets)

        elif k in (curses.KEY_ENTER, 10, 13):
            if wallets:
                return wallets[sel]

        elif k in (ord('n'), ord('N')):
            result = page_create_wallet(stdscr)
            sel = 0
            msg = result if result else ""

# ════════════════════════════════════════════════════════════════════════════
# PAGE: Create Wallet
# ════════════════════════════════════════════════════════════════════════════

def page_create_wallet(stdscr):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, "Create New Wallet")
    draw_footer(stdscr, [("Esc", "Cancel"), ("Enter", "Confirm")])
    draw_box(stdscr, 2, 2, h - 4, w - 4, "New Wallet")

    fields = {}

    safe_addstr(stdscr, 4, 5, "Wallet name:", curses.color_pair(CP_HIGHLIGHT) | curses.A_BOLD)
    v, c = input_field(stdscr, 5, 5, 50, "Name: ")
    if c: return "Cancelled."
    fields["name"] = v.strip()

    safe_addstr(stdscr, 7, 5, "Seed method:", curses.color_pair(CP_HIGHLIGHT) | curses.A_BOLD)
    safe_addstr(stdscr, 8, 5, "[1] Mnemonic (24 words)   [2] Hex seed", curses.color_pair(CP_DIM))
    stdscr.refresh()
    while True:
        k = stdscr.getch()
        if k == ord('1'):
            method = "mnemonic"
            break
        elif k == ord('2'):
            method = "seed"
            break
        elif k == 27:
            return "Cancelled."

    if method == "mnemonic":
        safe_addstr(stdscr, 10, 5, "Enter 24-word mnemonic:", curses.color_pair(CP_HIGHLIGHT) | curses.A_BOLD)
        v, c = input_field(stdscr, 11, 5, w - 12, "Mnemonic: ", secret=True)
        if c: return "Cancelled."
        fields["mnemonic"] = v.strip()
        v2, c = input_field(stdscr, 12, 5, 50, "BIP39 passphrase (optional): ")
        if c: return "Cancelled."
        fields["passphrase"] = v2
        row = 13
    else:
        safe_addstr(stdscr, 10, 5, "Enter 64-byte hex seed (128 chars):", curses.color_pair(CP_HIGHLIGHT) | curses.A_BOLD)
        v, c = input_field(stdscr, 11, 5, w - 12, "Seed hex: ", secret=True)
        if c: return "Cancelled."
        fields["seed"] = v.strip()
        row = 12

    v, c = input_field(stdscr, row, 5, 50, "Encryption password: ", secret=True)
    if c: return "Cancelled."
    fields["password"] = v

    safe_addstr(stdscr, row + 1, 5, "Privacy level [0=heavy / 1=light / 2=none, default=1]: ", curses.color_pair(CP_DIM))
    v, c = input_field(stdscr, row + 2, 5, 20, "Privacy: ", prefill="1")
    fields["privacy"] = v.strip() or "1"

    # Build args
    args = [fields["name"]]
    if method == "mnemonic":
        args += ["-m"] + fields["mnemonic"].split()
        if fields.get("passphrase"):
            args += ["--passphrase", fields["passphrase"]]
    else:
        args += ["-s", fields["seed"]]
    args += [fields["password"], "-p", fields["privacy"]]

    safe_addstr(stdscr, row + 4, 5, "Creating wallet…", curses.color_pair(CP_DIM))
    stdscr.refresh()

    stdout, stderr, rc = run_script("makewallet.py", args)
    if rc == 0:
        modal_message(stdscr, "Success", [f"Wallet '{fields['name']}' created!", "", stdout.strip()[-200:]], CP_SUCCESS)
        return f"Created wallet: {fields['name']}"
    else:
        err = (stderr or stdout).strip()[-300:]
        modal_message(stdscr, "Error", textwrap.wrap(err, 54), CP_ERROR)
        return f"Error creating wallet."

# ════════════════════════════════════════════════════════════════════════════
# PAGE 2: Currency selector
# ════════════════════════════════════════════════════════════════════════════

def page_select_currency(stdscr, wallet_name):
    curses.curs_set(0)
    sel = 0
    currencies = SUPPORTED_CURRENCIES

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, f"Currency  ‹ {wallet_name}")
        draw_footer(stdscr, [("↑↓", "Navigate"), ("Enter", "Select"), ("Esc", "Back")])

        wallet_data = load_wallet(wallet_name)
        draw_box(stdscr, 2, 2, h - 4, w - 4, "Select Currency")

        safe_addstr(stdscr, 4, 5, f"Wallet: {wallet_name}", curses.color_pair(CP_DIM))

        for i, cur in enumerate(currencies):
            y = 6 + i * 3
            if y + 2 >= h - 3:
                break
            info = CURRENCIES[cur]
            addrs = get_addresses_by_currency(wallet_data, cur)
            bal = sum(int(a.get("balance", 0)) for a in addrs)
            bal_str = format_sats(bal) if addrs else "no addresses"
            line1 = f"  {info['icon']}  {info['name']} ({cur.upper()})"
            line2 = f"     {len(addrs)} address(es)  ·  {bal_str}"
            attr = curses.color_pair(CP_SELECTED) | curses.A_BOLD if i == sel else curses.color_pair(CP_CURRENCY) | curses.A_BOLD
            attr2 = curses.color_pair(CP_SELECTED) if i == sel else curses.color_pair(CP_DIM)
            if i == sel:
                safe_addstr(stdscr, y, 4, " " * (w - 10), curses.color_pair(CP_SELECTED))
                safe_addstr(stdscr, y + 1, 4, " " * (w - 10), curses.color_pair(CP_SELECTED))
            safe_addstr(stdscr, y, 4, line1, attr)
            safe_addstr(stdscr, y + 1, 4, line2, attr2)

        stdscr.refresh()
        k = stdscr.getch()

        if k == 27:
            return None
        elif k == curses.KEY_UP:
            sel = (sel - 1) % len(currencies)
        elif k == curses.KEY_DOWN:
            sel = (sel + 1) % len(currencies)
        elif k in (curses.KEY_ENTER, 10, 13):
            return currencies[sel]

# ════════════════════════════════════════════════════════════════════════════
# PAGE 3: Wallet Dashboard
# ════════════════════════════════════════════════════════════════════════════

def page_dashboard(stdscr, wallet_name, currency):
    curses.curs_set(0)
    sel = 0

    ACTIONS = [
        ("B", "Balance / Addresses"),
        ("R", "Receive (show all)"),
        ("S", "Send"),
        ("Y", "Sync UTXOs"),
        ("A", "Advanced"),
        ("Esc", "Back"),
    ]

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        info = CURRENCIES[currency]
        draw_header(stdscr, f"{info['name']}  ‹ {wallet_name}")
        draw_footer(stdscr, [(a[0], a[1]) for a in ACTIONS])

        wallet_data = load_wallet(wallet_name)
        addrs = get_addresses_by_currency(wallet_data, currency)
        total_bal = sum(int(a.get("balance", 0)) for a in addrs)

        # Balance card
        draw_box(stdscr, 2, 2, 6, w - 4, f"{info['icon']} {info['name']}")
        safe_addstr(stdscr, 4, 5, "Balance:", curses.color_pair(CP_DIM))
        safe_addstr(stdscr, 4, 14, format_sats(total_bal), curses.color_pair(CP_SUCCESS) | curses.A_BOLD)
        safe_addstr(stdscr, 5, 5, f"Addresses: {len(addrs)}", curses.color_pair(CP_DIM))

        # Address list
        draw_box(stdscr, 8, 2, h - 11, w - 4, "Addresses")
        for i, addr in enumerate(addrs):
            y = 10 + i
            if y >= h - 4:
                break
            bal = int(addr.get("balance", 0))
            atype = addr.get("type", "?")
            path = addr.get("path", "?")
            address = addr.get("address", "?")
            utxo_count = len(addr.get("UTXO", []))
            trunc = address[:32] + "…" if len(address) > 33 else address
            line = f"  {trunc:<34} {atype:<8} {format_sats(bal):<22} {utxo_count} utxo(s)"
            if i == sel:
                safe_addstr(stdscr, y, 4, " " * (w - 10), curses.color_pair(CP_SELECTED))
                safe_addstr(stdscr, y, 4, line, curses.color_pair(CP_SELECTED) | curses.A_BOLD)
            else:
                safe_addstr(stdscr, y, 4, line)

        # Hints row
        safe_addstr(stdscr, h - 4, 4,
            "B=Balance  R=Receive  S=Send  Y=Sync  A=Advanced",
            curses.color_pair(CP_KEY))

        stdscr.refresh()
        k = stdscr.getch()

        if k == 27:
            return
        elif k == curses.KEY_UP and addrs:
            sel = (sel - 1) % len(addrs)
        elif k == curses.KEY_DOWN and addrs:
            sel = (sel + 1) % len(addrs)
        elif k in (ord('b'), ord('B')):
            page_balance_detail(stdscr, wallet_name, currency, addrs)
        elif k in (ord('r'), ord('R')):
            selected = addrs[sel] if addrs else None
            page_receive(stdscr, wallet_name, currency, selected)
        elif k in (ord('s'), ord('S')):
            selected = addrs[sel] if addrs else None
            page_send(stdscr, wallet_name, currency, addrs, selected)
        elif k in (ord('y'), ord('Y')):
            page_sync(stdscr, wallet_name)
        elif k in (ord('a'), ord('A')):
            page_advanced(stdscr, wallet_name, currency, addrs, sel)

# ════════════════════════════════════════════════════════════════════════════
# Balance Detail
# ════════════════════════════════════════════════════════════════════════════

def page_balance_detail(stdscr, wallet_name, currency, addrs):
    curses.curs_set(0)
    scroll = 0
    rows = []
    for a in addrs:
        rows.append(("ADDR", a.get("address","?"), a.get("type","?"), int(a.get("balance",0)), a.get("path","?")))
        for u in a.get("UTXO", []):
            rows.append(("UTXO", u.get("txid","?")[:20]+"…", f"vout:{u.get('vout','?')}", int(u.get("value",0)), ""))

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, f"Balance Detail  ‹ {wallet_name} / {currency}")
        draw_footer(stdscr, [("↑↓", "Scroll"), ("Esc", "Back")])
        draw_box(stdscr, 2, 2, h - 4, w - 4, "Balance & UTXOs")

        visible = h - 8
        for i, row in enumerate(rows[scroll:scroll+visible]):
            y = 4 + i
            kind, a, b, val, path = row
            if kind == "ADDR":
                line = f"  ▶ {a:<44} {b:<10} {format_sats(val)}"
                safe_addstr(stdscr, y, 4, line, curses.color_pair(CP_HIGHLIGHT) | curses.A_BOLD)
                if path:
                    safe_addstr(stdscr, y, 4 + len(line) + 2, f"path:{path}", curses.color_pair(CP_DIM))
            else:
                line = f"      └ txid: {a}  {b:<12} {format_sats(val)}"
                safe_addstr(stdscr, y, 4, line, curses.color_pair(CP_DIM))

        stdscr.refresh()
        k = stdscr.getch()
        if k == 27: return
        elif k == curses.KEY_UP:   scroll = max(0, scroll - 1)
        elif k == curses.KEY_DOWN: scroll = min(max(0, len(rows) - visible), scroll + 1)

# ════════════════════════════════════════════════════════════════════════════
# Receive
# ════════════════════════════════════════════════════════════════════════════

def page_receive(stdscr, wallet_name, currency, selected_addr):
    curses.curs_set(0)
    sel = 0
    scroll = 0

    wallet_data = load_wallet(wallet_name)
    addrs = get_addresses_by_currency(wallet_data, currency)
    if selected_addr:
        for i, a in enumerate(addrs):
            if a.get("address") == selected_addr.get("address"):
                sel = i
                break

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, f"Receive  ‹ {wallet_name} / {currency}")
        draw_footer(stdscr, [("↑↓", "Select"), ("Enter", "Copy"), ("N", "New"), ("Esc", "Back")])
        draw_box(stdscr, 2, 2, h - 4, w - 4, "Receive")

        if not addrs:
            safe_addstr(stdscr, 5, 5, "No receive addresses found.", curses.color_pair(CP_DIM))
            safe_addstr(stdscr, 6, 5, "Press N to derive a new address for this wallet/currency.", curses.color_pair(CP_DIM))
        else:
            visible = (h - 12) // 3
            visible = max(1, visible)
            if sel < scroll:
                scroll = sel
            elif sel >= scroll + visible:
                scroll = sel - visible + 1

            for idx, addr in enumerate(addrs[scroll:scroll+visible]):
                i = scroll + idx
                y = 4 + idx * 3
                used = bool(addr.get("transactions")) or bool(addr.get("UTXO"))
                clear = int(addr.get("balance", 0)) == 0 and not addr.get("UTXO")
                comment = addr.get("comment", "")
                status = "USED" if used else "NEW"
                clear_label = "CLEAR" if clear else "DIRTY"
                line1 = f"{i+1:2d}. {addr.get('address','?')[:w-24]}"
                line2 = f"    {addr.get('type','?')}  {status}/{clear_label}  {format_sats(addr.get('balance', 0))}  {comment[:max(0, w-52)]}"
                if i == sel:
                    safe_addstr(stdscr, y, 4, " " * (w - 10), curses.color_pair(CP_SELECTED))
                    safe_addstr(stdscr, y, 4, line1, curses.color_pair(CP_SELECTED) | curses.A_BOLD)
                    safe_addstr(stdscr, y + 1, 4, line2, curses.color_pair(CP_SELECTED))
                else:
                    safe_addstr(stdscr, y, 4, line1)
                    safe_addstr(stdscr, y + 1, 4, line2, curses.color_pair(CP_DIM))

            selected = addrs[sel]
            safe_addstr(stdscr, h - 6, 4, f"Selected: {selected.get('address','?')}", curses.color_pair(CP_HIGHLIGHT))
            safe_addstr(stdscr, h - 5, 4,
                f"Path: {selected.get('path','?')}  Type: {selected.get('type','?')}  Balance: {format_sats(selected.get('balance',0))}",
                curses.color_pair(CP_DIM))
            safe_addstr(stdscr, h - 4, 4,
                f"Comment: {selected.get('comment','')}", curses.color_pair(CP_DIM))

        stdscr.refresh()
        k = stdscr.getch()
        if k == 27:
            return
        elif k == curses.KEY_UP and addrs:
            sel = (sel - 1) % len(addrs)
        elif k == curses.KEY_DOWN and addrs:
            sel = (sel + 1) % len(addrs)
        elif k in (ord('n'), ord('N')):
            page_new_address(stdscr, wallet_name, currency)
            wallet_data = load_wallet(wallet_name)
            addrs = get_addresses_by_currency(wallet_data, currency)
            sel = min(sel, len(addrs)-1) if addrs else 0
        elif k in (curses.KEY_ENTER, 10, 13, ord('c'), ord('C')) and addrs:
            copy_to_clipboard(addrs[sel].get('address',''))
            modal_message(stdscr, "Copied", ["Address copied to clipboard"], CP_SUCCESS)

def page_new_address(stdscr, wallet_name, currency):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, "New Address")
    draw_footer(stdscr, [("Esc", "Cancel"), ("Enter", "Confirm")])
    draw_box(stdscr, 2, 2, h - 4, w - 4, "Derive New Address")

    row = 4
    safe_addstr(stdscr, row, 5, "BIP32 derivation path:", curses.color_pair(CP_DIM))
    default_path = "m/84'/0'/0'/0/0" if currency == "btc" else "m/84'/1'/0'/0/0"
    path, c = input_field(stdscr, row + 1, 5, 60, "Path: ", prefill=default_path)
    if c: return

    safe_addstr(stdscr, row + 3, 5, "Address type [p2pkh / p2wpkh / bip-84]:", curses.color_pair(CP_DIM))
    atype, c = input_field(stdscr, row + 4, 5, 40, "Type: ", prefill="bip-84")
    if c: return

    safe_addstr(stdscr, row + 6, 5, "Parent key password:", curses.color_pair(CP_DIM))
    pw_parent, c = input_field(stdscr, row + 7, 5, 50, "Parent pw: ", secret=True)
    if c: return

    safe_addstr(stdscr, row + 9, 5, "Address key password:", curses.color_pair(CP_DIM))
    pw_addr, c = input_field(stdscr, row + 10, 5, 50, "Address pw: ", secret=True)
    if c: return

    safe_addstr(stdscr, row + 12, 5, "Number of addresses to create [1]:", curses.color_pair(CP_DIM))
    count_str, c = input_field(stdscr, row + 13, 5, 20, "Count: ", prefill="1")
    if c: return
    try:
        count = max(1, int(count_str.strip() or "1"))
    except ValueError:
        count = 1

    safe_addstr(stdscr, row + 15, 5, "Comment (optional):", curses.color_pair(CP_DIM))
    comment, c = input_field(stdscr, row + 16, 5, 60, "Comment: ")
    if c: return

    safe_addstr(stdscr, row + 18, 5, "Deriving…", curses.color_pair(CP_DIM))
    stdscr.refresh()

    def build_paths(base_path, count):
        m = re.search(r"/(\d+)$", base_path)
        if m:
            root = base_path[:m.start()]
            start = int(m.group(1))
        else:
            root = base_path.rstrip('/')
            start = 0
        return [f"{root}/{start + i}" for i in range(count)]

    paths = build_paths(path, count)
    results = []
    for idx, addr_path in enumerate(paths):
        args = [wallet_name, addr_path, currency, atype, pw_parent, pw_addr]
        if comment:
            args += ["--comment", comment]
        stdout, stderr, rc = run_script("makeaddress.py", args)
        if rc == 0:
            results.append(f"{idx+1}. {addr_path} OK")
        else:
            err = (stderr or stdout).strip().splitlines()[-1]
            results.append(f"{idx+1}. {addr_path} ERR: {err}")

    if len(results) == 1:
        line = results[0]
        if line.endswith("OK"):
            modal_message(stdscr, "Address Created", [line], CP_SUCCESS)
        else:
            modal_message(stdscr, "Error", textwrap.wrap(line, 54), CP_ERROR)
    else:
        modal_message(stdscr, "Batch Create Results", results[-12:], CP_SUCCESS if all("OK" in r for r in results) else CP_ERROR)

# ════════════════════════════════════════════════════════════════════════════
# Sync
# ════════════════════════════════════════════════════════════════════════════

def page_sync(stdscr, wallet_name):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, f"Sync UTXOs  ‹ {wallet_name}")
    draw_box(stdscr, 2, 2, h - 4, w - 4, "Sync")
    safe_addstr(stdscr, 4, 5, "Fetching UTXOs from mempool.space…", curses.color_pair(CP_DIM))
    safe_addstr(stdscr, 5, 5, "Please wait.", curses.color_pair(CP_DIM))
    stdscr.refresh()

    stdout, stderr, rc = run_script("syncutxo.py", [wallet_name])
    lines = (stdout + stderr).strip().splitlines()[-20:]
    if rc == 0:
        modal_message(stdscr, "Sync Complete", lines[-12:] if lines else ["Done."], CP_SUCCESS)
    else:
        modal_message(stdscr, "Sync Error", lines[-12:] if lines else ["Unknown error."], CP_ERROR)

# ════════════════════════════════════════════════════════════════════════════
# Fee estimation helpers
# ════════════════════════════════════════════════════════════════════════════

def estimate_tx_vbytes(n_inputs, n_outputs, input_type="p2wpkh"):
    """Rough vbyte estimate for fee calculation."""
    if input_type in ("p2wpkh", "bip-84"):
        # segwit: 10.5 overhead + 41/input (non-witness) + 27.5/input (witness) + 31/output
        return int(10.5 + n_inputs * 68.5 + n_outputs * 31)
    else:
        # legacy p2pkh: 10 + 148/input + 34/output
        return 10 + n_inputs * 148 + n_outputs * 34

def fetch_fee_estimates(currency):
    """Fetch sat/vbyte fee estimates from mempool.space. Returns dict or None."""
    import urllib.request, json as _json
    prefix = "testnet4/" if currency == "testnet4" else ""
    try:
        url = f"https://mempool.space/{prefix}api/v1/fees/recommended"
        with urllib.request.urlopen(url, timeout=5) as r:
            return _json.loads(r.read().decode())
    except Exception:
        return None

def copy_to_clipboard(text):
    """Try to copy text to system clipboard. Returns True on success."""
    import subprocess as _sp
    for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"],
                ["pbcopy"], ["wl-copy"]):
        try:
            p = _sp.Popen(cmd, stdin=_sp.PIPE, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            p.communicate(input=text.encode())
            if p.returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False

def save_transaction(tx_hex, tx_type="signed", wallet_name="", note=""):
    """Save transaction to transactions folder with timestamp. Returns (success, filename, path)."""
    from datetime import datetime
    TRANSACTIONS_DIR.mkdir(exist_ok=True)
    
    # Create subdirectory for transaction type (signed/unsigned)
    tx_subdir = TRANSACTIONS_DIR / tx_type
    tx_subdir.mkdir(exist_ok=True)
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    wallet_prefix = f"{wallet_name}_" if wallet_name else ""
    filename = f"{wallet_prefix}{tx_type}_{timestamp}.txt"
    filepath = tx_subdir / filename
    
    try:
        # Build content
        lines = [f"Transaction: {tx_type.upper()}", f"Timestamp: {timestamp}"]
        if wallet_name:
            lines.append(f"Wallet: {wallet_name}")
        if note:
            lines.append(f"Note: {note}")
        lines.extend(["", f"TX Hex:", tx_hex, ""])
        
        content = "\n".join(lines)
        with open(filepath, "w") as f:
            f.write(content)
        return True, filename, str(filepath)
    except Exception as e:
        return False, filename, str(e)

def greedy_coin_select(all_utxos, target):
    """Greedy UTXO selection. Returns (list_of_(addr,utxo), total_in)."""
    # Sort descending by value
    sorted_utxos = sorted(all_utxos, key=lambda x: int(x[1].get("value", 0)), reverse=True)
    selected, total = [], 0
    for a, u in sorted_utxos:
        selected.append((a, u))
        total += int(u.get("value", 0))
        if total >= target:
            break
    return selected, total

# ════════════════════════════════════════════════════════════════════════════
# Send (full)
# ════════════════════════════════════════════════════════════════════════════

def page_send(stdscr, wallet_name, currency, addrs, selected_addr):
    """Full send flow: fee rate → coin select → advanced opts → review → sign → result."""
    curses.curs_set(0)

    all_utxos = []
    for a in addrs:
        for u in a.get("UTXO", []):
            all_utxos.append((a, u))

    if not all_utxos:
        modal_message(stdscr, "No UTXOs", ["No UTXOs found. Run Sync first."], CP_ERROR)
        return

    total_avail = sum(int(u[1].get("value", 0)) for u in all_utxos)

    # ── Step 1: fetch live fee estimates ──────────────────────────────────
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, f"Send  ‹ {wallet_name} / {currency}")
    draw_box(stdscr, 2, 2, h - 4, w - 4, "Fetching fee estimates…")
    safe_addstr(stdscr, 4, 5, "Connecting to mempool.space…", curses.color_pair(CP_DIM))
    stdscr.refresh()
    fee_data = fetch_fee_estimates(currency)

    # ── Step 2: send form ─────────────────────────────────────────────────
    # Determine auto change address = address of selected_addr or first addr
    auto_change = (selected_addr or (addrs[0] if addrs else {})).get("address", "")
    auto_change_path = (selected_addr or (addrs[0] if addrs else {})).get("path", "")
    # Detect input type from selected addr for vbyte estimate
    addr_type = (selected_addr or (addrs[0] if addrs else {})).get("type", "p2wpkh")

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, f"Send  ‹ {wallet_name} / {currency}")
        draw_footer(stdscr, [("Esc", "Cancel"), ("Tab", "Advanced"), ("Enter", "Next")])
        draw_box(stdscr, 2, 2, h - 4, w - 4, "Send Transaction")

        row = 4
        # Balance summary
        safe_addstr(stdscr, row, 5,
            f"Spendable: {format_sats(total_avail)}  ({len(all_utxos)} UTXO{'s' if len(all_utxos)!=1 else ''})",
            curses.color_pair(CP_SUCCESS))
        safe_addstr(stdscr, row+1, 5,
            f"Change → {auto_change[:40]}{'…' if len(auto_change)>40 else ''}  ({auto_change_path})",
            curses.color_pair(CP_DIM))

        # Fee rate panel
        row += 3
        if fee_data:
            safe_addstr(stdscr, row, 5, "Live fee rates (sat/vB):", curses.color_pair(CP_HIGHLIGHT) | curses.A_BOLD)
            safe_addstr(stdscr, row, 30,
                f"  Fast:{fee_data.get('fastestFee','?')}  Med:{fee_data.get('halfHourFee','?')}  Slow:{fee_data.get('hourFee','?')}  Min:{fee_data.get('minimumFee','?')}",
                curses.color_pair(CP_CURRENCY))
        else:
            safe_addstr(stdscr, row, 5, "Fee rates unavailable (offline)", curses.color_pair(CP_DIM))
        row += 1

        # Inputs
        dest, c = input_field(stdscr, row,   5, w - 12, "Destination: ")
        if c: return
        amount_str, c = input_field(stdscr, row+1, 5, 50, "Amount (sats): ")
        if c: return

        # Fee mode toggle
        safe_addstr(stdscr, row+2, 5, "Fee mode  [1] sat/vByte  [2] total sats  [default=1]: ", curses.color_pair(CP_DIM))
        fmode, c = input_field(stdscr, row+3, 5, 10, "Mode: ", prefill="1")
        if c: return
        fmode = fmode.strip() or "1"

        if fmode == "2":
            fee_input, c = input_field(stdscr, row+4, 5, 40, "Fee (sats): ", prefill="500")
            if c: return
            fee_rate_str = None
        else:
            default_rate = str(fee_data.get("halfHourFee", 5)) if fee_data else "5"
            fee_input, c = input_field(stdscr, row+4, 5, 40, "Fee rate (sat/vB): ", prefill=default_rate)
            if c: return
            fee_rate_str = fee_input.strip()

        # Advanced options
        safe_addstr(stdscr, row+6, 5, "─── Advanced ───────────────────────────────────────────────", curses.color_pair(CP_HIGHLIGHT))
        ver_s, c   = input_field(stdscr, row+7,  5, 20, "Version [2]: ", prefill="2")
        if c: return
        lock_s, c  = input_field(stdscr, row+8,  5, 35, "Locktime [0 / block / timestamp]: ", prefill="0")
        if c: return
        seq_s, c   = input_field(stdscr, row+9,  5, 30, "Sequence [ffffffff]: ", prefill="ffffffff")
        if c: return
        rbf_s, c   = input_field(stdscr, row+10, 5, 10, "RBF [y/N]: ", prefill="n")
        if c: return
        sighash_s, c = input_field(stdscr, row+11, 5, 30, "Sighash [1=ALL 2=NONE 3=SINGLE]: ", prefill="1")
        if c: return
        custom_change, c = input_field(stdscr, row+12, 5, w-12, "Change address [blank=auto]: ")
        if c: return

        pw, c = input_field(stdscr, row+14, 5, 50, "Signing password: ", secret=True)
        if c: return
        break

    # ── Validate & compute ────────────────────────────────────────────────
    try:
        amount = int(amount_str.replace(",", "").strip())
    except ValueError:
        modal_message(stdscr, "Error", ["Invalid amount."], CP_ERROR)
        return

    change_address = custom_change.strip() or auto_change

    # Estimate vbytes for fee rate mode (assume 2 outputs: dest + change)
    if fmode == "1":
        try:
            rate = float(fee_rate_str)
        except ValueError:
            modal_message(stdscr, "Error", ["Invalid fee rate."], CP_ERROR)
            return
        # Initial estimate with 2 outputs; will refine after coin selection
        est_vb = estimate_tx_vbytes(1, 2, addr_type)
        fee = max(1, int(rate * est_vb))
    else:
        try:
            fee = int(fee_input.replace(",","").strip())
        except ValueError:
            modal_message(stdscr, "Error", ["Invalid fee amount."], CP_ERROR)
            return
        rate = None

    # Coin selection (greedy, largest-first)
    selected_utxos, total_in = greedy_coin_select(all_utxos, amount + fee)

    # Refine fee with actual input count if rate mode
    if fmode == "1":
        est_vb = estimate_tx_vbytes(len(selected_utxos), 2, addr_type)
        fee = max(1, int(rate * est_vb))
        # Re-select with updated fee
        selected_utxos, total_in = greedy_coin_select(all_utxos, amount + fee)

    if total_in < amount + fee:
        modal_message(stdscr, "Insufficient Funds", [
            f"Need:  {format_sats(amount + fee)}",
            f"Have:  {format_sats(total_in)}",
            f"Short: {format_sats(amount + fee - total_in)}",
        ], CP_ERROR)
        return

    change = total_in - amount - fee
    n_out = 2 if (change > 546 and change_address) else 1
    vbytes = estimate_tx_vbytes(len(selected_utxos), n_out, addr_type)
    effective_rate = fee / vbytes if vbytes else 0

    # ── Review screen ─────────────────────────────────────────────────────
    rbf_enabled = rbf_s.strip().lower() in ("y", "yes")
    seq_val = "fffffffd" if rbf_enabled and int(seq_s.strip() or "ffffffff", 16) > 0xFFFFFFFE else (seq_s.strip() or "ffffffff")
    locktime_val = lock_s.strip() or "0"
    version_val  = ver_s.strip() or "2"
    sighash_val  = sighash_s.strip() or "1"

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, "Review Transaction")
        draw_footer(stdscr, [("Enter/Y", "Sign & Continue"), ("Esc", "Cancel")])
        draw_box(stdscr, 2, 2, h - 4, w - 4, "Transaction Summary")

        r = 4
        def kv(row, k, v, vc=CP_DIM):
            safe_addstr(stdscr, row, 5,  f"{k:<18}", curses.color_pair(CP_HIGHLIGHT))
            safe_addstr(stdscr, row, 23, str(v)[:w-28], curses.color_pair(vc))

        kv(r,   "To",         dest)
        kv(r+1, "Amount",     format_sats(amount), CP_SUCCESS)
        kv(r+2, "Fee",        f"{format_sats(fee)}  ({effective_rate:.2f} sat/vB,  ~{vbytes} vB)", CP_CURRENCY)
        kv(r+3, "Change",     f"{format_sats(change)} → {change_address[:35]}{'…' if len(change_address)>35 else ''}" if change > 546 else f"{format_sats(change)} (burned as fee — below dust)" )
        kv(r+4, "Inputs",     f"{len(selected_utxos)} UTXO(s)  →  {format_sats(total_in)}")
        kv(r+5, "Version",    version_val)
        kv(r+6, "Locktime",   locktime_val + (" (block)" if int(locktime_val) < 500000000 else " (timestamp)") if locktime_val.isdigit() else locktime_val)
        kv(r+7, "Sequence",   seq_val)
        kv(r+8, "RBF",        "YES (replaceable)" if rbf_enabled else "No", CP_ERROR if rbf_enabled else CP_DIM)
        kv(r+9, "Sighash",    {1:"SIGHASH_ALL",2:"SIGHASH_NONE",3:"SIGHASH_SINGLE"}.get(int(sighash_val),f"0x{int(sighash_val):02x}"))

        safe_addstr(stdscr, r+11, 5, "UTXOs selected:", curses.color_pair(CP_DIM))
        for i, (a, u) in enumerate(selected_utxos[:5]):
            safe_addstr(stdscr, r+12+i, 7,
                f"  {u.get('txid','')[:20]}…:{u.get('vout','?')}  {format_sats(u.get('value',0))}  [{a.get('type','?')}]",
                curses.color_pair(CP_DIM))
        if len(selected_utxos) > 5:
            safe_addstr(stdscr, r+17, 7, f"  … and {len(selected_utxos)-5} more", curses.color_pair(CP_DIM))

        stdscr.refresh()
        k = stdscr.getch()
        if k == 27: return
        if k in (curses.KEY_ENTER, 10, 13, ord('y'), ord('Y')):
            break

    # ── Build ─────────────────────────────────────────────────────────────
    stdscr.erase(); h, w = stdscr.getmaxyx()
    draw_header(stdscr, "Building…")
    draw_box(stdscr, 2, 2, 10, w - 4, "")

    inputs_str  = ",".join(f"{u.get('txid')}:{u.get('vout')}" for a, u in selected_utxos)
    out_parts   = [f"{dest}:{amount}"]
    if change > 546 and change_address:
        out_parts.append(f"{change_address}:{change}")
    outputs_str = ",".join(out_parts)

    safe_addstr(stdscr, 4, 5, "Building transaction…", curses.color_pair(CP_DIM)); stdscr.refresh()

    build_args = ["-i", inputs_str, "-o", outputs_str,
                  "-v", version_val, "-l", locktime_val, "-s", seq_val]
    if rbf_enabled:
        build_args.append("-r")

    stdout, stderr, rc = run_script("createtransaction.py", build_args)
    if rc != 0:
        modal_message(stdscr, "Build Error", textwrap.wrap((stderr or stdout).strip()[-300:], 54), CP_ERROR)
        return

    raw_tx = next((l.strip() for l in stdout.splitlines()
                   if len(l.strip()) > 50 and all(c in "0123456789abcdefABCDEF" for c in l.strip())), None)
    if not raw_tx:
        modal_message(stdscr, "Error", ["Could not extract raw TX.", stdout[-200:]], CP_ERROR)
        return

    # ── Sign ──────────────────────────────────────────────────────────────
    safe_addstr(stdscr, 5, 5, "Signing…", curses.color_pair(CP_DIM)); stdscr.refresh()

    stdout2, stderr2, rc2 = run_script("signtransaction.py",
        [raw_tx, wallet_name, "-p", pw, "-s", sighash_val])
    if rc2 != 0:
        modal_message(stdscr, "Sign Error", textwrap.wrap((stderr2 or stdout2).strip()[-300:], 54), CP_ERROR)
        return

    signed_tx = next((l.strip() for l in stdout2.splitlines()
                      if len(l.strip()) > 50 and all(c in "0123456789abcdefABCDEF" for c in l.strip())), None)
    if not signed_tx:
        modal_message(stdscr, "Error", ["Could not extract signed TX.", stdout2[-200:]], CP_ERROR)
        return

    page_broadcast_result(stdscr, signed_tx, wallet_name, currency,
                          meta={"amount": amount, "fee": fee, "dest": dest,
                                "vbytes": len(signed_tx)//2, "rate": fee/(len(signed_tx)//2) if signed_tx else 0})

# ════════════════════════════════════════════════════════════════════════════
# Broadcast result screen
# ════════════════════════════════════════════════════════════════════════════

def page_broadcast_result(stdscr, signed_tx, wallet_name, currency, meta=None):
    import urllib.request as _ur
    curses.curs_set(0)
    scroll = 0
    tx_lines = textwrap.wrap(signed_tx, 72)
    actual_vb = len(signed_tx) // 2
    actual_rate = (meta["fee"] / actual_vb) if meta and actual_vb else 0
    txid_result = None

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, "Signed Transaction")
        draw_footer(stdscr, [("C", "Copy TX"), ("S", "Save"), ("B", "Broadcast"), ("↑↓", "Scroll"), ("Esc", "Back")])
        draw_box(stdscr, 2, 2, h - 4, w - 4, "Signed TX")

        r = 4
        if meta:
            safe_addstr(stdscr, r,   5, f"Amount : {format_sats(meta['amount'])}", curses.color_pair(CP_SUCCESS) | curses.A_BOLD)
            safe_addstr(stdscr, r+1, 5, f"Fee    : {format_sats(meta['fee'])}  ({actual_rate:.2f} sat/vB,  {actual_vb} bytes)", curses.color_pair(CP_CURRENCY))
            safe_addstr(stdscr, r+2, 5, f"To     : {meta['dest'][:w-12]}", curses.color_pair(CP_DIM))
            r += 4

        safe_addstr(stdscr, r, 5, "TX Hex:", curses.color_pair(CP_HIGHLIGHT) | curses.A_BOLD)
        r += 1

        visible = h - r - 5
        for i, line in enumerate(tx_lines[scroll:scroll+visible]):
            safe_addstr(stdscr, r + i, 5, line, curses.color_pair(CP_DIM))

        if txid_result:
            safe_addstr(stdscr, h-5, 5, f"✓ TXID: {txid_result}", curses.color_pair(CP_SUCCESS) | curses.A_BOLD)

        stdscr.refresh()
        k = stdscr.getch()

        if k == 27:
            return
        elif k == curses.KEY_UP:
            scroll = max(0, scroll - 1)
        elif k == curses.KEY_DOWN:
            scroll = min(max(0, len(tx_lines) - visible), scroll + 1)

        elif k in (ord('c'), ord('C')):
            ok = copy_to_clipboard(signed_tx)
            modal_message(stdscr, "Copy TX",
                ["Copied to clipboard!" if ok else "Clipboard unavailable.",
                 "", "You can also select the hex above manually."],
                CP_SUCCESS if ok else CP_ERROR)

        elif k in (ord('s'), ord('S')):
            stdscr.erase(); h, w = stdscr.getmaxyx()
            draw_header(stdscr, "Save Transaction")
            draw_footer(stdscr, [("Esc", "Cancel"), ("Enter", "Save")])
            draw_box(stdscr, 2, 2, h - 4, w - 4, "Save Transaction")
            
            safe_addstr(stdscr, 4, 5, "Optional note (e.g., 'payment to Alice'):", curses.color_pair(CP_DIM))
            note, c = input_field(stdscr, 5, 5, w - 12, "Note: ")
            if not c:
                ok, filename, path = save_transaction(signed_tx, "signed", wallet_name, note)
                if ok:
                    modal_message(stdscr, "Transaction Saved",
                        [f"Saved to:", f"{path}", "", f"File: {filename}"],
                        CP_SUCCESS)
                else:
                    modal_message(stdscr, "Save Failed", [f"Error: {path}"], CP_ERROR)

        elif k in (ord('b'), ord('B')):
            if not confirm_modal(stdscr, "Broadcast?",
                    ["Send this transaction to the network?", f"Network: {currency.upper()}"]):
                continue
            url = f"https://mempool.space/{'testnet4/' if currency=='testnet4' else ''}api/tx"
            stdscr.erase(); h, w = stdscr.getmaxyx()
            draw_header(stdscr, "Broadcasting…")
            draw_box(stdscr, 2, 2, 8, w-4, "")
            safe_addstr(stdscr, 4, 5, "Submitting to mempool.space…", curses.color_pair(CP_DIM))
            stdscr.refresh()
            # Remove any whitespace/newlines from the hex before sending
            clean_hex = "".join(signed_tx.split())
            if any(c not in "0123456789abcdefABCDEF" for c in clean_hex):
                modal_message(stdscr, "Broadcast Failed",
                    ["TX contains invalid characters; aborting broadcast."], CP_ERROR)
                continue

            # Quick sanity-check: decode hex and ensure TX has at least one input
            try:
                data = bytes.fromhex(clean_hex)
                def read_vi(d, off):
                    p = d[off]
                    if p < 0xfd: return p, 1
                    elif p == 0xfd: return int.from_bytes(d[off+1:off+3], 'little'), 3
                    elif p == 0xfe: return int.from_bytes(d[off+1:off+5], 'little'), 5
                    else: return int.from_bytes(d[off+1:off+9], 'little'), 9

                if len(data) < 5:
                    raise ValueError("TX too short")
                is_segwit = (len(data) > 5 and data[4] == 0x00 and data[5] == 0x01)
                cursor = 6 if is_segwit else 4
                in_count, _ = read_vi(data, cursor)
            except Exception as e:
                modal_message(stdscr, "Broadcast Failed", [f"Invalid TX: {e}"], CP_ERROR)
                continue
            if in_count == 0:
                modal_message(stdscr, "Broadcast Failed", ["TX has zero inputs; cannot broadcast."], CP_ERROR)
                continue

            req = _ur.Request(url, data=clean_hex.encode(), headers={"Content-Type": "text/plain"})
            try:
                with _ur.urlopen(req, timeout=15) as resp:
                    txid_result = resp.read().decode().strip()
                ok_lines = [
                    f"TXID:",
                    txid_result,
                    "",
                    f"mempool.space/{'testnet4/' if currency=='testnet4' else ''}tx/{txid_result}",
                ]
                # Also copy txid
                copy_to_clipboard(txid_result)
                modal_message(stdscr, "Broadcast Success", ok_lines, CP_SUCCESS)
            except _ur.HTTPError as he:
                try:
                    body = he.read().decode(errors='ignore')
                except Exception:
                    body = str(he)
                modal_message(stdscr, "Broadcast Failed", textwrap.wrap(body, 54), CP_ERROR)
            except Exception as e:
                modal_message(stdscr, "Broadcast Failed", textwrap.wrap(str(e), 54), CP_ERROR)

# ════════════════════════════════════════════════════════════════════════════
# PAGE: Advanced
# ════════════════════════════════════════════════════════════════════════════

def page_advanced(stdscr, wallet_name, currency, addrs, sel):
    curses.curs_set(0)
    options = [
        ("P", "Derive Parent Key  (makeparent.py)"),
        ("A", "Derive Address     (makeaddress.py)"),
        ("C", "Create Transaction (createtransaction.py)"),
        ("S", "Sign Transaction   (signtransaction.py)"),
        ("X", "Inspect Raw TX"),
        ("Esc", "Back"),
    ]
    sel_adv = 0
    action_keys = [o[0] for o in options]

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, f"Advanced  ‹ {wallet_name} / {currency}")
        draw_footer(stdscr, [(o[0], o[1]) for o in options])
        draw_box(stdscr, 2, 2, h - 4, w - 4, "Advanced Options")

        for i, (key, label) in enumerate(options):
            y = 4 + i * 2
            if i == sel_adv:
                safe_addstr(stdscr, y, 4, " " * (w - 10), curses.color_pair(CP_SELECTED))
                safe_addstr(stdscr, y, 5, f"[{key}]", curses.color_pair(CP_KEY) | curses.A_REVERSE)
                safe_addstr(stdscr, y, 5 + len(key) + 3, label, curses.color_pair(CP_SELECTED) | curses.A_BOLD)
            else:
                safe_addstr(stdscr, y, 5, f"[{key}]", curses.color_pair(CP_KEY))
                safe_addstr(stdscr, y, 5 + len(key) + 3, label)

        stdscr.refresh()
        k = stdscr.getch()

        if k == 27: return
        elif k == curses.KEY_UP:   sel_adv = (sel_adv - 1) % len(options)
        elif k == curses.KEY_DOWN: sel_adv = (sel_adv + 1) % len(options)
        elif k in (curses.KEY_ENTER, 10, 13):
            choice = options[sel_adv][0]
            if choice == "Esc": return
            _dispatch_advanced(stdscr, choice, wallet_name, currency, addrs)
        else:
            ch = chr(k).upper() if 32 <= k <= 126 else ""
            if ch in action_keys:
                if ch == "Esc": return
                _dispatch_advanced(stdscr, ch, wallet_name, currency, addrs)

def _dispatch_advanced(stdscr, choice, wallet_name, currency, addrs):
    if choice == "P":
        adv_make_parent(stdscr, wallet_name)
    elif choice == "A":
        page_new_address(stdscr, wallet_name, currency)
    elif choice == "C":
        adv_create_transaction(stdscr, wallet_name, currency, addrs)
    elif choice == "S":
        adv_sign_transaction(stdscr, wallet_name, currency)
    elif choice == "X":
        adv_inspect_tx(stdscr)

# ─── Advanced: Make Parent ───────────────────────────────────────────────────

def adv_make_parent(stdscr, wallet_name):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, "Derive Parent Key")
    draw_footer(stdscr, [("Esc", "Cancel"), ("Enter", "Confirm")])
    draw_box(stdscr, 2, 2, h - 4, w - 4, "makeparent.py")

    row = 4
    safe_addstr(stdscr, row, 5, "BIP32 parent path (e.g. m/84'/0'/0'):", curses.color_pair(CP_DIM))
    path, c = input_field(stdscr, row+1, 5, 60, "Path: ", prefill="m/84'/0'/0'")
    if c: return

    safe_addstr(stdscr, row+3, 5, "Root (master) password:", curses.color_pair(CP_DIM))
    pw_root, c = input_field(stdscr, row+4, 5, 50, "Root pw: ", secret=True)
    if c: return

    safe_addstr(stdscr, row+6, 5, "New parent key password:", curses.color_pair(CP_DIM))
    pw_parent, c = input_field(stdscr, row+7, 5, 50, "Parent pw: ", secret=True)
    if c: return

    safe_addstr(stdscr, row+9, 5, "Deriving parent…", curses.color_pair(CP_DIM))
    stdscr.refresh()

    stdout, stderr, rc = run_script("makeparent.py", [wallet_name, path, pw_root, pw_parent])
    if rc == 0:
        modal_message(stdscr, "Parent Key Created", [stdout.strip()[-200:]], CP_SUCCESS)
    else:
        modal_message(stdscr, "Error", textwrap.wrap((stderr or stdout).strip()[-300:], 54), CP_ERROR)

# ─── Advanced: Create Transaction ────────────────────────────────────────────

def adv_create_transaction(stdscr, wallet_name, currency, addrs):
    """Full advanced create transaction with all options: RBF, locktime, version, sequence, sighash."""
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, "Create Transaction (Advanced)")
    draw_footer(stdscr, [("Esc", "Cancel"), ("Enter", "Build")])
    draw_box(stdscr, 2, 2, h - 4, w - 4, "createtransaction.py")

    row = 4

    # Show available UTXOs summary
    utxo_lines = []
    for a in addrs:
        for u in a.get("UTXO", []):
            utxo_lines.append(f"  {u.get('txid','')[:20]}…:{u.get('vout','?')}  {format_sats(u.get('value',0))}")

    if utxo_lines:
        safe_addstr(stdscr, row, 5, f"Available UTXOs ({len(utxo_lines)}):", curses.color_pair(CP_DIM))
        for i, ul in enumerate(utxo_lines[:3]):
            safe_addstr(stdscr, row+1+i, 5, ul, curses.color_pair(CP_DIM) | curses.A_DIM)
        row += 1 + min(len(utxo_lines), 3) + 1
    else:
        safe_addstr(stdscr, row, 5, "No UTXOs. Run Sync first.", curses.color_pair(CP_ERROR))
        row += 2

    inputs_hint = ",".join(
        f"{u.get('txid')}:{u.get('vout')}"
        for a in addrs for u in a.get("UTXO",[])
    )[:80] if addrs else ""

    inputs_str, c = input_field(stdscr, row,   5, w-12, "Inputs (txid:vout,...): ", prefill=inputs_hint)
    if c: return
    outputs_str, c = input_field(stdscr, row+1, 5, w-12, "Outputs (addr:sats,...): ")
    if c: return

    safe_addstr(stdscr, row+3, 5, "─── Advanced Options ───", curses.color_pair(CP_HIGHLIGHT) | curses.A_BOLD)

    ver_str, c = input_field(stdscr, row+4, 5, 20, "Version [1/2]: ", prefill="2")
    if c: return
    lock_str, c = input_field(stdscr, row+5, 5, 30, "Locktime [block/timestamp]: ", prefill="0")
    if c: return
    seq_str,  c = input_field(stdscr, row+6, 5, 30, "Sequence [hex, default ffffffff]: ", prefill="ffffffff")
    if c: return

    safe_addstr(stdscr, row+7, 5, "RBF (Replace-By-Fee) [y/N]:", curses.color_pair(CP_DIM))
    rbf_str, c = input_field(stdscr, row+8, 5, 10, "RBF: ", prefill="n")
    if c: return

    safe_addstr(stdscr, row+10, 5, "Building…", curses.color_pair(CP_DIM))
    stdscr.refresh()

    args = ["-i", inputs_str, "-o", outputs_str,
            "-v", ver_str.strip() or "2",
            "-l", lock_str.strip() or "0",
            "-s", seq_str.strip() or "ffffffff"]
    if rbf_str.strip().lower() in ("y", "yes"):
        args.append("-r")

    stdout, stderr, rc = run_script("createtransaction.py", args)
    if rc != 0:
        modal_message(stdscr, "Build Error", textwrap.wrap((stderr or stdout).strip()[-300:], 54), CP_ERROR)
        return

    raw_tx = None
    for line in stdout.splitlines():
        line = line.strip()
        if len(line) > 50 and all(ch in "0123456789abcdefABCDEF" for ch in line):
            raw_tx = line

    if raw_tx:
        page_show_raw_tx(stdscr, raw_tx, wallet_name, currency, offer_sign=True)
    else:
        modal_message(stdscr, "Output", (stdout + stderr).strip().splitlines()[-15:], CP_DIM)

# ─── Advanced: Sign Transaction ───────────────────────────────────────────────

def adv_sign_transaction(stdscr, wallet_name, currency):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, "Sign Transaction (Advanced)")
    draw_footer(stdscr, [("Esc", "Cancel"), ("Enter", "Sign")])
    draw_box(stdscr, 2, 2, h - 4, w - 4, "signtransaction.py")

    row = 4
    safe_addstr(stdscr, row, 5, "Paste raw unsigned transaction hex:", curses.color_pair(CP_DIM))
    raw_tx, c = input_field(stdscr, row+1, 5, w-12, "Raw TX: ")
    if c: return

    safe_addstr(stdscr, row+3, 5, "Sighash type:", curses.color_pair(CP_DIM))
    safe_addstr(stdscr, row+4, 7, "1=SIGHASH_ALL  2=SIGHASH_NONE  3=SIGHASH_SINGLE  0x81=ALL|ANYONECANPAY", curses.color_pair(CP_DIM) | curses.A_DIM)
    sighash_str, c = input_field(stdscr, row+5, 5, 20, "Sighash [1]: ", prefill="1")
    if c: return

    pw, c = input_field(stdscr, row+7, 5, 50, "Signing password: ", secret=True)
    if c: return

    safe_addstr(stdscr, row+9, 5, "Signing…", curses.color_pair(CP_DIM))
    stdscr.refresh()

    stdout, stderr, rc = run_script("signtransaction.py",
        [raw_tx, wallet_name, "-p", pw, "-s", sighash_str.strip() or "1"])

    if rc != 0:
        modal_message(stdscr, "Sign Error", textwrap.wrap((stderr or stdout).strip()[-300:], 54), CP_ERROR)
        return

    signed = None
    for line in stdout.splitlines():
        line = line.strip()
        if len(line) > 50 and all(ch in "0123456789abcdefABCDEF" for ch in line):
            signed = line
    if signed:
        page_show_raw_tx(stdscr, signed, wallet_name, currency, offer_sign=False)
    else:
        modal_message(stdscr, "Output", (stdout+stderr).strip().splitlines()[-15:], CP_DIM)

# ─── Advanced: Inspect TX ────────────────────────────────────────────────────

def adv_inspect_tx(stdscr):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, "Inspect Raw Transaction")
    draw_footer(stdscr, [("Esc", "Cancel"), ("Enter", "Inspect")])
    draw_box(stdscr, 2, 2, h - 4, w - 4, "TX Inspector")

    safe_addstr(stdscr, 4, 5, "Paste raw transaction hex:", curses.color_pair(CP_DIM))
    raw_tx, c = input_field(stdscr, 5, 5, w-12, "Raw TX: ")
    if c: return

    # Try to parse
    try:
        # Inline minimal parsing
        data = bytes.fromhex(raw_tx)
        version = int.from_bytes(data[0:4], 'little')

        # Detect segwit
        is_segwit = (data[4] == 0x00 and data[5] == 0x01)
        cursor = 6 if is_segwit else 4

        def read_vi(d, off):
            p = d[off]
            if p < 0xfd: return p, 1
            elif p == 0xfd: return int.from_bytes(d[off+1:off+3],'little'), 3
            elif p == 0xfe: return int.from_bytes(d[off+1:off+5],'little'), 5
            else: return int.from_bytes(d[off+1:off+9],'little'), 9

        in_count, n = read_vi(data, cursor); cursor += n
        inputs = []
        for _ in range(in_count):
            txid = data[cursor:cursor+32][::-1].hex()
            vout = int.from_bytes(data[cursor+32:cursor+36],'little')
            cursor += 36
            sl, n = read_vi(data, cursor); cursor += n
            script = data[cursor:cursor+sl].hex(); cursor += sl
            seq = data[cursor:cursor+4].hex(); cursor += 4
            inputs.append((txid, vout, script, seq))

        out_count, n = read_vi(data, cursor); cursor += n
        outputs = []
        for _ in range(out_count):
            val = int.from_bytes(data[cursor:cursor+8],'little'); cursor += 8
            sl, n = read_vi(data, cursor); cursor += n
            spk = data[cursor:cursor+sl].hex(); cursor += sl
            outputs.append((val, spk))

        locktime = int.from_bytes(data[-4:],'little')

        lines = [
            f"Version  : {version}",
            f"SegWit   : {'Yes' if is_segwit else 'No'}",
            f"Locktime : {locktime}  " + (f"(block {locktime})" if locktime < 500000000 else f"(timestamp)"),
            f"Inputs   : {len(inputs)}",
        ]
        for i, (txid, vout, script, seq) in enumerate(inputs):
            rbf = int(seq, 16) <= 0xFFFFFFFD
            lines.append(f"  In[{i}]: {txid[:20]}…:{vout}  seq:{seq}  {'RBF' if rbf else ''}")
            if script:
                lines.append(f"         scriptSig: {script[:40]}…")
        lines.append(f"Outputs  : {len(outputs)}")
        for i, (val, spk) in enumerate(outputs):
            lines.append(f"  Out[{i}]: {format_sats(val)}  scriptPubKey: {spk[:30]}…")

        page_scroll_text(stdscr, "TX Inspector", lines)

    except Exception as e:
        modal_message(stdscr, "Parse Error", [str(e)], CP_ERROR)

# ─── Generic scrollable text page ─────────────────────────────────────────────

def page_show_raw_tx(stdscr, raw_tx, wallet_name, currency, offer_sign=False):
    lines = textwrap.wrap(raw_tx, 74)
    hints = [("↑↓", "Scroll"), ("C", "Copy"), ("T", "Save"), ("Esc", "Back")]
    if offer_sign:
        hints.insert(0, ("S", "Sign this TX"))

    scroll = 0
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, "Raw Transaction Hex")
        draw_footer(stdscr, hints)
        draw_box(stdscr, 2, 2, h - 4, w - 4, "Raw TX")

        visible = h - 8
        for i, line in enumerate(lines[scroll:scroll+visible]):
            safe_addstr(stdscr, 4 + i, 5, line, curses.color_pair(CP_DIM))

        stdscr.refresh()
        k = stdscr.getch()
        if k == 27: 
            return
        elif k == curses.KEY_UP:   
            scroll = max(0, scroll - 1)
        elif k == curses.KEY_DOWN: 
            scroll = min(max(0, len(lines) - visible), scroll + 1)
        elif k in (ord('c'), ord('C')):
            ok = copy_to_clipboard(raw_tx)
            modal_message(stdscr, "Copy TX",
                ["Copied to clipboard!" if ok else "Clipboard unavailable."],
                CP_SUCCESS if ok else CP_ERROR)
        elif k in (ord('s'), ord('S')) and offer_sign:
            adv_sign_transaction_prefilled(stdscr, wallet_name, raw_tx, currency)
        elif k in (ord('t'), ord('T')):
            # Save unsigned transaction
            stdscr.erase(); h, w = stdscr.getmaxyx()
            draw_header(stdscr, "Save Transaction")
            draw_footer(stdscr, [("Esc", "Cancel"), ("Enter", "Save")])
            draw_box(stdscr, 2, 2, h - 4, w - 4, "Save Transaction")
            
            safe_addstr(stdscr, 4, 5, "Optional note (e.g., 'pending signature'):", curses.color_pair(CP_DIM))
            note, c = input_field(stdscr, 5, 5, w - 12, "Note: ")
            if not c:
                ok, filename, path = save_transaction(raw_tx, "unsigned", wallet_name, note)
                if ok:
                    modal_message(stdscr, "Transaction Saved",
                        [f"Saved to:", f"{path}", "", f"File: {filename}"],
                        CP_SUCCESS)
                else:
                    modal_message(stdscr, "Save Failed", [f"Error: {path}"], CP_ERROR)

def adv_sign_transaction_prefilled(stdscr, wallet_name, raw_tx, currency):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, "Sign Transaction")
    draw_footer(stdscr, [("Esc", "Cancel"), ("Enter", "Sign")])
    draw_box(stdscr, 2, 2, h - 4, w - 4, "Sign")

    safe_addstr(stdscr, 4, 5, "Sighash type [1=ALL 2=NONE 3=SINGLE]:", curses.color_pair(CP_DIM))
    sighash_str, c = input_field(stdscr, 5, 5, 20, "Sighash [1]: ", prefill="1")
    if c: return

    pw, c = input_field(stdscr, 7, 5, 50, "Password: ", secret=True)
    if c: return

    safe_addstr(stdscr, 9, 5, "Signing…", curses.color_pair(CP_DIM))
    stdscr.refresh()

    stdout, stderr, rc = run_script("signtransaction.py",
        [raw_tx, wallet_name, "-p", pw, "-s", sighash_str.strip() or "1"])

    if rc != 0:
        modal_message(stdscr, "Sign Error", textwrap.wrap((stderr or stdout).strip()[-300:], 54), CP_ERROR)
        return

    signed = None
    for line in stdout.splitlines():
        line = line.strip()
        if len(line) > 50 and all(ch in "0123456789abcdefABCDEF" for ch in line):
            signed = line

    if signed:
        page_broadcast_result(stdscr, signed, wallet_name, currency)
    else:
        modal_message(stdscr, "Output", (stdout+stderr).strip().splitlines()[-15:], CP_DIM)

def page_scroll_text(stdscr, title, lines):
    scroll = 0
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr, title)
        draw_footer(stdscr, [("↑↓", "Scroll"), ("Esc", "Back")])
        draw_box(stdscr, 2, 2, h - 4, w - 4, title)
        visible = h - 8
        for i, line in enumerate(lines[scroll:scroll+visible]):
            safe_addstr(stdscr, 4 + i, 5, line[:w-10], curses.color_pair(CP_DIM))
        stdscr.refresh()
        k = stdscr.getch()
        if k == 27: return
        elif k == curses.KEY_UP:   scroll = max(0, scroll - 1)
        elif k == curses.KEY_DOWN: scroll = min(max(0, len(lines) - visible), scroll + 1)

# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main(stdscr):
    init_colors()
    curses.curs_set(0)
    stdscr.keypad(True)

    while True:
        wallet = page_select_wallet(stdscr)
        if wallet is None:
            break

        while True:
            currency = page_select_currency(stdscr, wallet)
            if currency is None:
                break
            page_dashboard(stdscr, wallet, currency)

def run():
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    run()