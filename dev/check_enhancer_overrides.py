"""Prueft _collect_enhancer_overrides()/_render_enhancer_overrides() - ohne WanGP.

Die beiden Funktionen sind rein: sie bekommen ein `models_def`-aehnliches Dict
und geben Zaehler plus Gruppen zurueck. Der Test braucht deshalb keinen Host -
WanGP wird nur importiert, damit `import plugin` ueberhaupt laeuft.

Aufruf (aus dem WanGP-Ordner, mit dessen venv):

    ./.wan2gp/bin/python ~/git/wan2gp-local-enhance/dev/check_enhancer_overrides.py

Optional, ohne Testlauf: den gerenderten Text fuer eine eigene JSON-Datei
ausgeben (die Datei enthaelt entweder direkt das models_def-Objekt oder ein
Objekt mit dem Schluessel "models_def"):

    ./.wan2gp/bin/python ~/git/wan2gp-local-enhance/dev/check_enhancer_overrides.py \
        --dump /pfad/models_def.json

Geprueft wird die grobe Erkennung: betroffen ist jede Definition mit irgendeinem
Schluessel der Form text_/image_/video_prompt_enhancer_instructions (Ziffer 1-4
optional). Dazu die Gruppenzuordnung (Image, Image + Video, Video, Audio je
family_label), die Zaehler, das Zusammenfassen gleicher Namen und die
Robustheit gegen kaputte Eintraege.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WAN2GP = Path("~/git/Wan2GP").expanduser()

sys.path.insert(0, str(WAN2GP))
sys.path.insert(0, str(REPO))

import plugin as P  # noqa: E402

# Die Fixture ist erfunden und deckt genau die Faelle ab, die die Erkennung
# unterscheiden muss. Der echte Katalog kommt zur Laufzeit aus dem Host
# (_main("models_def")); hier wird bewusst keine Modell-Definition aufgeloest.
MODELS_DEF = {
    # Bildmodell mit eigenem Schluessel -> Image.
    "image_model": {
        "name": "Image Model B",
        "metadata": {"main_output": ["image"], "family_label": "Qwen Image"},
        "image_prompt_enhancer_instructions": "describe the image",
    },
    # Videomodell ohne eigene Schluessel -> darf nicht in der Liste landen.
    "video_model": {
        "name": "Video Model A",
        "metadata": {"main_output": ["video"], "family_label": "Wan"},
        "model_modes": ["T", "V"],
    },
    # Musik -> Audio (Music).
    "music_model": {
        "name": "Music Model",
        "metadata": {"main_output": ["audio"], "family_label": "Music"},
        "text_prompt_enhancer_instructions": "write lyrics",
    },
    # Zweite Audio-Familie -> Audio (TTS), alphabetisch nach Music.
    "tts_model": {
        "name": "TTS Model",
        "metadata": {"main_output": ["audio"], "family_label": "TTS"},
        "text_prompt_enhancer_instructions": "write a monologue",
    },
    # Ausgeblendet: ueberspringen, aber als untersucht zaehlen.
    "hidden_model": {
        "name": "Hidden Model",
        "visible": False,
        "metadata": {"main_output": ["image"]},
        "image_prompt_enhancer_instructions": "hidden",
    },
    # Nur der nummerierte Schluessel -> muss erkannt werden.
    "numbered_model": {
        "name": "Numbered Model",
        "metadata": {"main_output": ["video"]},
        "text_prompt_enhancer_instructions1": "profile 1",
    },
    # Kein metadata: Fallback des Hosts ueber v2i_switch_supported.
    "v2i_model": {
        "name": "V2I Model",
        "v2i_switch_supported": True,
        "video_prompt_enhancer_instructions": "v2i",
    },
    # Gleicher Anzeigename -> groups fasst zusammen.
    "image_model_copy": {
        "name": "Image Model B",
        "metadata": {"main_output": ["image"]},
        "image_prompt_enhancer_instructions": "copy of the image model",
    },
    # Kaputter Eintrag -> darf nicht abstuerzen.
    "broken_entry": "not a dict",
    # Fallback-Regeln ohne metadata: audio_only / image_outputs / inpaint_support.
    "audio_only_model": {
        "name": "Audio Only Model",
        "audio_only": True,
        "text_prompt_enhancer_instructions": "audio",
    },
    "image_outputs_model": {
        "name": "Image Outputs Model",
        "image_outputs": True,
        "image_prompt_enhancer_instructions": "image",
    },
    "inpaint_model": {
        "name": "Inpaint Model",
        "inpaint_support": True,
        "image_prompt_enhancer_instructions": "inpaint",
    },
}

# Erwartete Gruppen in genau dieser Reihenfolge (Anzeige -> Namen).
EXPECTED_GROUPS = (
    ("Image", ("Image Model B", "Image Outputs Model")),
    ("Image + Video", ("Inpaint Model", "V2I Model")),
    ("Video", ("Numbered Model",)),
    ("Audio", ("Audio Only Model",)),
    ("Audio (Music)", ("Music Model",)),
    ("Audio (TTS)", ("TTS Model",)),
)

# 12 Eintraege in MODELS_DEF; betroffen sind alle ausser video_model,
# hidden_model und dem kaputten Eintrag.
EXPECTED_EXAMINED = 12
EXPECTED_AFFECTED = 9

_FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        _FAILURES.append(name)


def collect(models_def=None):
    """Kurzschreibweise: sammeln und dabei den Erwartungswert nicht vergessen."""
    return P.LocalEnhancePlugin._collect_enhancer_overrides(
        MODELS_DEF if models_def is None else models_def
    )


def rendered_names(result):
    return [name for _label, names in result.groups for name in names]


def dump(path):
    """--dump: gerenderten Text zu einer JSON-Datei ausgeben (sonst nichts)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"Konnte {path} nicht lesen: {exc}")
        return 2

    if isinstance(payload, dict) and isinstance(payload.get("models_def"), dict):
        payload = payload["models_def"]
    result = P.LocalEnhancePlugin._collect_enhancer_overrides(payload)
    print(P.LocalEnhancePlugin._render_enhancer_overrides(result))
    return 0


