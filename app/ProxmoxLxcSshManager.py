import json
import os
import queue
import re
import shutil
import subprocess
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk


APP_VERSION = "0.5.0"
APP_TITLE = f"Proxmox LXC SSH Manager v{APP_VERSION}"
OUTPUT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = OUTPUT_DIR / "ProxmoxLxcSshManager.config.json"
DEFAULT_HOSTS = [
    {"address": "192.168.1.100", "user": "root", "port": 22},
    {"address": "192.168.1.101", "user": "root", "port": 22},
]
DEFAULT_PUBLIC_KEY = Path.home() / ".ssh" / "id_ed25519.pub"
DEFAULT_REMOTE_KEY_NAME = "proxmox_lxc_access.pub"
DEFAULT_SETTINGS = {
    "hosts": DEFAULT_HOSTS,
    "public_key": str(DEFAULT_PUBLIC_KEY),
    "remote_key_name": DEFAULT_REMOTE_KEY_NAME,
    "lxc_user": "root",
    "lxc_ip_prefixes": ["192.168.1."],
    "remote_key_directory": "/root",
    "connect_timeout_seconds": 8,
    "output_directory": "../shortcuts",
    "dry_run": False,
}

DISCOVER_SCRIPT = r'''set -u
for ct in $(pct list 2>/dev/null | awk 'NR > 1 {print $1}'); do
    status=$(pct status "$ct" 2>/dev/null || true)
    status=${status#status: }
    name=$(pct config "$ct" 2>/dev/null | sed -n 's/^hostname: //p')
    [ -z "$name" ] && name="lxc-$ct"
    ip=""
    if [ "$status" = "running" ]; then
        addresses=$(pct exec "$ct" -- hostname -I 2>/dev/null || true)
        if [ -z "$addresses" ]; then
            addresses=$(pct exec "$ct" -- ip -o -4 addr show 2>/dev/null | awk '$3 == "inet" {sub(/\/.*/, "", $4); print $4}' || true)
        fi
        for address in $addresses; do
            case "$address" in
                __LXC_IP_PATTERNS__) ip="$address"; break ;;
            esac
        done
    fi
    printf '%s|%s|%s|%s\n' "$ct" "$name" "$status" "$ip"
done
'''

CONFIGURE_SCRIPT = r'''set -u
public_key_file=__REMOTE_KEY_PATH__
if [ ! -s "$public_key_file" ]; then
    echo "ERROR: Public key is missing or empty: $public_key_file" >&2
    exit 2
fi

failed=0
for ct in __SELECTED_CT_IDS__; do
    name=$(pct config "$ct" 2>/dev/null | sed -n 's/^hostname: //p')
    [ -z "$name" ] && name="lxc-$ct"
    echo "=== LXC $ct ($name) ==="

    status=$(pct status "$ct" 2>/dev/null || true)
    if [ "$status" != "status: running" ]; then
        echo "ERROR: LXC $ct ($name) is not running." >&2
        failed=1
        continue
    fi

    if ! pct push "$ct" "$public_key_file" /tmp/proxmox_lxc_access_key.pub; then
        echo "ERROR: Could not copy the public key to LXC $ct." >&2
        failed=1
        continue
    fi

    if pct exec "$ct" -- bash -s <<'LXC_SCRIPT'
set -eu
key_file=/tmp/proxmox_lxc_access_key.pub
trap 'rm -f "$key_file"' EXIT

if ! command -v sshd >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache openssh
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y openssh-server
    else
        echo "ERROR: sshd is missing and no supported package manager was found (apt-get, apk, dnf)." >&2
        exit 3
    fi
fi

install -d -o root -g root -m 700 /root/.ssh
touch /root/.ssh/authorized_keys
public_key=$(cat "$key_file")
grep -qxF "$public_key" /root/.ssh/authorized_keys || printf '%s\n' "$public_key" >> /root/.ssh/authorized_keys
chown root:root /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now ssh 2>/dev/null || systemctl enable --now sshd
elif command -v rc-update >/dev/null 2>&1 && command -v rc-service >/dev/null 2>&1; then
    rc-update add sshd default >/dev/null 2>&1 || true
    rc-service sshd start
else
    echo "ERROR: no supported service manager was found (systemd or OpenRC)." >&2
    exit 4
fi
LXC_SCRIPT
    then
        echo "OK: SSH access configured for LXC $ct ($name)."
    else
        echo "ERROR: SSH configuration failed for LXC $ct ($name)." >&2
        failed=1
    fi
done
exit "$failed"
'''


