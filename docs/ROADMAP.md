# Plan rozwoju

## 0.6.0 — interfejs i dystrybucja

- przebudowa GUI z czytelnym podziałem na hosty, kontenery i operacje;
- większa przestrzeń robocza dla tabeli LXC oraz responsywne skalowanie okna;
- wyróżnienie głównego przepływu i uporządkowanie operacji dodatkowych;
- licznik zaznaczonych hostów i kontenerów;
- czytelniejsze stany pracy, błędów i trybu podglądu;
- czyszczenie oraz kopiowanie dziennika z poziomu GUI;
- przygotowanie pojedynczego pliku EXE;
- testy regresji logiki interfejsu i pakowania.

## Później

- podpisywanie wydań dla Windows;
- opcjonalny instalator zamiast wersji przenośnej.

## Zasady bezpieczeństwa

- nie nadpisywać istniejących kluczy prywatnych;
- nie usuwać wpisów `authorized_keys` bez potwierdzenia;
- wykonywać zmiany tylko dla jawnie zaznaczonych kontenerów;
- przechowywać ustawienia użytkownika poza kontrolą wersji;
- pokazywać pełny wynik nieudanych operacji SSH, SCP i `pct`.
