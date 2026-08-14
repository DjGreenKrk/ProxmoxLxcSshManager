# Historia zmian

Wersjonowanie projektu jest zgodne z [Semantic Versioning](https://semver.org/).

## 0.2.0 — 2026-08-14

### Dodano

- test połączenia SSH z hostami Proxmox oraz dostępności polecenia `pct`;
- kolumny `SSH` i `BAT` na liście kontenerów;
- równoległe sprawdzanie dostępu SSH do zaznaczonych LXC;
- wyszukiwanie kontenerów po hoście, CTID, nazwie, statusie i adresie;
- filtry kontenerów uruchomionych, z działającym SSH, bez SSH i bez BAT;
- pasek postępu dla operacji wykonywanych na wielu hostach lub kontenerach.

### Zmieniono

- pełna procedura weryfikuje dostęp SSH po jego skonfigurowaniu;
- techniczna nazwa pliku tymczasowego w LXC jest neutralna i niezależna od użytkownika.

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