def load_settings():
    if not CONFIG_FILE.exists():
        settings = DEFAULT_SETTINGS.copy()
        settings["hosts"] = DEFAULT_HOSTS.copy()
        save_settings(settings)
        return settings

    try:
        settings = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if "lxc_ip_prefixes" not in settings and "lxc_ip_prefix" in settings:
            settings["lxc_ip_prefixes"] = [settings.pop("lxc_ip_prefix")]
        merged = DEFAULT_SETTINGS.copy()
        merged.update(settings)
        hosts = merged["hosts"]
        legacy_user = str(settings.get("proxmox_user", "root"))
        if not isinstance(hosts, list):
            raise ValueError("Pole hosts musi być listą.")
        normalized_hosts = []
        for host in hosts:
            profile = {"address": host, "user": legacy_user, "port": 22} if isinstance(host, str) else dict(host)
            address = str(profile.get("address", "")).strip()
            user = str(profile.get("user", legacy_user)).strip()
            port = int(profile.get("port", 22))
            name = str(profile.get("name", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9._:-]+", address):
                raise ValueError(f"Nieprawidłowy adres hosta: {address}")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", user):
                raise ValueError(f"Nieprawidłowy użytkownik hosta: {user}")
            if not 1 <= port <= 65535:
                raise ValueError(f"Nieprawidłowy port hosta: {port}")
            normalized = {"address": address, "user": user, "port": port}
            if name:
                normalized["name"] = name
            normalized_hosts.append(normalized)
        merged["hosts"] = normalized_hosts
        merged.pop("proxmox_user", None)
        return merged
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Nie można odczytać konfiguracji {CONFIG_FILE}: {error}") from error


def save_settings(settings):
    CONFIG_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_ssh_script(host, script, user="root", port=22, timeout=8):
    command = [
        "ssh.exe", "-T", "-p", str(port), "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
        f"{user}@{host}", "bash -s",
    ]
    return subprocess.run(
        command,
        input=script.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def check_ssh_access(host, user="root", timeout=8, accept_new=False):
    host_key_policy = "accept-new" if accept_new else "yes"
    command = [
        "ssh.exe", "-T", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
        "-o", "ConnectionAttempts=1", "-o", f"StrictHostKeyChecking={host_key_policy}",
        f"{user}@{host}", "exit",
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = result.stdout.decode("utf-8", errors="replace")
    if result.returncode == 0:
        return "działa", output
    lowered = output.lower()
    if "host key verification failed" in lowered or "no host key is known" in lowered:
        return "wymaga zaufania", output
    if "permission denied" in lowered:
        return "brak autoryzacji", output
    return "niedostępny", output


def safe_filename_part(value):
    value = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", value).rstrip(" .")
    return value or "unnamed"


class HostDialog(simpledialog.Dialog):
    def __init__(self, parent, title, initial=None):
        self.initial = initial or {"address": "", "user": "root", "port": 22}
        self.result = None
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text="Adres IP lub DNS:").grid(row=0, column=0, sticky="w", padx=5, pady=4)
        ttk.Label(master, text="Użytkownik SSH:").grid(row=1, column=0, sticky="w", padx=5, pady=4)
        ttk.Label(master, text="Port SSH:").grid(row=2, column=0, sticky="w", padx=5, pady=4)
        self.address_entry = ttk.Entry(master, width=35)
        self.user_entry = ttk.Entry(master, width=35)
        self.port_entry = ttk.Entry(master, width=35)
        self.address_entry.grid(row=0, column=1, padx=5, pady=4)
        self.user_entry.grid(row=1, column=1, padx=5, pady=4)
        self.port_entry.grid(row=2, column=1, padx=5, pady=4)
        self.address_entry.insert(0, self.initial["address"])
        self.user_entry.insert(0, self.initial["user"])
        self.port_entry.insert(0, str(self.initial["port"]))
        return self.address_entry

    def validate(self):
        address = self.address_entry.get().strip()
        user = self.user_entry.get().strip()
        try:
            port = int(self.port_entry.get().strip())
        except ValueError:
            messagebox.showerror(APP_TITLE, "Port SSH musi być liczbą.", parent=self)
            return False
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", address):
            messagebox.showerror(APP_TITLE, "Adres hosta zawiera niedozwolone znaki.", parent=self)
            return False
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", user):
            messagebox.showerror(APP_TITLE, "Nieprawidłowa nazwa użytkownika SSH.", parent=self)
            return False
        if not 1 <= port <= 65535:
            messagebox.showerror(APP_TITLE, "Port SSH musi mieścić się w zakresie 1-65535.", parent=self)
            return False
        self.result = {"address": address, "user": user, "port": port}
        if address == self.initial.get("address") and self.initial.get("name"):
            self.result["name"] = self.initial["name"]
        return True


class ProxmoxManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x850")
        self.minsize(820, 700)
        self.log_queue = queue.Queue()
        self.worker_running = False
        self.container_records = {}
        self.loaded_containers = []
        self.loaded_hosts = set()
        self.settings = load_settings()
        self.hosts = self.settings["hosts"]
        self.key_path = tk.StringVar(value=str(self.settings["public_key"]))
        self.remote_key_name = tk.StringVar(value=str(self.settings["remote_key_name"]))
        self.lxc_user = tk.StringVar(value=str(self.settings["lxc_user"]))
        self.lxc_ip_prefixes = tk.StringVar(value=", ".join(self.settings["lxc_ip_prefixes"]))
        self.remote_key_directory = tk.StringVar(value=str(self.settings["remote_key_directory"]))
        self.connect_timeout = tk.StringVar(value=str(self.settings["connect_timeout_seconds"]))
        self.output_directory = tk.StringVar(value=str(self.settings["output_directory"]))
        self.dry_run = tk.BooleanVar(value=bool(self.settings.get("dry_run", False)))
        self.status = tk.StringVar(value="Gotowy")
        self.container_count = tk.StringVar(value="Załadowane kontenery: 0")
        self.container_filter = tk.StringVar(value="Wszystkie")
        self.container_search = tk.StringVar()
        self.progress_text = tk.StringVar()
        self._build_ui()
        self._refresh_hosts()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._drain_log_queue)

    def _build_ui(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=2, minsize=230)
        main.rowconfigure(5, weight=1)

        hosts_frame = ttk.LabelFrame(main, text="Hosty Proxmox", padding=8)
        hosts_frame.grid(row=0, column=0, sticky="nsew")
        hosts_frame.columnconfigure(0, weight=1)
        hosts_frame.rowconfigure(0, weight=1)

        self.host_list = tk.Listbox(hosts_frame, selectmode=tk.EXTENDED, height=6)
        self.host_list.grid(row=0, column=0, rowspan=6, sticky="nsew", padx=(0, 8))
        ttk.Button(hosts_frame, text="Dodaj host", command=self.add_host).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Button(hosts_frame, text="Edytuj host", command=self.edit_host).grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Button(hosts_frame, text="Usuń host", command=self.remove_hosts).grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Button(hosts_frame, text="Zaznacz wszystkie", command=self.select_all).grid(row=3, column=1, sticky="ew", pady=2)
        ttk.Button(hosts_frame, text="Załaduj kontenery", command=lambda: self.start_task(self.load_containers)).grid(row=4, column=1, sticky="ew", pady=2)
        ttk.Button(hosts_frame, text="Testuj hosty", command=lambda: self.start_task(self.test_hosts)).grid(row=5, column=1, sticky="ew", pady=2)

        key_frame = ttk.LabelFrame(main, text="Klucz publiczny SSH", padding=8)
        key_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        key_frame.columnconfigure(0, weight=1)
        ttk.Entry(key_frame, textvariable=self.key_path).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(key_frame, text="Wybierz plik…", command=self.choose_key).grid(row=0, column=1)
        ttk.Label(key_frame, text="Nazwa na hoście Proxmox:").grid(row=1, column=0, sticky="w", pady=(8, 2))
        ttk.Entry(key_frame, textvariable=self.remote_key_name).grid(row=2, column=0, columnspan=2, sticky="ew")

        settings_frame = ttk.LabelFrame(main, text="Ustawienia połączeń i wyników", padding=8)
        settings_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(3, weight=1)

        ttk.Label(settings_frame, text="Użytkownik LXC:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(settings_frame, textvariable=self.lxc_user).grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=2)
        ttk.Label(settings_frame, text="Dane Proxmox:").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=2)
        ttk.Label(settings_frame, text="ustawiane osobno przy każdym hoście").grid(row=0, column=3, sticky="w", pady=2)

        ttk.Label(settings_frame, text="Prefiksy IP kontenerów:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(settings_frame, textvariable=self.lxc_ip_prefixes).grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=2)
        ttk.Label(settings_frame, text="Timeout SSH [s]:").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(settings_frame, textvariable=self.connect_timeout).grid(row=1, column=3, sticky="ew", pady=2)

        ttk.Label(
            settings_frame,
            text="Oddziel przecinkami, średnikami lub spacjami, np. 192.168.0., 10.20.0. — nie muszą być zgodne z siecią hosta Proxmox.",
            foreground="#555555",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(0, 4))

        ttk.Label(settings_frame, text="Katalog klucza na Proxmox:").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(settings_frame, textvariable=self.remote_key_directory).grid(row=3, column=1, columnspan=3, sticky="ew", pady=2)

        ttk.Label(settings_frame, text="Katalog skrótów BAT:").grid(row=4, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(settings_frame, textvariable=self.output_directory).grid(row=4, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=2)
        ttk.Button(settings_frame, text="Wybierz katalog…", command=self.choose_output_directory).grid(row=4, column=3, sticky="ew", pady=2)

        containers_frame = ttk.LabelFrame(main, text="Kontenery — zaznacz LXC do obsługi", padding=8)
        containers_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        containers_frame.columnconfigure(0, weight=1)
        containers_frame.rowconfigure(1, weight=1)
        filter_frame = ttk.Frame(containers_frame)
        filter_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        filter_frame.columnconfigure(1, weight=1)
        ttk.Label(filter_frame, text="Szukaj:").grid(row=0, column=0, padx=(0, 6))
        search_entry = ttk.Entry(filter_frame, textvariable=self.container_search)
        search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        ttk.Label(filter_frame, text="Filtr:").grid(row=0, column=2, padx=(0, 6))
        filter_box = ttk.Combobox(
            filter_frame,
            textvariable=self.container_filter,
            values=(
                "Wszystkie", "Uruchomione", "SSH działa", "Wymaga zaufania",
                "Brak autoryzacji", "SSH niedostępne", "Nie sprawdzono", "Bez BAT",
            ),
            state="readonly",
            width=15,
        )
        filter_box.grid(row=0, column=3)
        search_entry.bind("<KeyRelease>", lambda _event: self.apply_container_filter())
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self.apply_container_filter())
        style = ttk.Style(self)
        style.configure("Containers.Treeview", foreground="#000000", background="#ffffff", fieldbackground="#ffffff", rowheight=22)
        style.map("Containers.Treeview", foreground=[("selected", "#ffffff")], background=[("selected", "#0078d7")])
        self.container_tree = ttk.Treeview(
            containers_frame,
            columns=("host", "ct", "name", "status", "ip", "ssh", "bat"),
            show="headings",
            selectmode="extended",
            height=8,
            style="Containers.Treeview",
        )
        headings = {
            "host": ("Host Proxmox", 145),
            "ct": ("CTID", 60),
            "name": ("Nazwa LXC", 220),
            "status": ("Status", 80),
            "ip": ("Adres IP", 140),
            "ssh": ("SSH", 115),
            "bat": ("BAT", 55),
        }
        for column, (label, width) in headings.items():
            self.container_tree.heading(column, text=label)
            self.container_tree.column(column, width=width, anchor="w")
        container_scroll = ttk.Scrollbar(containers_frame, orient="vertical", command=self.container_tree.yview)
        self.container_tree.configure(yscrollcommand=container_scroll.set)
        self.container_tree.grid(row=1, column=0, sticky="nsew")
        container_scroll.grid(row=1, column=1, sticky="ns")
        container_footer = ttk.Frame(containers_frame)
        container_footer.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        container_footer.columnconfigure(0, weight=1)
        ttk.Label(container_footer, textvariable=self.container_count).grid(row=0, column=0, sticky="w")
        ttk.Button(container_footer, text="Sprawdź SSH", command=lambda: self.start_task(self.check_container_ssh, require_containers=True)).grid(row=0, column=1, padx=4)
        ttk.Button(container_footer, text="Zaufaj nowym kluczom", command=lambda: self.start_task(self.trust_container_host_keys, require_containers=True)).grid(row=0, column=2, padx=4)
        ttk.Button(container_footer, text="Zaznacz widoczne LXC", command=self.select_all_containers).grid(row=0, column=3, sticky="e")

        actions = ttk.LabelFrame(main, text="Operacje", padding=8)
        actions.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        for column in range(6):
            actions.columnconfigure(column, weight=1)

        self.action_buttons = [
            ttk.Button(actions, text="0. Wygeneruj klucz SSH", command=lambda: self.start_task(self.generate_ssh_key, require_hosts=False)),
            ttk.Button(actions, text="1. Wyślij klucz na hosty", command=lambda: self.start_task(self.upload_keys)),
            ttk.Button(actions, text="2. Skonfiguruj SSH w LXC", command=lambda: self.start_task(self.configure_lxc, require_containers=True)),
            ttk.Button(actions, text="3. Generuj skróty BAT", command=lambda: self.start_task(self.generate_shortcuts, require_containers=True)),
            ttk.Button(actions, text="4. Archiwizuj stare BAT", command=self.confirm_archive_stale_shortcuts),
            ttk.Button(actions, text="Wykonaj wszystko", command=lambda: self.start_task(self.run_all, require_containers=True)),
        ]
        for column, button in enumerate(self.action_buttons):
            button.grid(row=0, column=column, sticky="ew", padx=3)
        ttk.Checkbutton(
            actions,
            text="Tryb podglądu — nie wprowadzaj zmian",
            variable=self.dry_run,
        ).grid(row=1, column=0, columnspan=6, sticky="w", padx=3, pady=(8, 0))

        log_frame = ttk.LabelFrame(main, text="Dziennik", padding=8)
        log_frame.grid(row=5, column=0, sticky="nsew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_box = tk.Text(log_frame, wrap="word", state="disabled", font=("Consolas", 9), height=8)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scrollbar.set)
        self.log_box.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        status_frame = ttk.Frame(main)
        status_frame.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.status, anchor="w").grid(row=0, column=0, sticky="ew")
        self.progress_bar = ttk.Progressbar(status_frame, mode="determinate", length=220)
        self.progress_bar.grid(row=0, column=1, padx=(8, 6))
        ttk.Label(status_frame, textvariable=self.progress_text, width=14, anchor="e").grid(row=0, column=2)

    def _refresh_hosts(self):
        self.host_list.delete(0, tk.END)
        for host in self.hosts:
            self.host_list.insert(tk.END, self.host_label(host))
        self.select_all()
        if hasattr(self, "container_tree"):
            self.container_tree.delete(*self.container_tree.get_children())
            self.container_records.clear()
            self.loaded_containers.clear()
            self.loaded_hosts.clear()
            self.container_count.set("Załadowane kontenery: 0")

    def _persist(self):
        self.settings["hosts"] = self.hosts
        self.settings["public_key"] = self.key_path.get().strip()
        self.settings["remote_key_name"] = self.remote_key_name.get().strip()
        self.settings.pop("proxmox_user", None)
        self.settings["lxc_user"] = self.lxc_user.get().strip()
        self.settings["lxc_ip_prefixes"] = self.validated_ip_prefixes()
        self.settings.pop("lxc_ip_prefix", None)
        self.settings["remote_key_directory"] = self.remote_key_directory.get().strip()
        self.settings["connect_timeout_seconds"] = self.connect_timeout.get().strip()
        self.settings["output_directory"] = self.output_directory.get().strip()
        self.settings["dry_run"] = self.dry_run.get()
        save_settings(self.settings)

    def on_close(self):
        self._persist()
        self.destroy()

    def add_host(self):
        profile = HostDialog(self, "Dodaj host Proxmox").result
        if not profile:
            return
        if not any(host["address"] == profile["address"] for host in self.hosts):
            self.hosts.append(profile)
            self._persist()
            self._refresh_hosts()
        else:
            messagebox.showwarning(APP_TITLE, "Host o tym adresie już istnieje.", parent=self)

    def edit_host(self):
        indexes = list(self.host_list.curselection())
        if len(indexes) != 1:
            messagebox.showwarning(APP_TITLE, "Zaznacz dokładnie jeden host do edycji.", parent=self)
            return
        index = indexes[0]
        profile = HostDialog(self, "Edytuj host Proxmox", self.hosts[index]).result
        if not profile:
            return
        if any(position != index and host["address"] == profile["address"] for position, host in enumerate(self.hosts)):
            messagebox.showwarning(APP_TITLE, "Host o tym adresie już istnieje.", parent=self)
            return
        self.hosts[index] = profile
        self._persist()
        self._refresh_hosts()

    def remove_hosts(self):
        indexes = list(self.host_list.curselection())
        if not indexes:
            return
        for index in reversed(indexes):
            del self.hosts[index]
        self._persist()
        self._refresh_hosts()

    def select_all(self):
        self.host_list.selection_set(0, tk.END)

    def select_all_containers(self):
        self.container_tree.selection_set(self.container_tree.get_children())

    def apply_container_filter(self):
        phrase = self.container_search.get().strip().lower()
        selected_filter = self.container_filter.get()
        visible = []
        for record in self.loaded_containers:
            searchable = " ".join(
                str(record.get(key, ""))
                for key in ("host", "host_display", "ct", "name", "status", "ip", "ssh")
            ).lower()
            if phrase and phrase not in searchable:
                continue
            if selected_filter == "Uruchomione" and record["status"] != "running":
                continue
            if selected_filter == "SSH działa" and record.get("ssh") != "działa":
                continue
            if selected_filter == "Wymaga zaufania" and record.get("ssh") != "wymaga zaufania":
                continue
            if selected_filter == "Brak autoryzacji" and record.get("ssh") != "brak autoryzacji":
                continue
            if selected_filter == "SSH niedostępne" and record.get("ssh") not in {"niedostępny", "błąd testu"}:
                continue
            if selected_filter == "Nie sprawdzono" and record.get("ssh") != "nie sprawdzono":
                continue
            if selected_filter == "Bez BAT" and record.get("bat"):
                continue
            visible.append(record)
        self._render_container_records(visible)

    def choose_key(self):
        selected = filedialog.askopenfilename(
            parent=self,
            title="Wybierz klucz publiczny SSH",
            initialdir=str(DEFAULT_PUBLIC_KEY.parent),
            initialfile=DEFAULT_PUBLIC_KEY.name,
            filetypes=[("Klucze publiczne", "*.pub"), ("Wszystkie pliki", "*.*")],
        )
        if selected:
            self.key_path.set(selected)
            self._persist()

    def choose_output_directory(self):
        current = self.configured_output_directory()
        selected = filedialog.askdirectory(
            parent=self,
            title="Wybierz katalog dla skrótów BAT",
            initialdir=str(current),
        )
        if selected:
            self.output_directory.set(selected)
            self._persist()

    def selected_hosts(self):
        return [self.hosts[index] for index in self.host_list.curselection()]

    @staticmethod
    def host_label(host):
        connection = f"{host['user']}@{host['address']}:{host['port']}"
        return f"{host['name']} — {connection}" if host.get("name") else connection

    def refresh_host_labels(self):
        selected = set(self.host_list.curselection())
        self.host_list.delete(0, tk.END)
        for index, host in enumerate(self.hosts):
            self.host_list.insert(tk.END, self.host_label(host))
            if index in selected:
                self.host_list.selection_set(index)

    @staticmethod
    def host_address(host):
        return host["address"]

    def selected_containers(self):
        return [self.container_records[item] for item in self.container_tree.selection()]

    def confirm_archive_stale_shortcuts(self):
        if self.worker_running:
            return
        hosts = self.selected_hosts()
        if not hosts:
            messagebox.showwarning(APP_TITLE, "Zaznacz co najmniej jeden host.", parent=self)
            return
        if not self.loaded_containers:
            messagebox.showwarning(APP_TITLE, "Najpierw załaduj kontenery z wybranych hostów.", parent=self)
            return
        missing_hosts = {self.host_address(host) for host in hosts} - self.loaded_hosts
        if missing_hosts:
            messagebox.showwarning(
                APP_TITLE,
                "Odśwież listę kontenerów dla wszystkich wybranych hostów przed archiwizacją.",
                parent=self,
            )
            return
        stale = self.find_stale_shortcuts(hosts)
        if not stale:
            messagebox.showinfo(APP_TITLE, "Nie znaleziono nieaktualnych skrótów BAT dla wybranych hostów.", parent=self)
            return
        names = "\n".join(f"• {path.name}" for path in stale[:12])
        if len(stale) > 12:
            names += f"\n… i jeszcze {len(stale) - 12}"
        confirmed = messagebox.askyesno(
            APP_TITLE,
            f"Znaleziono {len(stale)} nieaktualnych skrótów:\n\n{names}\n\n"
            "Przenieść je do podfolderu _archive?",
            parent=self,
        )
        if confirmed:
            self.start_task(self.archive_stale_shortcuts)

    def start_task(self, operation, require_hosts=True, require_containers=False):
        if self.worker_running:
            return
        hosts = self.selected_hosts()
        if require_hosts and not hosts:
            messagebox.showwarning(APP_TITLE, "Zaznacz co najmniej jeden host.", parent=self)
            return
        containers = self.selected_containers()
        if require_containers and not containers:
            messagebox.showwarning(
                APP_TITLE,
                "Najpierw załaduj kontenery i zaznacz co najmniej jeden LXC.",
                parent=self,
            )
            return
        self._persist()
        self.worker_running = True
        self.status.set("Praca w toku…")
        self.progress_bar.configure(value=0, maximum=1)
        self.progress_text.set("")
        for button in self.action_buttons:
            button.configure(state="disabled")

        def worker():
            try:
                if require_containers:
                    operation(hosts, containers)
                else:
                    operation(hosts)
            except Exception as error:
                self.log(f"BŁĄD: {error}")
            finally:
                self.log_queue.put(("finished", None))

        threading.Thread(target=worker, daemon=True).start()

    def log(self, message=""):
        self.log_queue.put(("log", str(message)))

    def _drain_log_queue(self):
        try:
            while True:
                kind, value = self.log_queue.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert(tk.END, value + "\n")
                    self.log_box.see(tk.END)
                    self.log_box.configure(state="disabled")
                elif kind == "finished":
                    self.worker_running = False
                    self.status.set("Gotowy")
                    for button in self.action_buttons:
                        button.configure(state="normal")
                elif kind == "containers":
                    self.show_container_records(value)
                elif kind == "refresh_containers":
                    self.apply_container_filter()
                elif kind == "progress":
                    current, total, label = value
                    self.progress_bar.configure(maximum=max(total, 1), value=current)
                    self.progress_text.set(label or f"{current}/{total}")
                elif kind == "host_labels":
                    self.refresh_host_labels()
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def load_containers(self, hosts):
        timeout = self.validated_timeout()
        ip_prefixes = self.validated_ip_prefixes()
        ip_patterns = "|".join(f"{prefix}*" for prefix in ip_prefixes)
        discover_script = DISCOVER_SCRIPT.replace("__LXC_IP_PATTERNS__", ip_patterns)
        records = []

        for host_index, host_profile in enumerate(hosts, start=1):
            host = self.host_address(host_profile)
            self.set_progress(host_index - 1, len(hosts), f"{host_index - 1}/{len(hosts)}")
            self.log(f"[{host}] Ładowanie listy kontenerów…")
            result = run_ssh_script(host, discover_script, host_profile["user"], host_profile["port"], timeout)
            output = result.stdout.decode("utf-8", errors="replace")
            if result.returncode:
                if output.strip():
                    self.log(f"[{host}] {output.strip()}")
                raise RuntimeError(f"Odczyt LXC z {host} zakończył się kodem {result.returncode}.")

            for row in output.splitlines():
                match = re.fullmatch(r"(\d+)\|([^|]+)\|([^|]+)\|(\d+\.\d+\.\d+\.\d+)?", row.strip())
                if not match:
                    if row.strip():
                        self.log(f"[{host}] Pominięto nieznaną odpowiedź: {row}")
                    continue
                ct_id, name, status, ip = match.groups()
                record = {
                    "host": host,
                    "host_display": host_profile.get("name", host),
                    "ct": ct_id,
                    "name": name,
                    "status": status,
                    "ip": ip or "",
                    "ssh": "nie sprawdzono" if status == "running" and ip else "—",
                }
                record["bat"] = self.shortcut_path_for(record).is_file()
                records.append(record)
            self.set_progress(host_index, len(hosts), f"{host_index}/{len(hosts)}")

        self.log(f"Załadowano {len(records)} kontenerów. Zaznacz te, które chcesz obsłużyć.")
        self.loaded_hosts = {self.host_address(host) for host in hosts}
        self.log_queue.put(("containers", records))

    def test_hosts(self, hosts):
        timeout = self.validated_timeout()
        script = (
            "node_name=$(hostname -f 2>/dev/null || hostname 2>/dev/null || true)\n"
            "printf 'NODE_NAME|%s\\n' \"$node_name\"\n"
            "command -v pct >/dev/null || exit 10\n"
            "pveversion 2>/dev/null || echo 'Proxmox version unavailable'\n"
        )
        failures = 0
        names_changed = False
        for index, host_profile in enumerate(hosts, start=1):
            host = self.host_address(host_profile)
            self.set_progress(index - 1, len(hosts), f"{index - 1}/{len(hosts)}")
            self.log(f"[{host}] Test SSH i pct…")
            result = run_ssh_script(host, script, host_profile["user"], host_profile["port"], timeout)
            output_lines = result.stdout.decode("utf-8", errors="replace").splitlines()
            name_line = next((line for line in output_lines if line.startswith("NODE_NAME|")), "")
            discovered_name = name_line.partition("|")[2].strip()
            output = "\n".join(line for line in output_lines if not line.startswith("NODE_NAME|")).strip()
            if discovered_name and host_profile.get("name") != discovered_name:
                host_profile["name"] = discovered_name
                names_changed = True
                self.log(f"[{host}] Zapisano nazwę hosta: {discovered_name}")
            if result.returncode == 0:
                self.log(f"[{host}] OK — {output or 'SSH i pct dostępne'}")
            else:
                failures += 1
                self.log(f"[{host}] BŁĄD ({result.returncode}) — {output or 'brak odpowiedzi'}")
            self.set_progress(index, len(hosts), f"{index}/{len(hosts)}")
        if names_changed:
            self.settings["hosts"] = self.hosts
            save_settings(self.settings)
            self.log_queue.put(("host_labels", None))
        if failures:
            raise RuntimeError(f"Test nie powiódł się dla {failures} z {len(hosts)} hostów.")
        self.log("Wszystkie zaznaczone hosty przeszły test.")

    def check_container_ssh(self, _hosts, containers):
        self._check_container_ssh(containers, accept_new=False)

    def trust_container_host_keys(self, _hosts, containers):
        self.log("Akceptowanie wyłącznie nowych fingerprintów SSH; zmienione klucze nadal będą odrzucone.")
        self._check_container_ssh(containers, accept_new=True)

    def _check_container_ssh(self, containers, accept_new=False):
        lxc_user = self.validated_user("lxc_user")
        timeout = self.validated_timeout()
        candidates = [record for record in containers if record["status"] == "running" and record["ip"]]
        skipped = len(containers) - len(candidates)
        for record in containers:
            if record not in candidates:
                record["ssh"] = "—"
        if not candidates:
            self.log_queue.put(("refresh_containers", None))
            raise RuntimeError("Żaden zaznaczony kontener nie jest uruchomiony i nie ma pasującego adresu IP.")

        self.log(f"Sprawdzanie SSH w {len(candidates)} kontenerach…")
        completed = 0
        with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as executor:
            futures = {
                executor.submit(check_ssh_access, record["ip"], lxc_user, timeout, accept_new): record
                for record in candidates
            }
            for future in as_completed(futures):
                record = futures[future]
                try:
                    ssh_status, output = future.result()
                except Exception as error:
                    ssh_status, output = "błąd testu", str(error)
                record["ssh"] = ssh_status
                completed += 1
                self.set_progress(completed, len(candidates), f"{completed}/{len(candidates)}")
                self.log(f"[{record['host']}] LXC {record['ct']} ({record['name']}): SSH {ssh_status}")
                if output.strip() and ssh_status not in {"działa", "brak autoryzacji"}:
                    self.log(f"  {output.strip()}")
        self.log_queue.put(("refresh_containers", None))
        if skipped:
            self.log(f"Pominięto {skipped} zatrzymanych kontenerów lub rekordów bez adresu IP.")

    def shortcut_path_for(self, record):
        filename = (
            f"Proxmox-{safe_filename_part(record['host'])}-LXC-{record['ct']}-"
            f"{safe_filename_part(record['name'])}.bat"
        )
        return self.configured_output_directory() / filename

    def find_stale_shortcuts(self, hosts):
        output_dir = self.configured_output_directory()
        if not output_dir.is_dir():
            return []
        selected_hosts = {self.host_address(host) for host in hosts}
        expected = {
            self.shortcut_path_for(record).resolve()
            for record in self.loaded_containers
            if record["host"] in selected_hosts
        }
        candidates = []
        for host in selected_hosts:
            pattern = f"Proxmox-{safe_filename_part(host)}-LXC-*.bat"
            candidates.extend(output_dir.glob(pattern))
        return sorted(
            {path.resolve() for path in candidates if path.resolve() not in expected},
            key=lambda path: path.name.lower(),
        )

    def archive_stale_shortcuts(self, hosts):
        stale = self.find_stale_shortcuts(hosts)
        if not stale:
            self.log("Nie znaleziono nieaktualnych skrótów BAT.")
            return
        archive_dir = self.configured_output_directory() / "_archive" / datetime.now().strftime("%Y%m%d-%H%M%S")
        if self.dry_run.get():
            for source in stale:
                self.log(f"PODGLĄD: zostałby zarchiwizowany {source.name} -> {archive_dir}")
            self.log(f"PODGLĄD: zaplanowano archiwizację {len(stale)} nieaktualnych skrótów.")
            return
        archive_dir.mkdir(parents=True, exist_ok=True)
        for index, source in enumerate(stale, start=1):
            self.set_progress(index - 1, len(stale), f"{index - 1}/{len(stale)}")
            destination = archive_dir / source.name
            suffix = 1
            while destination.exists():
                destination = archive_dir / f"{source.stem}-{suffix}{source.suffix}"
                suffix += 1
            shutil.move(str(source), str(destination))
            self.log(f"Zarchiwizowano: {source.name} -> {archive_dir}")
            self.set_progress(index, len(stale), f"{index}/{len(stale)}")
        for record in self.loaded_containers:
            record["bat"] = self.shortcut_path_for(record).is_file()
        self.log_queue.put(("refresh_containers", None))
        self.log(f"Zarchiwizowano {len(stale)} nieaktualnych skrótów. Pliki można odzyskać z {archive_dir}")

    def show_container_records(self, records):
        self.loaded_containers = records
        self.apply_container_filter()

    def _render_container_records(self, records):
        self.container_tree.delete(*self.container_tree.get_children())
        self.container_records.clear()
        for record in records:
            item = self.container_tree.insert(
                "", tk.END,
                values=(
                    record.get("host_display", record["host"]), record["ct"], record["name"], record["status"],
                    record["ip"] or "—", record.get("ssh", "nie sprawdzono"),
                    "tak" if record.get("bat") else "nie",
                ),
            )
            self.container_records[item] = record
        self.container_count.set(f"Widoczne: {len(records)} / załadowane: {len(self.loaded_containers)}")
        children = self.container_tree.get_children()
        if children:
            self.container_tree.see(children[0])

    def set_progress(self, current, total, label=""):
        self.log_queue.put(("progress", (current, total, label)))

    def upload_keys(self, hosts):
        key = Path(os.path.expandvars(os.path.expanduser(self.key_path.get().strip())))
        remote_key_path = self.validated_remote_key_path()
        timeout = self.validated_timeout()
        if not self.dry_run.get():
            if not key.is_file():
                raise FileNotFoundError(f"Nie znaleziono klucza publicznego: {key}")
            if not key.read_bytes().strip():
                raise ValueError(f"Plik klucza jest pusty: {key}")

        self.log("Wysyłanie klucza publicznego. SCP może otworzyć okno do wpisania hasła.")
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        for host_profile in hosts:
            host = self.host_address(host_profile)
            self.log(f"[{host}] Wysyłanie {key.name} -> {remote_key_path}")
            if self.dry_run.get():
                self.log(f"[{host}] PODGLĄD: pominięto wysyłanie klucza.")
                continue
            result = subprocess.run(
                [
                    "scp.exe", "-P", str(host_profile["port"]), "-o", f"ConnectTimeout={timeout}",
                    str(key), f"{host_profile['user']}@{host}:{remote_key_path}",
                ],
                creationflags=flags,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(f"SCP do {host} zakończył się kodem {result.returncode}.")
            self.log(f"[{host}] Klucz wysłany poprawnie.")

    def generate_ssh_key(self, _hosts=None):
        public_key = Path(os.path.expandvars(os.path.expanduser(self.key_path.get().strip())))
        if public_key.suffix.lower() != ".pub":
            raise ValueError("Ścieżka klucza publicznego powinna kończyć się rozszerzeniem .pub.")
        private_key = public_key.with_suffix("")

        if public_key.exists():
            if not public_key.is_file() or not public_key.read_bytes().strip():
                raise ValueError(f"Klucz publiczny jest nieprawidłowy lub pusty: {public_key}")
            self.log(f"Klucz już istnieje — pozostawiono bez zmian: {public_key}")
            return
        if private_key.exists():
            raise FileExistsError(
                f"Istnieje klucz prywatny {private_key}, ale brakuje odpowiadającego pliku .pub. "
                "Program nie nadpisze istniejącego klucza."
            )

        if self.dry_run.get():
            self.log(f"PODGLĄD: zostałaby utworzona para kluczy Ed25519: {private_key}")
            return

        public_key.parent.mkdir(parents=True, exist_ok=True)
        username = os.environ.get("USERNAME", "user")
        computer = os.environ.get("COMPUTERNAME", "computer")
        comment = f"proxmox-lxc-{username}@{computer}"
        self.log(f"Generowanie pary Ed25519: {private_key}")
        result = subprocess.run(
            [
                "ssh-keygen.exe", "-t", "ed25519", "-f", str(private_key),
                "-N", "", "-C", comment,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        output = result.stdout.decode("utf-8", errors="replace").strip()
        if output:
            for line in output.splitlines():
                self.log(line)
        if result.returncode or not public_key.is_file():
            raise RuntimeError(f"Generowanie klucza zakończyło się kodem {result.returncode}.")
        self.log(f"Utworzono klucz prywatny: {private_key}")
        self.log(f"Utworzono klucz publiczny: {public_key}")

    def configure_lxc(self, _hosts, containers):
        remote_key_path = self.validated_remote_key_path()
        timeout = self.validated_timeout()
        profiles = {self.host_address(host): host for host in _hosts}
        grouped = {}
        for container in containers:
            grouped.setdefault(container["host"], []).append(container)

        for host_index, (host, host_containers) in enumerate(grouped.items(), start=1):
            host_profile = profiles[host]
            self.set_progress(host_index - 1, len(grouped), f"{host_index - 1}/{len(grouped)}")
            ct_ids = " ".join(container["ct"] for container in host_containers)
            configure_script = (
                CONFIGURE_SCRIPT
                .replace("__REMOTE_KEY_PATH__", remote_key_path)
                .replace("__SELECTED_CT_IDS__", ct_ids)
            )
            self.log(f"[{host}] Konfiguracja SSH w LXC: {ct_ids}")
            if self.dry_run.get():
                self.log(
                    f"[{host}] PODGLĄD: klucz zostałby dodany do LXC {ct_ids}; "
                    "sshd zostałby zainstalowany przez apt-get, apk lub dnf, jeśli go brakuje."
                )
                self.set_progress(host_index, len(grouped), f"{host_index}/{len(grouped)}")
                continue
            result = run_ssh_script(host, configure_script, host_profile["user"], host_profile["port"], timeout)
            output = result.stdout.decode("utf-8", errors="replace").strip()
            if output:
                for line in output.splitlines():
                    self.log(f"[{host}] {line}")
            if result.returncode:
                raise RuntimeError(f"Konfiguracja na {host} zakończyła się kodem {result.returncode}.")
            self.set_progress(host_index, len(grouped), f"{host_index}/{len(grouped)}")
        self.log("Konfiguracja SSH zakończona.")

    def generate_shortcuts(self, _hosts, containers):
        created = 0
        lxc_user = self.validated_user("lxc_user")
        output_dir = self.configured_output_directory()
        if not self.dry_run.get():
            output_dir.mkdir(parents=True, exist_ok=True)
        for index, container in enumerate(containers, start=1):
            self.set_progress(index - 1, len(containers), f"{index - 1}/{len(containers)}")
            host = container["host"]
            ct_id = container["ct"]
            name = container["name"]
            ip = container["ip"]
            if container["status"] != "running" or not ip:
                self.log(f"[{host}] Pominięto LXC {ct_id} ({name}): kontener nie działa lub nie ma pasującego IP.")
                self.set_progress(index, len(containers), f"{index}/{len(containers)}")
                continue
            filename = (
                f"Proxmox-{safe_filename_part(host)}-LXC-{ct_id}-"
                f"{safe_filename_part(name)}.bat"
            )
            title = f"{name} - SSH - LXC {ct_id} - {ip}".replace("'", "''")
            content = (
                "@echo off\r\n"
                f'start "" powershell.exe -NoExit -Command '
                f'"$Host.UI.RawUI.WindowTitle = \'{title}\'; ssh {lxc_user}@{ip}"\r\n'
            )
            if not self.dry_run.get():
                (output_dir / filename).write_text(content, encoding="ascii", errors="replace", newline="")
                container["bat"] = True
            created += 1
            prefix = "PODGLĄD: powstałby" if self.dry_run.get() else "Utworzono"
            self.log(f"{prefix}: {filename} -> {ip}")
            self.set_progress(index, len(containers), f"{index}/{len(containers)}")
        self.log_queue.put(("refresh_containers", None))
        action = "zaplanowano" if self.dry_run.get() else "utworzono"
        self.log(f"Gotowe: {action} {created} skrótów w {output_dir}")

    def run_all(self, hosts, containers):
        selected_addresses = {container["host"] for container in containers}
        target_hosts = [host for host in hosts if self.host_address(host) in selected_addresses]
        self.generate_ssh_key()
        self.upload_keys(target_hosts)
        self.configure_lxc(target_hosts, containers)
        self.check_container_ssh(target_hosts, containers)
        self.generate_shortcuts(target_hosts, containers)

    def validated_remote_key_name(self):
        name = self.remote_key_name.get().strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name in {".", ".."}:
            raise ValueError(
                "Nazwa klucza na hoście może zawierać tylko litery, cyfry, kropki, myślniki i podkreślenia."
            )
        return name

    def validated_remote_key_path(self):
        name = self.validated_remote_key_name()
        directory = str(self.settings["remote_key_directory"]).strip().rstrip("/")
        if not re.fullmatch(r"/[A-Za-z0-9._/-]+", directory) or ".." in directory.split("/"):
            raise ValueError("remote_key_directory w configu musi być bezpieczną ścieżką bezwzględną Unix.")
        return f"{directory}/{name}"

    def validated_user(self, setting_name):
        user = str(self.settings[setting_name]).strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", user):
            raise ValueError(f"Nieprawidłowa nazwa użytkownika w ustawieniu {setting_name}.")
        return user

    def validated_timeout(self):
        timeout = int(self.settings["connect_timeout_seconds"])
        if not 1 <= timeout <= 300:
            raise ValueError("connect_timeout_seconds musi mieścić się w zakresie 1-300.")
        return timeout

    def validated_ip_prefixes(self):
        raw = self.lxc_ip_prefixes.get() if hasattr(self, "lxc_ip_prefixes") else self.settings["lxc_ip_prefixes"]
        values = raw if isinstance(raw, list) else re.split(r"[,;\s]+", str(raw).strip())
        prefixes = []
        for value in values:
            prefix = str(value).strip()
            if not prefix:
                continue
            if not re.fullmatch(r"[0-9.]+", prefix):
                raise ValueError("Prefiksy LXC mogą zawierać tylko cyfry i kropki.")
            if prefix not in prefixes:
                prefixes.append(prefix)
        if not prefixes:
            raise ValueError("Podaj co najmniej jeden prefiks adresów LXC.")
        return prefixes

    def configured_output_directory(self):
        configured = Path(os.path.expandvars(os.path.expanduser(str(self.settings["output_directory"]))))
        return configured.resolve() if configured.is_absolute() else (OUTPUT_DIR / configured).resolve()


if __name__ == "__main__":
    ProxmoxManager().mainloop()
