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
Schluessel der Form text_/image_/video_prompt_enhancer_instructions (Ziffernsuffix
beliebig - der Host nimmt die erste Ziffer, die irgendwo im Modus steht). Dazu
die Gruppenzuordnung (Image, Image + Video, Video, Audio je family_label), die
Zaehler, die Buendelung nach metadata.base_model_type, das HTML-Escaping, die
echte Zeilentrennung im Render-Text und die Robustheit gegen kaputte Eintraege.

Zum Schluss laeuft eine realistische Namensprobe: die Fixture wird aus den
echten Definitionen in ~/git/Wan2GP/defaults/*.json (und finetunes/*.json)
gebaut - nur lesen, kein GPU, kein Handler. Welche Modelle betroffen sind, kommt
aus dem Zwischenspeicher eines echten Laufs (enhancer_models.json), weil die
meisten Anweisungen erst die Familien-Handler beisteuern und ohne Hoststart
nicht sichtbar waeren. Fehlt der Zwischenspeicher, entscheidet die Erkennung des
Plugins ueber die Rohdatei (dann sind es nur wenige Modelle).
"""

import html
import json
import re
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
#
# metadata.base_model_type ist der Buendelungsschluessel: Varianten desselben
# Modells landen in EINER Zeile. Fehlt das Feld, gilt architecture, zuletzt der
# interne Typ - deshalb steht es nur dort, wo eine Familie geprueft wird.
MODELS_DEF = {
    # Familie mit zwei Varianten. Der interne Typ der Hauptdefinition entspricht
    # dem Basistyp, deshalb traegt die Zeile deren Namen - nicht den der zweiten
    # Variante.
    "hidream_o1_dev": {
        "name": "HiDream O1 Image Dev 10B",
        "metadata": {"main_output": ["image"], "base_model_type": "hidream_o1_dev"},
        "image_prompt_enhancer_instructions": "describe the image",
    },
    "hidream_o1_dev_2604": {
        "name": "HiDream O1 Image Dev 2604 10B",
        "metadata": {"main_output": ["image"], "base_model_type": "hidream_o1_dev"},
        "image_prompt_enhancer_instructions": "describe the image",
    },
    # Einzelvariante: kein Zaehler, Name aus der eigenen Definition.
    "sense_nova_u1_5": {
        "name": "SenseNova U1.5 8B MoT",
        "metadata": {"main_output": ["image"], "base_model_type": "sense_nova_u1_5"},
        "image_prompt_enhancer_instructions": "describe the image",
    },
    # Familie OHNE Definition mit passendem internen Typ: der kuerzeste Name der
    # Gruppe gewinnt, der Zaehler steht trotzdem da.
    "image_model": {
        "name": "Image Model B",
        "metadata": {"main_output": ["image"], "base_model_type": "image_family"},
        "image_prompt_enhancer_instructions": "describe the image",
    },
    "image_model_copy": {
        "name": "Image Model B",
        "metadata": {"main_output": ["image"], "base_model_type": "image_family"},
        "image_prompt_enhancer_instructions": "copy of the image model",
    },
    # Videomodell ohne eigene Schluessel -> darf nicht in der Liste landen.
    "video_model": {
        "name": "Video Model A",
        "metadata": {"main_output": ["video"]},
        "model_modes": ["T", "V"],
    },
    # Musik -> Audio (Music), zwei Varianten in einer Familie.
    "music_model": {
        "name": "Music Model",
        "metadata": {
            "main_output": ["audio"],
            "family_label": "Music",
            "base_model_type": "music_family",
        },
        "text_prompt_enhancer_instructions": "write lyrics",
    },
    "music_model_v2": {
        "name": "Music Model v2",
        "metadata": {
            "main_output": ["audio"],
            "family_label": "Music",
            "base_model_type": "music_family",
        },
        "text_prompt_enhancer_instructions": "write lyrics",
    },
    # Zweite Audio-Familie -> Audio (TTS), alphabetisch nach Music.
    "tts_model": {
        "name": "TTS Model",
        "metadata": {
            "main_output": ["audio"],
            "family_label": "TTS",
            "base_model_type": "tts_model",
        },
        "text_prompt_enhancer_instructions": "write a monologue",
    },
    # Ausgeblendet: ueberspringen, aber als untersucht zaehlen.
    "hidden_model": {
        "name": "Hidden Model",
        "visible": False,
        "metadata": {"main_output": ["image"], "base_model_type": "hidden_model"},
        "image_prompt_enhancer_instructions": "hidden",
    },
    # Nur der nummerierte Schluessel -> muss erkannt werden, zweite Variante.
    "numbered_model": {
        "name": "Numbered Model",
        "metadata": {"main_output": ["video"], "base_model_type": "numbered_family"},
        "text_prompt_enhancer_instructions1": "profile 1",
    },
    "numbered_model_v2": {
        "name": "Numbered Model v2",
        "metadata": {"main_output": ["video"], "base_model_type": "numbered_family"},
        "text_prompt_enhancer_instructions": "profile default",
    },
    # Ziffernsuffix AUSSERHALB 1-4: der Host bildet das Suffix aus der ersten
    # Ziffer, die irgendwo im Modus-String steht (wgp.py:6462) - also aus jeder
    # Ziffer, nicht nur aus 1-4. Muss ebenfalls erkannt werden.
    "profile9_model": {
        "name": "Profile 9 Model",
        "metadata": {"main_output": ["video"], "base_model_type": "profile9_model"},
        "text_prompt_enhancer_instructions9": "profile 9",
    },
    # Nur max_tokens-Schluessel, KEINE Anweisungen -> darf nicht in der Liste
    # landen (die Erkennung darf nicht auf *_max_tokens* anspringen).
    "max_tokens_only_model": {
        "name": "Max Tokens Only Model",
        "metadata": {"main_output": ["video"]},
        "text_prompt_enhancer_max_tokens5": 4096,
        "video_prompt_enhancer_max_tokens": 2048,
    },
    # Kein metadata: Fallback des Hosts ueber v2i_switch_supported. Der
    # Buendelungsschluessel ist dann der interne Typ.
    "v2i_model": {
        "name": "V2I Model",
        "v2i_switch_supported": True,
        "video_prompt_enhancer_instructions": "v2i",
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
    # Anzeigename mit HTML-Sonderzeichen -> der Render-Text muss escapen.
    "escaped_model": {
        "name": 'Weird <b>&</b> Model "X"',
        "metadata": {"main_output": ["video"], "base_model_type": "weird"},
        "video_prompt_enhancer_instructions": "escaped",
    },
}

# Erwartete Familien in genau dieser Reihenfolge:
# (Gruppe, ((Basistyp, Anzeigename, Anzahl), ...)).
EXPECTED_FAMILIES = (
    (
        "Image",
        (
            ("hidream_o1_dev", "HiDream O1 Image Dev 10B", 2),
            ("image_family", "Image Model B", 2),
            ("image_outputs_model", "Image Outputs Model", 1),
            ("sense_nova_u1_5", "SenseNova U1.5 8B MoT", 1),
        ),
    ),
    (
        "Image + Video",
        (
            ("inpaint_model", "Inpaint Model", 1),
            ("v2i_model", "V2I Model", 1),
        ),
    ),
    (
        "Video",
        (
            ("numbered_family", "Numbered Model", 2),
            ("profile9_model", "Profile 9 Model", 1),
            ("weird", 'Weird <b>&</b> Model "X"', 1),
        ),
    ),
    ("Audio", (("audio_only_model", "Audio Only Model", 1),)),
    ("Audio (Music)", (("music_family", "Music Model", 2),)),
    ("Audio (TTS)", (("tts_model", "TTS Model", 1),)),
)

# 20 Eintraege in MODELS_DEF; betroffen sind alle ausser video_model,
# hidden_model, max_tokens_only_model und dem kaputten Eintrag.
EXPECTED_EXAMINED = 20
EXPECTED_AFFECTED = 16

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


def family_map(result):
    return {label: tuple(families) for label, families in result.groups}


def families_of(result, label):
    return family_map(result).get(label, ())


def family_named(result, name):
    for _label, families in result.groups:
        for family in families:
            if family.name == name:
                return family
    return None


def all_families(result):
    return [family for _label, families in result.groups for family in families]


def normalize(result):
    """Ergebnis auf die Form von EXPECTED_FAMILIES bringen."""
    return tuple(
        (
            label,
            tuple(
                (family.base_model_type, family.name, family.count)
                for family in families
            ),
        )
        for label, families in result.groups
    )


def render_lines(text):
    """Familienzeilen des Render-Textes - Gruppentitel und Trenner entfernt."""
    lines = []
    for chunk in text.replace("<br><br>", "<br>").split("<br>"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("<b>") and chunk.endswith("</b>"):
            continue
        lines.append(chunk)
    return lines


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


# --------------------------------------------------------- realistische Probe

_AFFECTED_KEYS = re.compile(r"^(?:text|image|video)_prompt_enhancer_instructions\d*$")


def _live_names():
    """(Anzeigenamen, Gruppen, Quelle) aus dem Zwischenspeicher eines echten Laufs.

    Nur lesen. Der Zwischenspeicher liegt neben plugin.py; fuer die reale
    Installation wird zusaetzlich der geladene Klon unter
    ~/git/Wan2GP/plugins/wan2gp-local-enhance geprueft. Beide Formate werden
    gelesen: der alte Stand (eine Zeile je Gruppe, Namen mit Komma getrennt) und
    der neue (eine Zeile je Familie, Namen mit <br> getrennt, Zaehler in
    Klammern).
    """
    candidates = (
        REPO / P._MODEL_CHECK_CACHE_NAME,
        WAN2GP / "plugins" / "wan2gp-local-enhance" / P._MODEL_CHECK_CACHE_NAME,
    )
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            continue
        text = str((payload or {}).get("list") or "")
        if not text:
            continue
        groups = []
        # Neuer Stand: eine Gruppe je <br><br>-Block. Alter Stand: eine Gruppe
        # je Zeile. Beides wird gelesen, damit die Probe nach dem naechsten
        # Klick nicht blind wird.
        chunks = text.split("<br><br>") if "<br" in text else text.split("\n")
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            match = re.match(r"<b>(.*?)</b>", chunk, re.DOTALL)
            if match is None:
                continue
            label = re.sub(r"<[^>]+>", "", match.group(1)).strip()
            rest = chunk[match.end():]
            names = []
            for item in re.split(r"<br\s*/?>", rest):
                item = re.sub(r"<[^>]+>", "", item)
                item = re.sub(r"^\s*—\s*", "", item).strip()
                for name in item.split(", "):
                    name = re.sub(r"\s*\(\d+\)\s*$", "", name.strip())
                    if name:
                        names.append(name)
            groups.append((label, names))
        return groups, str(path)
    return [], ""


