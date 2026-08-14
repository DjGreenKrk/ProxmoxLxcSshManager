# Historia zmian

Wersjonowanie projektu jest zgodne z [Semantic Versioning](https://semver.org/).

## 0.1.0 — 2026-08-14

Pierwsza wersjonowana wersja aplikacji.

### Dodano

- graficzny interfejs Tkinter dla Windows;
- konfigurowalną listę hostów Proxmox;
- generowanie par kluczy SSH Ed25519;
- wysyłanie klucza publicznego przez SCP;
- wykrywanie kontenerów LXC na wybranych hostach;
- tabelę umożliwiającą wybór konkretnych kontenerów;
- instalowanie i uruchamianie serwera SSH w wybranych LXC;
- bezpieczne dodawanie klucza do `authorized_keys` bez duplikatów;
- generowanie skrótów BAT dla wybranych kontenerów;
- konfigurowalne nazwy użytkowników, ścieżki, timeout i prefiks adresów;
- lokalny config JSON pomijany przez Git;
- przykładową konfigurację i dokumentację projektu.
