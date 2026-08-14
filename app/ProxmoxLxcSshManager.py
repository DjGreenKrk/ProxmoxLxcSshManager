import json
import os
import queue
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk


APP_VERSION = "0.1.0"
APP_TITLE = f"Proxmox LXC SSH Manager v{APP_VERSION}"
OUTPUT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = OUTPUT_DIR / "ProxmoxLxcSshManager.config.json"
DEFAULT_HOSTS = ["192.168.1.100", "192.168.1.101"]
DEFAULT_PUBLIC_KEY = Path.home() / ".ssh" / "id_ed25519.pub"
DEFAULT_REMOTE_KEY_NAME = "proxmox_lxc_access.pub"
DEFAULT_SETTINGS = {
    "hosts": DEFAULT_HOSTS,
    "public_key": str(DEFAULT_PUBLIC_KEY),
    "remote_key_name": DEFAULT_REMOTE_KEY_NAME,
    "proxmox_user": "root",
    "lxc_user": "root",
    "lxc_ip_prefix": "192.168.1.",
    "remote_key_directory": "/root",
    "connect_timeout_seconds": 8,
    "output_directory": "../shortcuts",
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
        for address in $addresses; do
            case "$address" in
                __LXC_IP_PREFIX__*) ip="$address"; break ;;
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

    if ! pct push "$ct" "$public_key_file" /tmp/julek_key.pub; then
        echo "ERROR: Could not copy the public key to LXC $ct." >&2
        failed=1
        continue
    fi

    if pct exec "$ct" -- bash -s <<'LXC_SCRIPT'
set -eu
key_file=/tmp/julek_key.pub
trap 'rm -f "$key_file"' EXIT

if ! command -v sshd >/dev/null 2>&1; then
    if ! command -v apt-get >/dev/null 2>&1; then
        echo "ERROR: sshd is missing and this container does not use apt-get." >&2
        exit 3
    fi
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server
fi

install -d -o root -g root -m 700 /root/.ssh
touch /root/.ssh/authorized_keys
public_key=$(cat "$key_file")
grep -qxF "$public_key" /root/.ssh/authorized_keys || printf '%s\n' "$public_key" >> /root/.ssh/authorized_keys
chown root:root /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now ssh 2>/dev/null || systemctl enable --now sshd
else
    echo "ERROR: systemctl is unavailable; start the SSH service manually." >&2
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
        merged = DEFAULT_SETTINGS.copy()
        merged.update(settings)
        hosts = merged["hosts"]
        if not isinstance(hosts, list) or not all(isinstance(host, str) for host in hosts):
            raise ValueError("Pole hosts musi być listą tekstową.")
        return merged
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Nie można odczytać konfiguracji {CONFIG_FILE}: {error}") from error


