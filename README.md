# Proxmox LXC SSH Manager

[![Version](https://img.shields.io/badge/version-0.5.0-blue)](https://github.com/DjGreenKrk/ProxmoxLxcSshManager/releases)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D4?logo=windows)](https://github.com/DjGreenKrk/ProxmoxLxcSshManager)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://github.com/DjGreenKrk/ProxmoxLxcSshManager/actions/workflows/tests.yml/badge.svg)](https://github.com/DjGreenKrk/ProxmoxLxcSshManager/actions/workflows/tests.yml)

Graficzne narzędzie dla Windows do zarządzania dostępem SSH do kontenerów LXC na hostach Proxmox.

Aktualna wersja rozwojowa: **0.5.0**

## Funkcje

- zarządzanie listą hostów Proxmox;
- osobne ustawienia adresu, użytkownika i portu SSH dla każdego hosta;
- generowanie lokalnej pary kluczy Ed25519;
- przesyłanie klucza publicznego na wybrane hosty;
- pobieranie i selekcja kontenerów LXC;
- diagnostykę połączenia z hostami Proxmox i dostępności `pct`;
- równoległe sprawdzanie dostępu SSH do wybranych LXC;
- jawne dodawanie nowych fingerprintów LXC do lokalnego `known_hosts`;
- filtrowanie kontenerów według nazwy, stanu SSH, zaufania fingerprintu, autoryzacji i obecności skrótu BAT;
- pasek postępu dla dłuższych operacji;
- wybór adresów LXC z wielu konfigurowalnych prefiksów sieciowych;
- wykrywanie nieaktualnych skrótów BAT i przenoszenie ich do odzyskiwalnego archiwum;
- instalowanie oraz uruchamianie serwera SSH w wybranych LXC;
- dodawanie klucza do `authorized_keys` bez duplikatów;
- generowanie skrótów BAT otwierających sesje SSH;
- zapisywanie ustawień użytkownika w lokalnym pliku JSON.
- tryb podglądu pokazujący plan operacji bez wysyłania kluczy i modyfikowania LXC lub skrótów;
- instalowanie OpenSSH przez `apt-get`, `apk` albo `dnf` oraz obsługę systemd i OpenRC.

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

Wyniki diagnostyki są bieżącym stanem sesji i nie są zapisywane w configu.
Przycisk `Zaufaj nowym kluczom` używa polityki OpenSSH `accept-new`: zapisuje
nowe fingerprinty, ale odrzuca klucze znanych hostów, które uległy zmianie.

Wygenerowane skróty trafiają domyślnie do katalogu `shortcuts`.
Nieaktualne skróty można przenieść do datowanego podfolderu `shortcuts/_archive`.

Prefiksy IP służą do wyboru właściwego adresu z `hostname -I` wewnątrz kontenera.
Nie muszą należeć do tej samej sieci co host Proxmox. Kilka wartości można podać
po przecinku, średniku lub spacji, np. `192.168.0., 10.20.0., 172.16.5.`.

Każdy host Proxmox ma własny profil połączenia w formacie `użytkownik@adres:port`.
Starszy config z tekstową listą hostów i globalnym `proxmox_user` jest migrowany
automatycznie przy wczytaniu.
Po udanym teście hosta aplikacja zapisuje jego zdalną nazwę i pokazuje wpis jako
`nazwa-hosta — użytkownik@adres:port`.

Opcja `Tryb podglądu` pozwala przejść przez operacje modyfikujące bez wykonywania
SCP, instalacji w LXC, tworzenia kluczy i skrótów ani archiwizacji plików.

Historia zmian znajduje się w [docs/CHANGELOG.md](docs/CHANGELOG.md), a plan rozwoju w [docs/ROADMAP.md](docs/ROADMAP.md).

## Testy

```powershell
python -m unittest discover -s tests -v
```

Ten sam zestaw jest uruchamiany przez GitHub Actions na Pythonie 3.10 i 3.12.