def _real_definitions():
    """Echte Definitionen aus defaults/*.json und finetunes/*.json (nur lesen)."""
    definitions = {}
    for folder in ("defaults", "finetunes"):
        root = WAN2GP / folder
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                continue
            model = payload.get("model") if isinstance(payload, dict) else None
            if not isinstance(model, dict):
                continue
            name = str(model.get("name") or "").strip()
            if not name:
                continue
            definitions[path.stem] = model
    return definitions


def _media_for_label(label):
    """Medien-Token und family_label zu einer Gruppenueberschrift."""
    base = re.sub(r"\s*\(.*\)\s*$", "", label).strip()
    if base == P._ENHANCER_GROUP_IMAGE:
        return ["image"], ""
    if base == P._ENHANCER_GROUP_IMAGE_VIDEO:
        return ["image", "video"], ""
    if base == P._ENHANCER_GROUP_AUDIO:
        match = re.match(r".*?\((.*)\)\s*$", label)
        return ["audio"], (match.group(1).strip() if match else "")
    return ["video"], ""


def realistic_models_def():
    """Fixture aus den echten Namen der Installation (nur lesen, kein Handler).

    Zuordnung der betroffenen Modelle ueber den Zwischenspeicher eines echten
    Laufs; Namen, interne Typen und Buendelungsschluessel kommen aus den echten
    Definitionsdateien. Fehlt der Zwischenspeicher, gilt die Erkennung des
    Plugins ueber die Rohdatei - dann sind nur die Modelle betroffen, die ihre
    Anweisungen direkt in der JSON mitbringen (das sind wenige, weil die meisten
    Anweisungen aus den Familien-Handlern kommen).
    """
    definitions = _real_definitions()
    groups, source = _live_names()
    affected = set()
    for label, names in groups:
        for name in names:
            affected.add(name)

    fixture = {}
    for stem, model in definitions.items():
        name = str(model.get("name") or "").strip()
        base = str(model.get("architecture") or stem).strip()
        entry = {"name": name, "metadata": {"base_model_type": base}}
        if name in affected:
            entry["image_prompt_enhancer_instructions"] = "real fixture"
        elif any(_AFFECTED_KEYS.match(str(key)) for key in model):
            entry["image_prompt_enhancer_instructions"] = "json fixture"
        fixture[stem] = entry

    # Gruppen aus dem Zwischenspeicher uebernehmen (die Medienart steckt sonst
    # nur in den Handler-Definitionen und ist ohne Host nicht zu bekommen).
    by_name = {entry["name"]: entry for entry in fixture.values()}
    for label, names in groups:
        main_output, family_label = _media_for_label(label)
        for name in names:
            entry = by_name.get(name)
            if entry is None:
                # Modell ohne Definitionsdatei: eigene Familie, eigener Name.
                fixture[name] = {
                    "name": name,
                    "metadata": {
                        "base_model_type": name,
                        "main_output": main_output,
                        "family_label": family_label,
                    },
                    "image_prompt_enhancer_instructions": "real fixture",
                }
                continue
            entry["metadata"]["main_output"] = main_output
            if family_label:
                entry["metadata"]["family_label"] = family_label
    if not groups:
        # Ohne Zwischenspeicher entscheidet die Medienart nicht - dann bleibt es
        # bei einer Gruppe fuer alles, was die Erkennung findet.
        for entry in fixture.values():
            entry["metadata"].setdefault("main_output", ["video"])
    return fixture, source


