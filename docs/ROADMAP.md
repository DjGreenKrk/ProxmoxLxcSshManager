# Plan rozwoju

## Najbliższe usprawnienia

- oddzielny użytkownik i port SSH dla każdego hosta;
- tryb podglądu bez wprowadzania zmian;
- obsługa instalacji SSH w systemach używających `apk` i `dnf`;
- pasek postępu i anulowanie kolejnych operacji;
- przygotowanie pojedynczego pliku EXE.

## Zasady bezpieczeństwa

- nie nadpisywać istniejących kluczy prywatnych;
- nie usuwać wpisów `authorized_keys` bez potwierdzenia;
- wykonywać zmiany tylko dla jawnie zaznaczonych kontenerów;
- przechowywać ustawienia użytkownika poza kontrolą wersji;
- pokazywać pełny wynik nieudanych operacji SSH, SCP i `pct`.
