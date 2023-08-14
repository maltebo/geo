# Stempelmünzen – der Bot

Mit den Daten von www.elongated-coin.de wird hier ein 
Stempelmünzen-Bot gebaut, der helfen kann, wenn man die 
nächstgelegenen Automaten sucht.

## Selbst ausführen

Die requirements für den Bot finden sich in requirements.txt.

Um den Bot selbst laufen zu lassen, muss erst ein
Bot mit token erstellt werden. 
Dann muss ein Unterordner "private" erstellt werden, in dem
eine Datei namens "private_constants.py" erstellt werden muss.
Diese muss zwei Dinge enthalten:

- Die Variable TOKEN, die den gültigen Telegram-token enthält.
- Die Variable ABS_PATH, die den Pfad zum geo-Projekt enthält.

Dann muss nur noch mit python 3.10 (andere Versionen können auch 
funktionieren, wurden aber nicht getestet) bot.py ausgeführt werden.