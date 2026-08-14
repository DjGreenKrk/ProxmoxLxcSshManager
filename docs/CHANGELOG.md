# Historia zmian

Wersjonowanie projektu jest zgodne z [Semantic Versioning](https://semver.org/).

## 0.5.0 — 2026-08-14

### Dodano

- tryb podglądu dla operacji modyfikujących hosty, kontenery i lokalne pliki;
- instalację OpenSSH w kontenerach używających `apk` lub `dnf`, obok dotychczasowego `apt-get`;
- uruchamianie usługi SSH przez OpenRC w kontenerach bez systemd;
- zgodność odkrywania testów `unittest` z Test Explorerem w VS Code i Pythonem 3.14.

### Zmieniono

- lokalne ustawienia `.vscode` są ignorowane przez Git.

### Naprawiono

- pojedynczy kontener LXC nie może już bezterminowo blokować ładowania, diagnostyki ani konfiguracji; `pct exec` i lokalne procesy SSH mają twarde limity czasu;
- diagnostyka automatycznie ponawia sekwencyjnie pierwszy test SSH zakończony timeoutem, ograniczając fałszywe alarmy podczas równoległego sprawdzania wielu LXC.

## 0.4.0 — 2026-08-14

### Dodano

- osobny profil połączenia dla każdego hosta Proxmox;
- konfigurowalne per host: adres IP lub DNS, użytkownik SSH i port;
- dialog dodawania oraz edycji hosta w GUI;
- czytelny format wpisów hostów `użytkownik@adres:port`;
- automatyczne pobieranie, zapisywanie i wyświetlanie zdalnej nazwy hosta po udanym teście;
- trwały zestaw testów jednostkowych dla migracji configu, profili i komend SSH;
- workflow GitHub Actions dla Pythona 3.10 i 3.12.

### Zmieniono

- SSH, SCP, diagnostyka i odczyt LXC używają ustawień właściwego hosta;
- stary config z listą adresów i globalnym użytkownikiem jest automatycznie migrowany;
- kolumna hosta na liście LXC pokazuje wykrytą nazwę zamiast technicznego adresu, jeśli nazwa jest dostępna.

## 0.3.0 — 2026-08-14

### Dodano

- obsługę wielu prefiksów IPv4 używanych do wyboru adresów LXC;
- automatyczną migrację starego ustawienia `lxc_ip_prefix` do listy `lxc_ip_prefixes`;
- wykrywanie nieaktualnych skrótów BAT dla załadowanych hostów;
- podgląd listy nieaktualnych plików i potwierdzenie operacji w GUI;
- odzyskiwalną archiwizację skrótów w datowanym katalogu `_archive`.

### Naprawiono

- wykrywanie IPv4 w kontenerach BusyBox/Alpine, które nie obsługują `hostname -I`; aplikacja używa dla nich `ip -o -4 addr`.

### Bezpieczeństwo

- archiwizacja jest blokowana, jeśli lista LXC nie została odświeżona dla wszystkich wybranych hostów;
- stare skróty nie są trwale usuwane.

## 0.2.0 — 2026-08-14

### Dodano

- test połączenia SSH z hostami Proxmox oraz dostępności polecenia `pct`;
- kolumny `SSH` i `BAT` na liście kontenerów;
- równoległe sprawdzanie dostępu SSH do zaznaczonych LXC;
- wyszukiwanie kontenerów po hoście, CTID, nazwie, statusie i adresie;
- osobne filtry dla działającego SSH, nieznanego fingerprintu, braku autoryzacji, niedostępnej usługi, nietestowanych LXC i braku BAT;
- pasek postępu dla operacji wykonywanych na wielu hostach lub kontenerach.
- jawną akcję dodawania nowych fingerprintów SSH do lokalnego `known_hosts`.

### Zmieniono

- pełna procedura weryfikuje dostęp SSH po jego skonfigurowaniu;
- techniczna nazwa pliku tymczasowego w LXC jest neutralna i niezależna od użytkownika.
- wyniki diagnostyki pozostają stanem bieżącej sesji, aby nie prezentować nieaktualnego cache jako aktualnego wyniku.

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
