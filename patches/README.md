# YuE2 „Cover“ — Host-Patch

Dieser Patch ergänzt in WanGP eine echte **Cover**-Quelle im
`Composition Source`-Dropdown von YuE2. Der Eintrag bleibt auch nach einem
Modellwechsel erhalten; intern wird `C` in der Pipeline wie
`A` (Use Score from Audio) behandelt.

## Anwenden

Im WanGP-Checkout (Quelle der Wahrheit ist der WanGP-Klon, **nicht** der
geladene Plugin-Klon):

```bash
cd ~/git/Wan2GP
git apply ~/git/wan2gp-local-enhance/patches/yue2-cover.patch
```

Danach WanGP **neu starten**. Plugins und Modelldefinitionen werden nur beim
Start geladen.

## Zurücknehmen

```bash
cd ~/git/Wan2GP
git apply -R ~/git/wan2gp-local-enhance/patches/yue2-cover.patch
```

## Was der Patch ändert

- `models/TTS/yue2/composition.py`: Quelle `C` = „Cover (Score from Audio,
  fixed tempo)“, Validierung wie `A` (Audioquelle nötig), Direct-Generation
  weiterhin nur mit `0`.
- `models/TTS/yue2/yue2_handler.py`: `C` im `letters_filter` der
  Composition Source.
- `models/TTS/yue2/pipeline.py`: `C` wird vor der Engine-Ausführung auf `A`
  abgebildet.
- `wgp.py`: Audio-Upload, Validierung, stiller WAV-Fallback und
  Enhancer-Kwargs behandeln `C` wie `A`.

## Wichtig

- Der Patch ist **nicht update-sicher**: ein WanGP-Update kann die Dateien
  überschreiben. Danach den Patch erneut anwenden.
- Der Patch macht aus YuE2 **keinen** Stimmen-Klon. Ein Cover nutzt das
  transkribierte Score der Quelle; Music Style (Genre, Instrumente, Stimme)
  bleibt eine eigene Wahl.
- Die BPM-Ausblendung und die Duration-Übernahme macht das Plugin
  (`Create Cover`-Checkbox in der Music-Style-Karte). Ohne Plugin bleibt der
  Host-Eintrag „Cover“ sonst ein normaler `A`-Lauf.
