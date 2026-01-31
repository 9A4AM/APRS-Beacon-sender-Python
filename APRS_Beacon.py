#-------------------------------------------------------------------------------
# Name:        APRS Beacon sender
# Purpose:
#
# Author:      9A4AM
#
# Created:     29.01.2026
# Updated:     30.01.2026 (Stateless APRS-IS connection)
# Copyright:   (c) 9A4AM 2026
# Licence:
#-------------------------------------------------------------------------------

import socket
import time
import threading
import configparser
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from datetime import datetime

# ===============================
# UI theme
# ===============================

BG_COLOR = "#1e1e1e"
FG_COLOR = "#e6e6e6"
BTN_COLOR = "#2d2d2d"
BTN_ACTIVE = "#3a3a3a"
STATUS_RED = "#8b0000"
STATUS_GREEN = "#006400"
TITLE_COLOR = "#d4af37"

FONT_MAIN = ("Segoe UI", 11)
FONT_LOG = ("Consolas", 11)
FONT_STATUS = ("Segoe UI", 12, "bold")
FONT_TITLE = ("Segoe UI", 14, "bold")

# ===============================
# APRS helpers
# ===============================

def decimal_to_aprs_lat(lat):
    direction = "N" if lat >= 0 else "S"
    lat = abs(lat)
    deg = int(lat)
    min_ = (lat - deg) * 60
    return f"{deg:02d}{min_:05.2f}{direction}"

def decimal_to_aprs_lon(lon):
    direction = "E" if lon >= 0 else "W"
    lon = abs(lon)
    deg = int(lon)
    min_ = (lon - deg) * 60
    return f"{deg:03d}{min_:05.2f}{direction}"

SYMBOL_MAP = {
    "Antenna": "r",
    "Ballon": "O",
    "Home": "-",
    "WX Station": "_",
    "Dish antenna": "`"
}

SYMBOL_LIST = list(SYMBOL_MAP.keys())


def wait_for_logresp(sock, timeout=5):
    sock.settimeout(timeout)
    start = time.time()

    while time.time() - start < timeout:
        data = sock.recv(1024)
        if not data:
            break

        text = data.decode(errors="ignore")
        for line in text.splitlines():
            if "logresp" in line.lower():
                return line.strip()

    return None


# ===============================
# Config loader
# ===============================

CONFIG_FILE = "config.ini"

def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE)

    return {
        "server": cfg["APRS_Data"]["Server"],
        "port": int(cfg["APRS_Data"]["Port"]),
        "interval": int(cfg["APRS_Data"]["Time"]),
        "symbol": cfg["APRS_Data"]["Symbol"],
        "comment": cfg["APRS_Data"]["Comment"],
        "lat": float(cfg["Location"]["Latitude"]),
        "lon": float(cfg["Location"]["Longitude"]),
        "call": cfg["Personal_Data"]["Call"],
        "ssid": cfg["Personal_Data"]["SSID"],
        "password": cfg["Personal_Data"]["Password"],
        "autostart": cfg["App"].getboolean("Start")
    }

def save_config(cfg):
    parser = configparser.ConfigParser()
    parser.read(CONFIG_FILE)

    parser["APRS_Data"]["Server"] = cfg["server"]
    parser["APRS_Data"]["Port"] = str(cfg["port"])
    parser["APRS_Data"]["Time"] = str(cfg["interval"])
    parser["APRS_Data"]["Symbol"] = cfg["symbol"]
    parser["APRS_Data"]["Comment"] = cfg["comment"]
    parser["Location"]["Latitude"] = str(cfg["lat"])
    parser["Location"]["Longitude"] = str(cfg["lon"])
    parser["Personal_Data"]["Call"] = cfg["call"]
    parser["Personal_Data"]["SSID"] = cfg["ssid"]
    parser["Personal_Data"]["Password"] = cfg["password"]
    parser["App"]["Start"] = "1" if cfg["autostart"] else "0"

    with open(CONFIG_FILE, "w") as f:
        parser.write(f)

# ===============================
# APRS Packet
# ===============================

def build_packet(cfg):
    ssid = f"-{cfg['ssid']}" if cfg["ssid"] else ""
    lat = decimal_to_aprs_lat(cfg["lat"])
    lon = decimal_to_aprs_lon(cfg["lon"])
    symbol = SYMBOL_MAP.get(cfg["symbol"], "-")
    timestamp = time.strftime("%H%M%Sz", time.gmtime())
    return f"{cfg['call']}{ssid}>APU25N,TCPIP*:@{timestamp}{lat}/{lon}{symbol}{cfg['comment']}"

# ===============================
# APRS Sender (STATELESS)
# ===============================