def realistic_probe():
    fixture, source = realistic_models_def()
    if not fixture:
        print("Realistische Namensprobe: keine Definitionen gefunden "
              "(~/git/Wan2GP/defaults/*.json fehlt) - uebersprungen.")
        return
    result = P.LocalEnhancePlugin._collect_enhancer_overrides(fixture)
    text = P.LocalEnhancePlugin._render_enhancer_overrides(result)
    lines = render_lines(text)
    print()
    print("=== Realistische Namensprobe ===")
    print(f"Quelle der Definitionsdateien: {WAN2GP}/defaults/*.json (+ finetunes)")
    print(f"Quelle der betroffenen Modelle: {source or 'JSON-Erkennung des Plugins'}")
    print(f"Definitionsdateien in der Fixture: {result.examined}")
    print(f"Betroffene Definitionen: {result.affected}")
    print(f"Gruppen: {len(result.groups)}, Familien (Zeilen): {len(lines)}")
    if lines:
        print(f"Laengste Zeile: {max(len(line) for line in lines)} Zeichen")
    print("--- gerenderter Text ---")
    print(text)
    print("--- Ende ---")


def main():
    result = collect()

    # 1. Zaehler.
    check(
        "Zaehler: untersucht/betroffen",
        result.examined == EXPECTED_EXAMINED and result.affected == EXPECTED_AFFECTED,
        f"-> {result.examined}/{result.affected}"
        f" (erwartet {EXPECTED_EXAMINED}/{EXPECTED_AFFECTED})",
    )

    # 2. Gruppen und Familien: Buendelung, Reihenfolge, Anzeigenamen, Zaehler.
    check(
        "Familien gebuendelt, Gruppen in fester Reihenfolge",
        normalize(result) == EXPECTED_FAMILIES,
        f"-> {normalize(result)}",
    )

    # 3. Mehrere Varianten desselben Basistyps -> EINE Zeile mit Zaehler.
    multi = [
        family
        for family in all_families(result)
        if family.count == 2
    ]
    check(
        "mehrere Varianten ergeben eine Zeile mit Zaehler",
        len(multi) == 4
        and family_named(result, "HiDream O1 Image Dev 10B") is not None
        and family_named(result, "HiDream O1 Image Dev 10B").count == 2
        and family_named(result, "HiDream O1 Image Dev 10B").model_types
        == ("hidream_o1_dev", "hidream_o1_dev_2604")
        and family_named(result, "Image Model B").count == 2
        and family_named(result, "Numbered Model").count == 2
        and family_named(result, "Music Model").count == 2,
        f"-> {[(f.name, f.count) for f in all_families(result)]}",
    )

    # 3b. Eine einzelne Variante bekommt KEINEN Zaehler.
    singles = [
        family
        for family in all_families(result)
        if family.count == 1
    ]
    check(
        "einzelne Variante bekommt keinen Zaehler",
        len(singles) == 8
        and all(family.model_types for family in singles)
        and P.LocalEnhancePlugin._render_enhancer_overrides(
            P.LocalEnhancePlugin._collect_enhancer_overrides(
                {
                    "only": {
                        "name": "Only Model",
                        "metadata": {"main_output": ["video"]},
                        "video_prompt_enhancer_instructions": "x",
                    }
                }
            )
        ).endswith("<b>Video</b><br>Only Model"),
        f"-> {[(f.name, f.count) for f in singles]}",
    )

    # 4. Anzeigename: Definition mit passendem internen Typ, sonst der kuerzeste
    #    Name der Gruppe.
    check(
        "Anzeigename aus der Definition mit passendem internen Typ",
        getattr(family_named(result, "HiDream O1 Image Dev 10B"), "base_model_type", None)
        == "hidream_o1_dev"
        and getattr(family_named(result, "Image Model B"), "base_model_type", None)
        == "image_family"
        and getattr(family_named(result, "Numbered Model"), "base_model_type", None)
        == "numbered_family",
        f"-> {[(f.base_model_type, f.name) for f in all_families(result)]}",
    )

    # 5. Videomodell ohne eigene Schluessel und ausgeblendetes Modell fehlen in
    #    der Ausgabe, das ausgeblendete zaehlt trotzdem als untersucht.
    family_names = [family.name for family in all_families(result)]
    check(
        "Videomodell ohne Schluessel fehlt",
        "Video Model A" not in family_names,
        f"-> {family_names}",
    )
    check(
        "visible == False wird uebersprungen, aber gezaehlt",
        "Hidden Model" not in family_names
        and result.examined > sum(family.count for family in all_families(result)),
        f"-> {family_names} / untersucht {result.examined}",
    )

    # 6. Nummerierter Schluessel (text_prompt_enhancer_instructions1) zaehlt.
    check(
        "Schluessel mit Ziffer 1 wird erkannt",
        family_named(result, "Numbered Model") is not None,
        f"-> {family_names}",
    )

    # 6b. Ziffernsuffix ausserhalb 1-4 zaehlt genauso (der Host nimmt jede
    #     Ziffer, die im Modus steht).
    check(
        "Schluessel mit Ziffer ausserhalb 1-4 wird erkannt",
        family_named(result, "Profile 9 Model") is not None,
        f"-> {family_names}",
    )

    # 6c. max_tokens-Schluessel sind KEINE Anweisungen und duerfen nicht
    #     treffen - auch nicht mit Ziffernsuffix.
    check(
        "max_tokens-Schluessel zaehlt nicht",
        "Max Tokens Only Model" not in family_names
        and not P.LocalEnhancePlugin._has_enhancer_instructions(
            MODELS_DEF["max_tokens_only_model"]
        ),
        f"-> {family_names}",
    )

    # 7. Fallback ohne metadata: v2i_switch_supported -> Image + Video.
    check(
        "v2i_switch_supported landet in Image + Video",
        family_named(result, "V2I Model") in families_of(result, "Image + Video"),
        f"-> {families_of(result, 'Image + Video')}",
    )

    # 8. Audio wird nach family_label unterteilt, Untergruppen alphabetisch.
    audio_labels = [label for label, _families in result.groups if label.startswith("Audio")]
    check(
        "Audio nach family_label unterteilt",
        audio_labels == ["Audio", "Audio (Music)", "Audio (TTS)"],
        f"-> {audio_labels}",
    )

    # 9. Der kaputte Eintrag hat nicht abgestuerzt (Lauf bis hierher) und die
    #    Fixture selbst ist vollstaendig durchlaufen worden.
    check(
        "kaputter Eintrag bricht nichts",
        isinstance(result.groups, tuple) and result.examined == len(MODELS_DEF),
        f"-> {result.examined} von {len(MODELS_DEF)}",
    )

    # 10. Fehlende Namen und fehlende Metadaten werfen nicht.
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
        and normalize(sparse_result)
        == (("Video", (("without_metadata", "Without Metadata", 1),)),),
        f"-> {sparse_result}",
    )

    # 11. Randfaelle: None, kein Dict, leeres Dict, Definition ohne Schluessel.
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

    # 12. metadata.main_output entscheidet vor dem Fallback.
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
        normalize(metadata_cases)
        == (
            ("Image + Video", (("both", "Both", 1),)),
            ("Audio (Sound)", (("audio_wins", "Audio Wins", 1),)),
        ),
        f"-> {metadata_cases.groups}",
    )

    # 13. Rendern: eine Zeile je Familie, Gruppentitel fett, Gruppen wirklich
    #     getrennt (Leerzeile = <br><br>), keine Tabelle.
    text = P.LocalEnhancePlugin._render_enhancer_overrides(result)
    labels = [label for label, _families in result.groups]
    check(
        "Render-Text hat eine Zeile je Familie",
        render_lines(text) == [
            ("HiDream O1 Image Dev 10B (2)"),
            ("Image Model B (2)"),
            ("Image Outputs Model"),
            ("SenseNova U1.5 8B MoT"),
            ("Inpaint Model"),
            ("V2I Model"),
            ("Numbered Model (2)"),
            ("Profile 9 Model"),
            ('Weird &lt;b&gt;&amp;&lt;/b&gt; Model &quot;X&quot;'),
            ("Audio Only Model"),
            ("Music Model (2)"),
            ("TTS Model"),
        ]
        and "|" not in text,
        f"-> {render_lines(text)}",
    )
    check(
        "Gruppenzeilen sind echt getrennt",
        text.count("<br><br>") == len(labels) - 1
        and all(f"<b>{label}</b><br>" in text for label in labels)
        and "\n" not in text,
        f"-> {text!r}",
    )
    check(
        "Zaehler nur bei mehreren Varianten",
        "HiDream O1 Image Dev 10B (2)" in text
        and "SenseNova U1.5 8B MoT" in text
        and "SenseNova U1.5 8B MoT (1)" not in text
        and "Profile 9 Model (1)" not in text,
        f"-> {text}",
    )

    # 14. HTML wird escaped (Namen stammen aus den Modelldefinitionen).
    check(
        "Render-Text escaped HTML",
        "&lt;b&gt;&amp;&lt;/b&gt;" in text
        and "&quot;X&quot;" in text
        and "Weird <b>" not in text,
        f"-> {text}",
    )

    # 15. Render-Text enthaelt alle Familiennamen.
    check(
        "Render-Text enthaelt die Namen",
        all(html.escape(family.name) in text for family in all_families(result))
        and text.startswith("<b>Image</b><br>"),
        f"-> {text}",
    )

    # 16. Altbestand: eine Gruppenliste aus reinen Namen rendert weiterhin.
    legacy = P.LocalEnhancePlugin._render_enhancer_overrides(
        (("Video", ("Old Model",)),)
    )
    check(
        "reine Namensliste rendert weiter",
        legacy == "<b>Video</b><br>Old Model",
        f"-> {legacy!r}",
    )

    # 17. Render-Text ohne betroffene Modelle bleibt leer.
    check(
        "Render-Text ohne betroffene Modelle bleibt leer",
        P.LocalEnhancePlugin._render_enhancer_overrides(collect({})) == ""
        and P.LocalEnhancePlugin._render_enhancer_overrides(None) == "",
        "-> nicht leer",
    )

    realistic_probe()

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
