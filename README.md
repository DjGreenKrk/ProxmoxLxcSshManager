# Proxmox LXC SSH Manager

[![Version](https://img.shields.io/badge/version-0.2.0-blue)](https://github.com/DjGreenKrk/ProxmoxLxcSshManager/releases)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D4?logo=windows)](https://github.com/DjGreenKrk/ProxmoxLxcSshManager)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Graficzne narzędzie dla Windows do zarządzania dostępem SSH do kontenerów LXC na hostach Proxmox.

Aktualna wersja: **0.2.0**

## Funkcje

- zarządzanie listą hostów Proxmox;
- generowanie lokalnej pary kluczy Ed25519;
- przesyłanie klucza publicznego na wybrane hosty;
- pobieranie i selekcja kontenerów LXC;
- diagnostykę połączenia z hostami Proxmox i dostępności `pct`;
- równoległe sprawdzanie dostępu SSH do wybranych LXC;
- filtrowanie kontenerów według nazwy, statusu SSH i obecności skrótu BAT;
- pasek postępu dla dłuższych operacji;
- instalowanie oraz uruchamianie serwera SSH w wybranych LXC;
- dodawanie klucza do `authorized_keys` bez duplikatów;
- generowanie skrótów BAT otwierających sesje SSH;
- zapisywanie ustawień użytkownika w lokalnym pliku JSON.

## Wymagania

- Windows 10 lub Windows 11;
- Python 3.10 lub nowszy z Tkinter;
- klient OpenSSH dla Windows (`ssh.exe`, `scp.exe`, `ssh-keygen.exe`);
- konto z dostępem SSH do hostów Proxmox;
- polecenie `pct` na hostach Proxmox.

## Uruchomienie

Z katalogu projektu:

```powershell
python .\app\ProxmoxLxcSshManager.py
```

Przy pierwszym uruchomieniu aplikacja tworzy prywatny plik
`app/ProxmoxLxcSshManager.config.json` na podstawie ustawień domyślnych.
Plik jest pomijany przez Git, ponieważ może zawierać adresy i ścieżki użytkownika.

## Podstawowy przepływ

1. Dodaj i zaznacz hosty Proxmox.
2. Wygeneruj klucz SSH albo wskaż istniejący plik publiczny.
3. Wyślij klucz na hosty.
4. Załaduj kontenery i zaznacz wybrane LXC.
5. Skonfiguruj SSH i wygeneruj skróty BAT.

Wygenerowane skróty trafiają domyślnie do katalogu `shortcuts`.

Historia zmian znajduje się w [docs/CHANGELOG.md](docs/CHANGELOG.md), a plan rozwoju w [docs/ROADMAP.md](docs/ROADMAP.md).