def main():
    result = collect()

    # 1. Zaehler.
    check(
        "Zaehler: untersucht/betroffen",
        result.examined == EXPECTED_EXAMINED and result.affected == EXPECTED_AFFECTED,
        f"-> {result.examined}/{result.affected}"
        f" (erwartet {EXPECTED_EXAMINED}/{EXPECTED_AFFECTED})",
    )

    # 2. Gruppenzuordnung und Reihenfolge.
    check(
        "Gruppen in fester Reihenfolge",
        tuple(result.groups) == EXPECTED_GROUPS,
        f"-> {result.groups}",
    )

    # 3. Namen alphabetisch sortiert und duplikatfrei.
    check(
        "Namen alphabetisch und duplikatfrei",
        all(list(names) == sorted(names, key=str.casefold) for _label, names in result.groups)
        and len(rendered_names(result)) == len(set(rendered_names(result))),
        f"-> {rendered_names(result)}",
    )
    check(
        "gleicher Anzeigename bleibt einmal",
        rendered_names(result).count("Image Model B") == 1
        and result.affected == EXPECTED_AFFECTED,
        f"-> {rendered_names(result)}",
    )

    # 4. Videomodell ohne eigene Schluessel und ausgeblendetes Modell fehlen in
    #    der Ausgabe, das ausgeblendete zaehlt trotzdem als untersucht.
    check(
        "Videomodell ohne Schluessel fehlt",
        "Video Model A" not in rendered_names(result),
        f"-> {rendered_names(result)}",
    )
    check(
        "visible == False wird uebersprungen, aber gezaehlt",
        "Hidden Model" not in rendered_names(result)
        and result.examined > sum(len(names) for _label, names in result.groups),
        f"-> {rendered_names(result)} / untersucht {result.examined}",
    )

    # 5. Nummerierter Schluessel (text_prompt_enhancer_instructions1) zaehlt.
    check(
        "Schluessel mit Ziffer 1 wird erkannt",
        "Numbered Model" in dict(result.groups).get("Video", ()),
        f"-> {dict(result.groups).get('Video')}",
    )

    # 6. Fallback ohne metadata: v2i_switch_supported -> Image + Video.
    check(
        "v2i_switch_supported landet in Image + Video",
        "V2I Model" in dict(result.groups).get("Image + Video", ()),
        f"-> {dict(result.groups).get('Image + Video')}",
    )

    # 7. Audio wird nach family_label unterteilt, Untergruppen alphabetisch.
    audio_labels = [label for label, _names in result.groups if label.startswith("Audio")]
    check(
        "Audio nach family_label unterteilt",
        audio_labels == ["Audio", "Audio (Music)", "Audio (TTS)"],
        f"-> {audio_labels}",
    )

    # 8. Der kaputte Eintrag hat nicht abgestuerzt (Lauf bis hierher) und die
    #    Fixture selbst ist vollstaendig durchlaufen worden.
    check(
        "kaputter Eintrag bricht nichts",
        isinstance(result.groups, tuple) and result.examined == len(MODELS_DEF),
        f"-> {result.examined} von {len(MODELS_DEF)}",
    )

    # 9. Fehlende Namen und fehlende Metadaten werfen nicht.
    sparse = {
        "nameless": {
            "image_prompt_enhancer_instructions": "ohne Namen",
            "metadata": {"main_output": ["image"]},
        },
        "without_metadata": {
            "name": "Without Metadata",
            "text_prompt_enhancer_instructions": "ohne Metadaten",
        },
    }
    sparse_result = collect(sparse)
    check(
        "fehlender Name und fehlende Metadaten sind erlaubt",
        sparse_result.examined == 2
        and sparse_result.affected == 1
        and sparse_result.groups == (("Video", ("Without Metadata",)),),
        f"-> {sparse_result}",
    )

    # 10. Randfaelle: None, kein Dict, leeres Dict, Definition ohne Schluessel.
    empty_cases = [
        P.LocalEnhancePlugin._collect_enhancer_overrides(value)
        for value in (None, "kein dict", [], {}, {"a": {"name": "Ohne Schluessel"}})
    ]
    check(
        "leere und falsche Kataloge ergeben nichts",
        all(item.groups == () and item.affected == 0 for item in empty_cases)
        and [item.examined for item in empty_cases] == [0, 0, 0, 0, 1],
        f"-> {empty_cases}",
    )

    # 11. metadata.main_output entscheidet vor dem Fallback.
    metadata_cases = collect(
        {
            "both": {
                "name": "Both",
                "metadata": {"main_output": ["image", "video"]},
                "image_outputs": False,
                "text_prompt_enhancer_instructions": "x",
            },
            "audio_wins": {
                "name": "Audio Wins",
                "audio_only": True,
                "metadata": {"main_output": ["audio"], "family_label": "Sound"},
                "text_prompt_enhancer_instructions": "x",
            },
        }
    )
    check(
        "metadata.main_output gewinnt gegen den Fallback",
        tuple(metadata_cases.groups)
        == (("Image + Video", ("Both",)), ("Audio (Sound)", ("Audio Wins",))),
        f"-> {metadata_cases.groups}",
    )

    # 12. Rendern: eine Zeile je Gruppe, keine Tabelle, Namen enthalten.
    text = P.LocalEnhancePlugin._render_enhancer_overrides(result)
    lines = text.split("\n")
    check(
        "Render-Text hat eine Zeile je Gruppe",
        len(lines) == len(EXPECTED_GROUPS)
        and all(line.startswith("<b>") for line in lines)
        and "|" not in text,
        f"-> {lines}",
    )
    check(
        "Render-Text enthaelt die Namen",
        all(
            all(name in text for name in names)
            for _label, names in EXPECTED_GROUPS
        )
        and text.split("\n")[0] == "<b>Image</b> \u2014 Image Model B, Image Outputs Model",
        f"-> {text}",
    )
    check(
        "Render-Text ohne betroffene Modelle bleibt leer",
        P.LocalEnhancePlugin._render_enhancer_overrides(collect({})) == ""
        and P.LocalEnhancePlugin._render_enhancer_overrides(None) == "",
        "-> nicht leer",
    )

    print()
    if _FAILURES:
        print(f"{len(_FAILURES)} Fall/Faelle fehlgeschlagen: {', '.join(_FAILURES)}")
        return 1
    print("Alle Faelle bestanden.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--dump":
        raise SystemExit(dump(sys.argv[2]))
    if len(sys.argv) > 1 and sys.argv[1] == "--dump":
        print("Aufruf: check_enhancer_overrides.py --dump <pfad/models_def.json>")
        raise SystemExit(2)
    raise SystemExit(main())