class APRSSender:
    def __init__(self, log_func):
        self.log = log_func
        self.packet_count = 0

    def send_beacon(self, cfg, retries=2, retry_delay=3):
        attempt = 0

        while attempt <= retries:
            sock = None
            try:
                sock = socket.create_connection(
                    (cfg["server"], cfg["port"]), timeout=10
                )

                # Login
                login = f"user {cfg['call']} pass {cfg['password']} vers PY-APRS\n"
                sock.sendall(login.encode())

                # Wait for logresp (VB6-style)
                logresp = wait_for_logresp(sock, timeout=5)
                if not logresp:
                    raise RuntimeError("No logresp from APRS-IS server")

                self.log(f"APRS-IS: {logresp}")

                # Mandatory delay after connect + login
                time.sleep(2)

                # Send beacon
                packet = build_packet(cfg)
                sock.sendall((packet + "\n").encode())

                # Give TCP time to flush
                time.sleep(0.5)

                self.packet_count += 1
                self.log(f"Sent: {packet}")
                return  # SUCCESS

            except Exception as e:
                attempt += 1
                if attempt > retries:
                    raise
                self.log(f"Send failed ({attempt}/{retries}): {e}")
                time.sleep(retry_delay)

            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass



# ===============================
# Main GUI
# ===============================

class APRSGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("APRS Beacon Sender")
        self.geometry("750x600")
        self.configure(bg=BG_COLOR)

        self.cfg = load_config()
        self.sender = APRSSender(self.log)
        self.running = True
        self.beacon_thread = None

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.iconbitmap("earth.ico")

        title = tk.Label(self, text="APRS Beacon sender by 9A4AM © 2026",
                         bg=BG_COLOR, fg=TITLE_COLOR, font=FONT_TITLE)
        title.pack(fill="x")

        self.lbl_callsign = tk.Label(
            self,
            text=f"CALLSIGN: {self.get_callsign_text()}",
            bg=BG_COLOR,
            fg="#00c8ff",
            font=("Segoe UI", 12, "bold"),
            pady=4
        )
        self.lbl_callsign.pack(fill="x")


        self.status = tk.Label(self, text="Idle", bg=STATUS_RED,
                               fg="white", font=FONT_STATUS)
        self.status.pack(fill="x")

        self.logbox = scrolledtext.ScrolledText(
            self, height=20, bg=BG_COLOR, fg=FG_COLOR,
            insertbackground="white", font=FONT_LOG)
        self.logbox.pack(fill="both", expand=True, padx=6, pady=6)

        frame = tk.Frame(self, bg=BG_COLOR)
        frame.pack(pady=6)

        tk.Button(frame, text="Send Beacon", command=self.send_once,
                  width=16, bg=BTN_COLOR, fg=FG_COLOR,
                  activebackground=BTN_ACTIVE, relief="flat").pack(side="left", padx=6)

        tk.Button(frame, text="Config", command=self.open_config,
                  width=16, bg=BTN_COLOR, fg=FG_COLOR,
                  activebackground=BTN_ACTIVE, relief="flat").pack(side="left", padx=6)

        self.counter = tk.Label(self, text="Packets: 0",
                                bg=BG_COLOR, fg=FG_COLOR, font=FONT_MAIN)
        self.counter.pack(pady=4)

        if self.cfg["autostart"]:
            self.after(1000, self.start_beacon)

    def get_callsign_text(self):
        if self.cfg["ssid"]:
            return f"{self.cfg['call']}-{self.cfg['ssid']}"
        return self.cfg["call"]

    def log(self, msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.logbox.insert(tk.END, f"[{ts}] {msg}\n")
        self.logbox.see(tk.END)

    def send_once(self):
        try:
            self.status.config(text="Sending...", bg="#b8860b")
            self.sender.send_beacon(self.cfg)
            self.counter.config(text=f"Packets: {self.sender.packet_count}")
            self.status.config(text="Idle", bg=STATUS_GREEN)
        except Exception as e:
            self.status.config(text="Error", bg=STATUS_RED)
            messagebox.showerror("Send error", str(e))

    def start_beacon(self):
        if self.beacon_thread and self.beacon_thread.is_alive():
            return
        self.beacon_thread = threading.Thread(target=self.beacon_loop, daemon=True)
        self.beacon_thread.start()

    def beacon_loop(self):
        while self.running:
            self.send_once()
            time.sleep(self.cfg["interval"] * 60)

    def open_config(self):
        ConfigWindow(self, self.cfg, self.apply_config)

    def apply_config(self, new_cfg):
        self.cfg = new_cfg
        self.lbl_callsign.config(text=f"CALLSIGN: {self.get_callsign_text()}")
        self.log("Config updated")

    def on_close(self):
        self.running = False
        self.destroy()

# ===============================
# Config window
# ===============================

class ConfigWindow(tk.Toplevel):
    def __init__(self, master, cfg, save_callback):
        super().__init__(master)
        self.title("APRS Config")
        self.configure(bg=BG_COLOR)
        self.cfg = cfg.copy()
        self.save_callback = save_callback
        self.resizable(False, False)

        row = 0

        def add_label(entry_text):
            lbl = tk.Label(self, text=entry_text, bg=BG_COLOR, fg=FG_COLOR, font=FONT_MAIN)
            lbl.grid(row=row, column=0, sticky="e", padx=5, pady=4)
            return lbl

        # Entries
        self.entries = {}

        # Personal_Data
        add_label("Call:")
        self.entries["call"] = tk.Entry(self, font=FONT_MAIN, width=30)
        self.entries["call"].grid(row=row, column=1, padx=5, pady=4)
        self.entries["call"].insert(0, cfg["call"])
        row += 1

        add_label("SSID:")
        self.entries["ssid"] = tk.Entry(self, font=FONT_MAIN, width=30)
        self.entries["ssid"].grid(row=row, column=1, padx=5, pady=4)
        self.entries["ssid"].insert(0, cfg["ssid"])
        row += 1

        add_label("Password:")
        self.entries["password"] = tk.Entry(self, font=FONT_MAIN, width=30)
        self.entries["password"].grid(row=row, column=1, padx=5, pady=4)
        self.entries["password"].insert(0, cfg["password"])
        row += 1

        # Location
        add_label("Latitude:")
        self.entries["lat"] = tk.Entry(self, font=FONT_MAIN, width=30)
        self.entries["lat"].grid(row=row, column=1, padx=5, pady=4)
        self.entries["lat"].insert(0, str(cfg["lat"]))
        row += 1

        add_label("Longitude:")
        self.entries["lon"] = tk.Entry(self, font=FONT_MAIN, width=30)
        self.entries["lon"].grid(row=row, column=1, padx=5, pady=4)
        self.entries["lon"].insert(0, str(cfg["lon"]))
        row += 1

        # APRS_Data
        add_label("Server:")
        self.entries["server"] = tk.Entry(self, font=FONT_MAIN, width=30)
        self.entries["server"].grid(row=row, column=1, padx=5, pady=4)
        self.entries["server"].insert(0, cfg["server"])
        row += 1

        add_label("Port:")
        self.entries["port"] = tk.Entry(self, font=FONT_MAIN, width=30)
        self.entries["port"].grid(row=row, column=1, padx=5, pady=4)
        self.entries["port"].insert(0, str(cfg["port"]))
        row += 1

        add_label("Interval (min):")
        self.entries["interval"] = tk.Entry(self, font=FONT_MAIN, width=30)
        self.entries["interval"].grid(row=row, column=1, padx=5, pady=4)
        self.entries["interval"].insert(0, str(cfg["interval"]))
        row += 1

        add_label("Comment:")
        # Multiline Text for Comment
        self.entries["comment"] = tk.Text(self, font=FONT_MAIN, height=4, width=40, bg=BG_COLOR, fg=FG_COLOR, insertbackground="white")
        self.entries["comment"].grid(row=row, column=1, padx=5, pady=4)
        self.entries["comment"].insert("1.0", cfg["comment"])
        row += 1

        add_label("Symbol:")
        self.symbol_cb = ttk.Combobox(self, values=SYMBOL_LIST, font=FONT_MAIN, state="readonly", width=28)
        self.symbol_cb.grid(row=row, column=1, padx=5, pady=4)
        self.symbol_cb.set(cfg["symbol"])
        row += 1


        add_label("Autostart:")
        self.autostart_var = tk.IntVar()
        self.autostart_var.set(1 if cfg["autostart"] else 0)
        self.chk_autostart = tk.Checkbutton(
            self, variable=self.autostart_var,
            onvalue=1, offvalue=0,
            bg=BG_COLOR, fg=FG_COLOR,
            selectcolor="#555555",   # jasno vidi kvačicu
            font=FONT_MAIN,
            activebackground=BG_COLOR, activeforeground=FG_COLOR
        )
        self.chk_autostart.grid(row=row, column=1, sticky="w", padx=5, pady=4)
        row += 1

        # Buttons
        btn_frame = tk.Frame(self, bg=BG_COLOR)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=10)

        tk.Button(btn_frame, text="Save", command=self.save, font=FONT_MAIN, width=12, bg=BTN_COLOR, fg=FG_COLOR, activebackground=BTN_ACTIVE, activeforeground=FG_COLOR, relief="flat").pack(side="left", padx=10)
        tk.Button(btn_frame, text="Cancel", command=self.destroy, font=FONT_MAIN, width=12, bg=BTN_COLOR, fg=FG_COLOR, activebackground=BTN_ACTIVE, activeforeground=FG_COLOR, relief="flat").pack(side="left", padx=10)

    def save(self):
        # Update cfg with entries
        try:
            self.cfg["call"] = self.entries["call"].get()
            self.cfg["ssid"] = self.entries["ssid"].get()
            self.cfg["password"] = self.entries["password"].get()
            self.cfg["lat"] = float(self.entries["lat"].get())
            self.cfg["lon"] = float(self.entries["lon"].get())
            self.cfg["server"] = self.entries["server"].get()
            self.cfg["port"] = int(self.entries["port"].get())
            self.cfg["interval"] = int(self.entries["interval"].get())
            self.cfg["comment"] = self.entries["comment"].get("1.0", tk.END).strip()
            self.cfg["symbol"] = self.symbol_cb.get()
            self.cfg["autostart"] = bool(self.autostart_var.get())
        except Exception as e:
            messagebox.showerror("Error", f"Invalid value: {e}")
            return

        save_config(self.cfg)
        self.save_callback(self.cfg)  # update main GUI
        self.destroy()

if __name__ == "__main__":
    app = APRSGUI()
    app.mainloop()