def save_settings(settings):
    CONFIG_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_ssh_script(host, script, user="root", timeout=8):
    command = [
        "ssh.exe", "-T", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
        f"{user}@{host}", "bash -s",
    ]
    return subprocess.run(
        command,
        input=script.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def safe_filename_part(value):
    value = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", value).rstrip(" .")
    return value or "unnamed"


class ProxmoxManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x850")
        self.minsize(820, 700)
        self.log_queue = queue.Queue()
        self.worker_running = False
        self.container_records = {}
        self.settings = load_settings()
        self.hosts = self.settings["hosts"]
        self.key_path = tk.StringVar(value=str(self.settings["public_key"]))
        self.remote_key_name = tk.StringVar(value=str(self.settings["remote_key_name"]))
        self.proxmox_user = tk.StringVar(value=str(self.settings["proxmox_user"]))
        self.lxc_user = tk.StringVar(value=str(self.settings["lxc_user"]))
        self.lxc_ip_prefix = tk.StringVar(value=str(self.settings["lxc_ip_prefix"]))
        self.remote_key_directory = tk.StringVar(value=str(self.settings["remote_key_directory"]))
        self.connect_timeout = tk.StringVar(value=str(self.settings["connect_timeout_seconds"]))
        self.output_directory = tk.StringVar(value=str(self.settings["output_directory"]))
        self.status = tk.StringVar(value="Gotowy")
        self.container_count = tk.StringVar(value="Załadowane kontenery: 0")
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
        self.host_list.grid(row=0, column=0, rowspan=4, sticky="nsew", padx=(0, 8))
        ttk.Button(hosts_frame, text="Dodaj host", command=self.add_host).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Button(hosts_frame, text="Usuń host", command=self.remove_hosts).grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Button(hosts_frame, text="Zaznacz wszystkie", command=self.select_all).grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Button(hosts_frame, text="Załaduj kontenery", command=lambda: self.start_task(self.load_containers)).grid(row=3, column=1, sticky="ew", pady=2)

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

        ttk.Label(settings_frame, text="Użytkownik Proxmox:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(settings_frame, textvariable=self.proxmox_user).grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=2)
        ttk.Label(settings_frame, text="Użytkownik LXC:").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(settings_frame, textvariable=self.lxc_user).grid(row=0, column=3, sticky="ew", pady=2)

        ttk.Label(settings_frame, text="Prefiks adresów LXC:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(settings_frame, textvariable=self.lxc_ip_prefix).grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=2)
        ttk.Label(settings_frame, text="Timeout SSH [s]:").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(settings_frame, textvariable=self.connect_timeout).grid(row=1, column=3, sticky="ew", pady=2)

        ttk.Label(settings_frame, text="Katalog klucza na Proxmox:").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(settings_frame, textvariable=self.remote_key_directory).grid(row=2, column=1, columnspan=3, sticky="ew", pady=2)

        ttk.Label(settings_frame, text="Katalog skrótów BAT:").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(settings_frame, textvariable=self.output_directory).grid(row=3, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=2)
        ttk.Button(settings_frame, text="Wybierz katalog…", command=self.choose_output_directory).grid(row=3, column=3, sticky="ew", pady=2)

        containers_frame = ttk.LabelFrame(main, text="Kontenery — zaznacz LXC do obsługi", padding=8)
        containers_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        containers_frame.columnconfigure(0, weight=1)
        containers_frame.rowconfigure(0, weight=1)
        style = ttk.Style(self)
        style.configure("Containers.Treeview", foreground="#000000", background="#ffffff", fieldbackground="#ffffff", rowheight=22)
        style.map("Containers.Treeview", foreground=[("selected", "#ffffff")], background=[("selected", "#0078d7")])
        self.container_tree = ttk.Treeview(
            containers_frame,
            columns=("host", "ct", "name", "status", "ip"),
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
        }
        for column, (label, width) in headings.items():
            self.container_tree.heading(column, text=label)
            self.container_tree.column(column, width=width, anchor="w")
        container_scroll = ttk.Scrollbar(containers_frame, orient="vertical", command=self.container_tree.yview)
        self.container_tree.configure(yscrollcommand=container_scroll.set)
        self.container_tree.grid(row=0, column=0, sticky="nsew")
        container_scroll.grid(row=0, column=1, sticky="ns")
        container_footer = ttk.Frame(containers_frame)
        container_footer.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        container_footer.columnconfigure(0, weight=1)
        ttk.Label(container_footer, textvariable=self.container_count).grid(row=0, column=0, sticky="w")
        ttk.Button(container_footer, text="Zaznacz wszystkie LXC", command=self.select_all_containers).grid(row=0, column=1, sticky="e")

        actions = ttk.LabelFrame(main, text="Operacje", padding=8)
        actions.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        for column in range(5):
            actions.columnconfigure(column, weight=1)

        self.action_buttons = [
            ttk.Button(actions, text="0. Wygeneruj klucz SSH", command=lambda: self.start_task(self.generate_ssh_key, require_hosts=False)),
            ttk.Button(actions, text="1. Wyślij klucz na hosty", command=lambda: self.start_task(self.upload_keys)),
            ttk.Button(actions, text="2. Skonfiguruj SSH w LXC", command=lambda: self.start_task(self.configure_lxc, require_containers=True)),
            ttk.Button(actions, text="3. Generuj skróty BAT", command=lambda: self.start_task(self.generate_shortcuts, require_containers=True)),
            ttk.Button(actions, text="Wykonaj wszystko", command=lambda: self.start_task(self.run_all, require_containers=True)),
        ]
        for column, button in enumerate(self.action_buttons):
            button.grid(row=0, column=column, sticky="ew", padx=3)

        log_frame = ttk.LabelFrame(main, text="Dziennik", padding=8)
        log_frame.grid(row=5, column=0, sticky="nsew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_box = tk.Text(log_frame, wrap="word", state="disabled", font=("Consolas", 9), height=8)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scrollbar.set)
        self.log_box.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        ttk.Label(main, textvariable=self.status, anchor="w").grid(row=6, column=0, sticky="ew", pady=(8, 0))

    def _refresh_hosts(self):
        self.host_list.delete(0, tk.END)
        for host in self.hosts:
            self.host_list.insert(tk.END, host)
        self.select_all()
        if hasattr(self, "container_tree"):
            self.container_tree.delete(*self.container_tree.get_children())
            self.container_records.clear()
            self.container_count.set("Załadowane kontenery: 0")

    def _persist(self):
        self.settings["hosts"] = self.hosts
        self.settings["public_key"] = self.key_path.get().strip()
        self.settings["remote_key_name"] = self.remote_key_name.get().strip()
        self.settings["proxmox_user"] = self.proxmox_user.get().strip()
        self.settings["lxc_user"] = self.lxc_user.get().strip()
        self.settings["lxc_ip_prefix"] = self.lxc_ip_prefix.get().strip()
        self.settings["remote_key_directory"] = self.remote_key_directory.get().strip()
        self.settings["connect_timeout_seconds"] = self.connect_timeout.get().strip()
        self.settings["output_directory"] = self.output_directory.get().strip()
        save_settings(self.settings)

    def on_close(self):
        self._persist()
        self.destroy()

    def add_host(self):
        host = simpledialog.askstring("Dodaj host Proxmox", "Adres IP lub nazwa DNS hosta:", parent=self)
        if not host:
            return
        host = host.strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", host):
            messagebox.showerror(APP_TITLE, "Adres hosta zawiera niedozwolone znaki.", parent=self)
            return
        if host not in self.hosts:
            self.hosts.append(host)
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

    def selected_containers(self):
        return [self.container_records[item] for item in self.container_tree.selection()]

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
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def load_containers(self, hosts):
        proxmox_user = self.validated_user("proxmox_user")
        timeout = self.validated_timeout()
        ip_prefix = self.validated_ip_prefix()
        discover_script = DISCOVER_SCRIPT.replace("__LXC_IP_PREFIX__", ip_prefix)
        records = []

        for host in hosts:
            self.log(f"[{host}] Ładowanie listy kontenerów…")
            result = run_ssh_script(host, discover_script, proxmox_user, timeout)
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
                records.append({"host": host, "ct": ct_id, "name": name, "status": status, "ip": ip or ""})

        self.log(f"Załadowano {len(records)} kontenerów. Zaznacz te, które chcesz obsłużyć.")
        self.log_queue.put(("containers", records))

    def show_container_records(self, records):
        self.container_tree.delete(*self.container_tree.get_children())
        self.container_records.clear()
        for record in records:
            item = self.container_tree.insert(
                "", tk.END,
                values=(record["host"], record["ct"], record["name"], record["status"], record["ip"] or "—"),
            )
            self.container_records[item] = record
        self.container_count.set(f"Załadowane kontenery: {len(records)}")
        children = self.container_tree.get_children()
        if children:
            self.container_tree.see(children[0])

    def upload_keys(self, hosts):
        key = Path(os.path.expandvars(os.path.expanduser(self.key_path.get().strip())))
        remote_key_path = self.validated_remote_key_path()
        proxmox_user = self.validated_user("proxmox_user")
        timeout = self.validated_timeout()
        if not key.is_file():
            raise FileNotFoundError(f"Nie znaleziono klucza publicznego: {key}")
        if not key.read_bytes().strip():
            raise ValueError(f"Plik klucza jest pusty: {key}")

        self.log("Wysyłanie klucza publicznego. SCP może otworzyć okno do wpisania hasła.")
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        for host in hosts:
            self.log(f"[{host}] Wysyłanie {key.name} -> {remote_key_path}")
            result = subprocess.run(
                ["scp.exe", "-o", f"ConnectTimeout={timeout}", str(key), f"{proxmox_user}@{host}:{remote_key_path}"],
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
        proxmox_user = self.validated_user("proxmox_user")
        timeout = self.validated_timeout()
        grouped = {}
        for container in containers:
            grouped.setdefault(container["host"], []).append(container)

        for host, host_containers in grouped.items():
            ct_ids = " ".join(container["ct"] for container in host_containers)
            configure_script = (
                CONFIGURE_SCRIPT
                .replace("__REMOTE_KEY_PATH__", remote_key_path)
                .replace("__SELECTED_CT_IDS__", ct_ids)
            )
            self.log(f"[{host}] Konfiguracja SSH w LXC: {ct_ids}")
            result = run_ssh_script(host, configure_script, proxmox_user, timeout)
            output = result.stdout.decode("utf-8", errors="replace").strip()
            if output:
                for line in output.splitlines():
                    self.log(f"[{host}] {line}")
            if result.returncode:
                raise RuntimeError(f"Konfiguracja na {host} zakończyła się kodem {result.returncode}.")
        self.log("Konfiguracja SSH zakończona.")

    def generate_shortcuts(self, _hosts, containers):
        created = 0
        lxc_user = self.validated_user("lxc_user")
        output_dir = self.configured_output_directory()
        output_dir.mkdir(parents=True, exist_ok=True)
        for container in containers:
            host = container["host"]
            ct_id = container["ct"]
            name = container["name"]
            ip = container["ip"]
            if container["status"] != "running" or not ip:
                self.log(f"[{host}] Pominięto LXC {ct_id} ({name}): kontener nie działa lub nie ma pasującego IP.")
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
            (output_dir / filename).write_text(content, encoding="ascii", errors="replace", newline="")
            created += 1
            self.log(f"Utworzono: {filename} -> {ip}")
        self.log(f"Gotowe: utworzono {created} skrótów w {output_dir}")

    def run_all(self, hosts, containers):
        target_hosts = list(dict.fromkeys(container["host"] for container in containers))
        self.generate_ssh_key()
        self.upload_keys(target_hosts)
        self.configure_lxc(target_hosts, containers)
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

    def validated_ip_prefix(self):
        prefix = str(self.settings["lxc_ip_prefix"]).strip()
        if not re.fullmatch(r"[0-9.]+", prefix):
            raise ValueError("lxc_ip_prefix może zawierać tylko cyfry i kropki.")
        return prefix

    def configured_output_directory(self):
        configured = Path(os.path.expandvars(os.path.expanduser(str(self.settings["output_directory"]))))
        return configured.resolve() if configured.is_absolute() else (OUTPUT_DIR / configured).resolve()


if __name__ == "__main__":
    ProxmoxManager().mainloop()
