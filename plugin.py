"""Enhance: OpenCode / Bonsai 27B - two prompt-enhancer buttons.

Hintergrund
-----------
WanGP koppelt den Prompt Enhancer fest an die Deepy-Engine:

    # shared/remote_llm/config.py:397
    def resolve_role_engine(server_config, role):
        return str(normalize_llm_config(server_config)["deepy"])   # role wird ignoriert

    # shared/remote_llm/config.py:381
    normalized["prompt_enhancer"] = ENGINE_SAME_AS_DEEPY

    # wgp.py:6505
    local_runtime = not is_remote_engine(resolve_role_engine(server_config, "prompt_enhancer"))

Laeuft Deepy also ueber OpenCode, nutzt auch der Enhance-Prompt-Knopf OpenCode.

Dieses Plugin umgeht das, ohne die Engine umzustellen. Der lokale Enhancer ist
namlich unabhaengig ladbar: ``ensure_prompt_enhancer_loaded()`` entscheidet allein
anhand von ``enhancer_enabled`` (ein Integer: 3/4/5 = 4B/9B/27B), nicht anhand der
Engine. Das Plugin ruft deshalb den lokalen Pfad direkt auf:

    ensure_prompt_enhancer_loaded()   -> laedt das lokale Qwen-Modell
    process_prompt_enhancer(...)      -> verbessert den Prompt
    unload_prompt_enhancer_runtime()  -> gibt den VRAM wieder frei

Voraussetzung: ``enhancer_enabled`` muss ungleich 0 sein (Config -> Prompt Enhancer /
Deepy -> LLM Engine auf ein lokales Qwen-Modell zeigen lassen). Der Wert bestimmt,
welches lokale Modell geladen wird.
"""

import html
import json
import re
import sys
import time
from pathlib import Path
from typing import NamedTuple

import gradio as gr

from shared.utils.plugins import WAN2GPPlugin
from shared.utils.process_locks import acquire_GPU_ressources, release_GPU_ressources
from shared.utils.prompt_parser import (
    PROMPT_UNIT_PREFIX,
    serialize_prompt_blocks_with_prefix,
    split_prompt_units,
)
from shared.remote_llm.config import engine_from_legacy_enhancer, is_remote_engine

PlugIn_Name = "Enhance: OpenCode / Bonsai 27B"
PlugIn_Id = "LocalEnhance"

# Wie lange der lokale Enhancer im VRAM bleiben darf, bevor er wieder freigegeben
# wird. Innerhalb dieses Fensters ist ein zweiter Klick sofort schnell.
_GPU_HOLD_SECONDS = 0

# Rangfolge der OpenCode-Reasoning-Level. Der Katalog liefert sie als Liste, die
# Reihenfolge ist nicht garantiert - deshalb wird nach Rang sortiert.
_REASONING_RANK = {"minimal": 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5, "ultra": 6}

# WanGP schreibt die Wortgrenze fest in die Enhancer-Anweisungen
# (shared/prompt_enhancer/prompt_enhance_utils.py:25/34/42/51/56). Das Plugin
# ersetzt genau diese Saetze, damit Min/Max ueber Felder einstellbar werden.
_DEFAULT_MIN_WORDS = 0
_DEFAULT_WORD_LIMIT = 150
_WORD_LIMIT_MAX = 2000
_MIN_WORDS_KEY = "local_enhance_min_words"
_MAX_WORDS_KEY = "local_enhance_max_words"
_WORD_LIMIT_KEY = "local_enhance_word_limit"   # Altbestand, Fallback fuer Max
# Sichtbare Breite der beiden Zahlenfelder im Tab. Gradio macht daraus
# min-width: min(N px, 100%) am Block; scale=0 verhindert, dass sie ueber die
# ganze Zeile wachsen. "1500" braucht rund 58 px - 120 px geben Luft, ohne dass
# eine eigene CSS-Regel noetig waere.
_WORD_FIELD_WIDTH = 120

# Modelle mit eigenen Enhancer-Anweisungen. Der Host holt die Anweisungen an
# diesen Schluesseln; die optionale Ziffer am Ende waehlt ein Profil, das der
# Modus vorgibt. Der Host nimmt dafuer die ERSTE Ziffer irgendwo im
# Modus-String (re.search(r"\d", prompt_enhancer_mode), wgp.py:6462-6464),
# also jede Ziffer 0-9 - nicht nur 1-4.
# Bringt ein Modell so einen Schluessel mit, gewinnen seine Anweisungen gegen
# die vom Plugin uebergebenen (_fallback_instructions) - die Wortgrenzen-Felder
# Min/Max wirken dort also nicht.
_ENHANCER_INSTRUCTION_RE = re.compile(
    r"^(?:text|image|video)_prompt_enhancer_instructions\d*$"
)
# Medien-Token aus metadata.main_output. Der Host schreibt "audio", "image" und
# "video"; Gross-/Kleinschreibung und ein angehaengtes Plural-s werden grob
# mitgenommen, damit eine unbekannte Schreibweise nichts verliert.
_MEDIA_TOKEN_RE = re.compile(r"^(image|video|audio)s?$", re.IGNORECASE)
# Gruppen der Ausgabe in genau dieser Reihenfolge. Audio steht zuletzt und wird
# dort nach family_label unterteilt (typisch "TTS" und "Music").
_ENHANCER_GROUP_IMAGE = "Image"
_ENHANCER_GROUP_IMAGE_VIDEO = "Image + Video"
_ENHANCER_GROUP_VIDEO = "Video"
_ENHANCER_GROUP_AUDIO = "Audio"
_ENHANCER_GROUPS = (
    _ENHANCER_GROUP_IMAGE,
    _ENHANCER_GROUP_IMAGE_VIDEO,
    _ENHANCER_GROUP_VIDEO,
)

# Bild-Eingaben, die LIVE aus den Komponenten kommen muessen: der Settings-
# Snapshot (state["all_settings"]) wird nur von save_inputs()-Fluessen
# geschrieben, nicht beim Hinzufuegen eines Bildes zur Galerie. WanGPs eigener
# Knopf ruft dafuer extra save_inputs() auf (wgp.py:13215) - das Plugin hat
# dafuer keine Komponenten und haengt die Bilder stattdessen als Klick-Eingaben
# an. Reihenfolge = Reihenfolge der Klick-Eingaben.
_IMAGE_INPUT_NAMES = (
    "image_start",
    "image_end",
    "image_refs",
    "image_guide",
    "image_prompt_type",
    "video_prompt_type",
)


class _EnhancerImages(NamedTuple):
    """Bilder, die der lokale Pfad an process_prompt_enhancer() weitergibt.

    labels sind die Bezeichnungen der Bilder (Kontrollbild, "start image",
    "Image reference no 1", ...) - sie steuern den Hinweis in der Statuszeile
    und die Wahl der Bild-Anweisungen (IT2I/IT2V statt T2I/T2V).
    """

    image_start: list | None
    image_refs: list | None
    kwargs: dict
    labels: tuple


class _EnhancerOverrides(NamedTuple):
    """Ergebnis von _collect_enhancer_overrides().

    examined: untersuchte Definitionen - alle Eintraege von models_def, auch die
              ausgeblendeten und die kaputten.
    affected: Definitionen mit eigenen Anweisungen, die nicht ausgeblendet sind
              und einen Anzeigenamen haben, also genau die Modelle in groups
              (jede Variante einzeln gezaehlt; groups buendelt sie zu Familien).
    groups:   ((Anzeige, (Familie, ...)), ...) in fester Reihenfolge: Image,
              Image + Video, Video, danach Audio je family_label alphabetisch.
              Eine Familie ist ein _EnhancerFamily-Eintrag; die Familien einer
              Gruppe sind alphabetisch sortiert, leere Gruppen fehlen ganz.
    """

    examined: int
    affected: int
    groups: tuple


class _EnhancerFamily(NamedTuple):
    """Eine Modellfamilie im Modell-Check - eine Zeile der Ausgabe.

    Varianten desselben Modells (gleicher Buendelungsschluessel) stehen in einer
    Zeile, count nennt ihre Zahl. base_model_type ist der Schluessel der
    Buendelung (metadata.base_model_type, sonst architecture, sonst der interne
    Typ), name der Anzeigename der Familie, model_types die internen Typen aller
    Varianten (alphabetisch, fuer Test und Fehlersuche).
    """

    base_model_type: str
    name: str
    count: int
    model_types: tuple


# ------------------------------------------------------------- Modell-Check
# Der Knopf "Check models" im Tab listet die Modelle, die eigene Enhancer-
# Anweisungen mitbringen - fuer sie wirken Min/Max nicht. Die Liste wird beim
# Aufbau des Tabs NICHT berechnet, sondern nur aus dieser JSON-Datei gelesen.
# Die Datei liegt neben plugin.py: die Basisklasse WAN2GPPlugin stellt kein
# Attribut fuer das Plugin-Verzeichnis bereit (andere Host-Plugins setzen sich
# selbst eines), deshalb der Pfad ueber __file__. Der Name steht in .gitignore,
# damit Testlaeufe den Arbeitsbaum nicht beschmutzen.
_MODEL_CHECK_CACHE_NAME = "enhancer_models.json"
# Feste englische Oberflaechentexte, wortgetreu.
_MODEL_CHECK_HINT = (
    "*These limits are applied by rewriting the enhancer instructions this plugin supplies. "
    "Models that ship their own enhancer instructions ignore them.*"
)
_MODEL_CHECK_INTRO = (
    "WanGP prefers a model's own enhancer instructions over the ones this plugin supplies, "
    "so Min/Max have no effect for these models."
)
# Die Liste sitzt in einem gr.HTML, deshalb HTML statt Markdown: frueher stand
# hier "**Check models**", im HTML waeren die Sternchen sichtbar geblieben.
_MODEL_CHECK_EMPTY = (
    "Not checked yet in this installation - press <b>Check models</b>."
)
_MODEL_CHECK_NO_CATALOG = (
    "<b>No model definitions loaded.</b> The model catalog of WanGP is "
    "empty. Load a model or refresh the catalog in WanGP first."
)
_MODEL_CHECK_NO_MODEL = (
    "No model in the current catalog ships its own enhancer instructions."
)
# Zeile zum AKTUELLEN Modell. Sie ist die eigentlich nuetzliche Antwort und
# steht immer sichtbar ueber dem eingeklappten Bereich - deshalb wird sie NICHT
# zwischengespeichert, sondern bei jedem Tab-Aufbau und Tab-Wechsel neu aus dem
# Live-Zustand des Hosts berechnet (siehe _current_model_line).
_MODEL_CHECK_CURRENT_UNKNOWN = "**Current model:** unknown."
_MODEL_CHECK_CURRENT_OWN = (
    "**Current model:** {name} - ships its own enhancer instructions, "
    "so Min/Max are ignored."
)
_MODEL_CHECK_CURRENT_PLAIN = (
    "**Current model:** {name} - no own enhancer instructions, Min/Max apply."
)
# Scrollbare Box der Liste: fester Hoechstwert plus eigener Scrollbalken, damit
# der Tab nicht auseinandergezogen wird. Der Stil sitzt inline am
# umschliessenden div - _UI_CSS bleibt dafuer unberuehrt.
_MODEL_CHECK_BOX_STYLE = "max-height:260px;overflow-y:auto;"
# Normale Knopfbreite. Gradios Default ist 160px; scale=0 verhindert nur das
# Wachsen ueber die Zeile, min_width gibt dem Label die noetige Breite, damit
# "Check models" einzeilig bleibt.
_MODEL_CHECK_BUTTON_WIDTH = 160


# Stylesheet der eingebauten Zeile. Steht als Konstante hier, damit dasselbe CSS
# auch ohne WanGP-Start geprueft werden kann (siehe AGENTS.md, Abschnitt Pruefen).
_UI_CSS = (
    # Der eingebaute Knopf verschwindet per ID; an visible=False kommt WanGPs
    # modellabhaengiges UI-Update sonst vorbei.
    "#local_enhance_builtin_btn{display:none !important;}"
    # Zeile 1 wird nur so breit wie ihr Inhalt, damit die Modus-Zeile darunter
    # umbrechen kann statt die Knoepfe zu quetschen.
    "#local_enhance_row{flex-wrap:wrap !important;}"
    "#local_enhance_row .local-enhance-label,"
    "#local_enhance_row .cbx_centered{"
    "width:auto !important;flex:0 0 auto !important;min-width:max-content !important;}"
    # Die Modus-Zeile: der gr.Form hinter der Knopfreihe, in dem nur noch das
    # Modus-Dropdown sitzt. Die beiden Wort-Regler stehen im Plugin-Tab und
    # brauchen hier keine eigenen Regeln mehr.
    "#local_enhance_row + .form{flex-basis:100% !important;}"
)
_WORD_KEEP_SENTENCE = "Keep within 150 words."
_WORD_LIMIT_SENTENCE = "Do not exceed the 150 word limit!"
_BASE_OUTPUT_TOKENS = 512
_MAX_OUTPUT_TOKENS = 4096
_NO_LIMIT_OUTPUT_TOKENS = 1024


def _main(name, default=None):
    """Live-Zugriff auf Globals des Hauptmoduls (nicht die eingefrorene Kopie)."""
    module = sys.modules.get("__main__")
    return getattr(module, name, default) if module is not None else default


class LocalEnhancePlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = PlugIn_Name
        self.version = "1.0.0"
        self.description = (
            "Lokaler Prompt-Enhancer neben dem eingebauten Knopf - benutzt immer das "
            "lokale Qwen-Modell, auch wenn Deepy ueber eine Remote-Engine laeuft."
        )
        self.type = ["extension"]
        self._last_enhanced = ""
        self._last_source = ""

    # ------------------------------------------------------------------ Setup

    def setup_ui(self):
        self.request_component("state")
        self.request_component("refresh_form_trigger")
        self.request_component("prompt")
        # Der eingebaute "Enhance Prompt"-Knopf wird ausgeblendet: er verbessert
        # ueber dieselbe Remote-Engine wie der OpenCode-Knopf und waere damit
        # ein Doppel. An seiner Stelle steht nur noch die Beschriftung.
        self.request_component("prompt_enhancer_btn")
        # Der vom Nutzer gewaehlte Modus liegt in WanGPs verstecktem gr.Text
        # `prompt_enhancer` (wgp.py:12169). Er wird vom sichtbaren Dropdown und
        # der Think-Checkbox aktuell gehalten (wgp.py:13036-13037) und ist auch
        # die Klick-Eingabe von WanGPs eigenem Knopf (wgp.py:13189). Ohne diese
        # Komponente faellt das Plugin auf den Modell-Default zurueck
        # (_effective_mode) und verwirft z. B. die Bilder, wenn der Nutzer
        # "Based on Text Prompt and Images" gewaehlt hat.
        self.request_component("prompt_enhancer")
        # Bilder fuer den lokalen Pfad. Namen, die ein Modell nicht hat, werden
        # vom PluginManager still uebersprungen (shared/utils/plugins.py:1626),
        # _image_components() filtert sie dann heraus.
        for component_name in _IMAGE_INPUT_NAMES:
            self.request_component(component_name)
        self.request_global("get_current_model_settings")
        self.request_global("get_state_model_type")
        self.request_global("get_model_def")
        self.request_global("get_model_settings")
        self.request_global("get_prompt_enhancer_choices")
        self.add_tab(tab_id=PlugIn_Id, label=PlugIn_Name, component_constructor=self.create_ui)
        self.add_custom_js(self._info_tooltip_js())
        # Knoepfe direkt neben "Enhance Prompt". Schlaegt das fehl, wird es
        # vom PluginManager geloggt und der Tab oben funktioniert trotzdem.
        try:
            self.insert_after("prompt_enhancer_btn", self.create_inline_button)
        except Exception as exc:  # noqa: BLE001
            print(f"[{PlugIn_Name}] Could not request the inline button: {exc}")

    def post_ui_setup(self, components):
        """Eingebauten Enhance-Knopf ausblenden - die Beschriftung liefert das Plugin.

        Ein direkter Attributzugriff genuegt: Gradio liest 'visible' erst beim
        Rendern der Config aus, und post_ui_setup laeuft vor dem Start.
        """
        builtin = components.get("prompt_enhancer_btn") if isinstance(components, dict) else None
        if builtin is not None:
            try:
                builtin.visible = False
            except Exception as exc:  # noqa: BLE001
                print(f"[{PlugIn_Name}] Could not hide the built-in button: {exc}")
        return {}

    # ------------------------------------------------------------- Hilfsmittel

    @staticmethod
    def _with_thinking(mode, enabled):
        """Das Thinking-Flag 'K' an den Enhancer-Modus haengen.

        wgp.py:6451 leitet thinking_enabled ausschliesslich aus `"K" in
        prompt_enhancer_mode` ab. Ohne 'K' denkt das lokale Modell nie - die
        Think-Checkbox war deshalb wirkungslos. chaining.with_thinking() ist die
        offizielle Umsetzung (shared/prompt_enhancer/chaining.py:37).
        """
        chaining = _main("prompt_enhancer_chaining")
        if chaining is not None:
            try:
                return chaining.with_thinking(mode, enabled)
            except Exception:  # noqa: BLE001 - Fallback unten
                pass
        mode = str(mode or "")
        if enabled:
            return f"{mode}K" if mode and "K" not in mode else mode
        return mode.replace("K", "")

    @staticmethod
    def _reasoning_efforts(profile):
        """Verfuegbare Reasoning-Level des im Profil gewaehlten Modells."""
        catalog = profile.get("model_catalog") or []
        provider = str(profile.get("provider", "") or "")
        model = str(profile.get("model", "") or "")
        entry = next(
            (
                item
                for item in catalog
                if isinstance(item, dict)
                and str(item.get("provider", "")) == provider
                and str(item.get("model", "")) == model
            ),
            None,
        )
        efforts = entry.get("reasoning_efforts") if isinstance(entry, dict) else None
        return [str(effort) for effort in (efforts or []) if str(effort).strip()]

    @classmethod
    def _remote_reasoning_effort(cls, profile, think):
        """Reasoning-Level fuer den Remote-Aufruf.

        OpenCode kennt kein 'aus', nur Varianten - der Wert geht als 'variant'
        in den Request (opencode_backend.py:226). Ein leeres Level heisst
        'Automatic' und ueberlaesst die Entscheidung dem Anbieter; deshalb wird
        ohne Think aktiv der niedrigste Level geschickt. Ist das Modell im
        Katalog unbekannt, bleibt das Profil unangetastet.
        """
        efforts = cls._reasoning_efforts(profile)
        if not efforts:
            return ""
        ordered = sorted(
            efforts,
            key=lambda effort: (_REASONING_RANK.get(effort.lower(), 99), efforts.index(effort)),
        )
        return ordered[-1] if think else ordered[0]

    @staticmethod
    def _resolve_mode(model_def, audio_only, image_mode):
        """Standard-Enhancer-Modus fuer das aktuelle Modell ermitteln."""
        chooser = _main("get_prompt_enhancer_choices")
        if chooser is None:
            return "T"
        try:
            choices, default, _definition = chooser(
                model_def, audio_only, image_mode, include_disabled=False
            )
        except Exception:
            return "T"
        if default:
            return str(default)
        if choices:
            return str(choices[0][1])
        return "T"

    @staticmethod
    def _effective_mode(live_mode, model_def, audio_only, image_mode):
        """Der Modus, mit dem der Enhancer laeuft - Live-Wert vor Default.

        `live_mode` ist der Inhalt von WanGPs verstecktem `prompt_enhancer`-Text,
        also genau die Buchstaben, die Dropdown und Think-Checkbox schreiben
        (wgp.py:13036-13037). Er ist die einzige Quelle fuer die Nutzerauswahl.
        Leer ist er, wenn der Nutzer "Disabled" gewaehlt hat oder die Komponente
        fehlt - dann bleibt _resolve_mode() als Fallback (bisheriges Verhalten).
        """
        mode = str(live_mode or "").strip()
        if mode:
            return mode
        return LocalEnhancePlugin._resolve_mode(model_def, audio_only, image_mode)

    @staticmethod
    def _local_enhancer_ready():
        """Ist ein lokales Enhancer-Modell konfiguriert?"""
        config = _main("server_config") or {}
        try:
            return int(config.get("enhancer_enabled", 0) or 0) > 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _variant_label():
        """Welches lokale Modell antwortet? Macht die Herkunft eindeutig."""
        config = _main("server_config") or {}
        try:
            number = int(config.get("enhancer_enabled", 0) or 0)
        except (TypeError, ValueError):
            number = 0
        return {
            1: "Llama 3.2 3B",
            2: "Llama Joy 8B",
            3: "Qwen3.5-4B",
            4: "Qwen3.5-9B",
            5: "Qwen3.8-27B",
        }.get(number, f"Modell {number}")

    @staticmethod
    def _button_label():
        """Beschriftung des lokalen Knopfes.

        Fest 'Local 27B', weil der Knopf die 27B jetzt auch dann erzwingt, wenn
        die Config als lokales Modell eine andere Groesse fuehrt.
        """
        return "Local 27B"

    @staticmethod
    def _remote_engine_name():
        """Remote-Engine fuer den OpenCode-Knopf bestimmen.

        Ist Deepy bereits remote, wird diese Engine genommen - sonst die erste
        profilierte Remote-Engine. Ohne Profil kann der Knopf nichts tun, weil
        die Configs der lokalen Agenten ein leeres OpenCode-Profil mitbringen.
        """
        config = _main("server_config") or {}
        llm = config.get("llm_engines") or {}
        current = str(llm.get("deepy", "") or "").strip().lower()
        if is_remote_engine(current):
            return current
        profiles = llm.get("profiles") or {}
        for candidate in ("opencode", "codex", "claude"):
            if candidate in profiles:
                return candidate
        return ""

    @classmethod
    def _remote_button_label(cls):
        engine = cls._remote_engine_name()
        return {"opencode": "OpenCode", "codex": "Codex", "claude": "Claude"}.get(engine, "OpenCode")

    @staticmethod
    def _first_prompt(prompts):
        """process_prompt_enhancer() liefert pro Prompt eine Liste."""
        first = prompts[0] if isinstance(prompts, (list, tuple)) else prompts
        while isinstance(first, (list, tuple)):
            first = first[0] if first else ""
        return str(first or "").strip()

    @staticmethod
    def _clamp_words(value):
        """Wortzahl auf 0.._WORD_LIMIT_MAX begrenzen; ungueltig -> None."""
        try:
            words = int(value)
        except (TypeError, ValueError):
            return None
        return max(0, min(_WORD_LIMIT_MAX, words))

    @classmethod
    def _word_range(cls, min_value=None, max_value=None):
        """Min/Max der Wortgrenze: Feldwert, sonst Config, sonst Default.

        0 heisst jeweils 'keine Grenze'. Ist Min groesser als Max, werden beide
        getauscht - die Anweisung waere sonst widerspruechlich.
        """
        config = _main("server_config") or {}
        config = config if isinstance(config, dict) else {}
        if min_value is None:
            min_value = config.get(_MIN_WORDS_KEY, _DEFAULT_MIN_WORDS)
        if max_value is None:
            max_value = config.get(_MAX_WORDS_KEY, config.get(_WORD_LIMIT_KEY, _DEFAULT_WORD_LIMIT))
        min_words = cls._clamp_words(min_value)
        max_words = cls._clamp_words(max_value)
        if min_words is None:
            min_words = _DEFAULT_MIN_WORDS
        if max_words is None:
            max_words = _DEFAULT_WORD_LIMIT
        if min_words > 0 and max_words > 0 and min_words > max_words:
            min_words, max_words = max_words, min_words
        return min_words, max_words

    @staticmethod
    def _remember_word_range(min_words, max_words):
        """Die Grenzen in der Live-Config merken - WanGP schreibt sie mit."""
        config = _main("server_config")
        if isinstance(config, dict):
            config[_MIN_WORDS_KEY] = int(min_words)
            config[_MAX_WORDS_KEY] = int(max_words)

    @staticmethod
    def _apply_word_limit(text, min_words, max_words):
        """Die festen 150-Wort-Saetze durch die gewaehlten Grenzen ersetzen."""
        text = str(text or "")
        if min_words > 0 and max_words > 0:
            keep = f"Keep between {min_words} and {max_words} words."
            limit = f"Do not exceed the {max_words} word limit!"
        elif max_words > 0:
            keep = f"Keep within {max_words} words."
            limit = f"Do not exceed the {max_words} word limit!"
        elif min_words > 0:
            keep = f"Write at least {min_words} words."
            limit = ""
        else:
            keep = ""
            limit = ""
        text = text.replace(_WORD_KEEP_SENTENCE, keep).replace(_WORD_LIMIT_SENTENCE, limit)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @staticmethod
    def _output_token_budget(min_words, max_words):
        """Token-Budget, in das die gewuenschte Wortzahl passt.

        150 Woerter passen in die 512 Tokens der Voreinstellung. Darueber waechst
        das Budget mit (grob 2.2 Tokens pro Wort; deutsch braucht mehr als
        englisch), sonst schneidet das Token-Limit den Prompt ab.
        """
        reference = max_words if max_words > 0 else min_words
        if reference <= 0:
            return _NO_LIMIT_OUTPUT_TOKENS
        return max(_BASE_OUTPUT_TOKENS, min(_MAX_OUTPUT_TOKENS, int(round(reference * 2.2)) + 64))

    @staticmethod
    def _word_note(min_words, max_words):
        """Kurzer Hinweis auf die gesetzten Grenzen."""
        if min_words > 0 and max_words > 0:
            return f", {min_words}-{max_words} words"
        if max_words > 0:
            return f", max {max_words} words"
        if min_words > 0:
            return f", min {min_words} words"
        return ", no word limit"

    @classmethod
    def _read_controls(cls, controls):
        """Think-Checkbox und Min/Max aus den Klick-Eingaben lesen.

        Die Widgets koennen fehlen (WanGP legt die Think-Checkbox nur fuer lokale
        Enhancer an), deshalb wird nach Typ ausgewertet: bool = Think, Zahlen =
        die beiden Wort-Regler (erst Min, dann Max). Der Modus-String ist vorher
        mit _split_mode_input() abgezogen, hier kommt also keiner mehr an.
        """
        think = False
        numbers = []
        for value in controls:
            if isinstance(value, bool):        # vor int pruefen: bool ist int
                think = value
            elif (
                isinstance(value, (list, tuple))
                and len(value) == 2
                and all(
                    isinstance(item, (int, float)) and not isinstance(item, bool)
                    for item in value
                )
            ):
                numbers = [int(item) for item in value]   # Regler-Paare
            elif isinstance(value, (int, float)):
                numbers.append(int(value))
        if len(numbers) >= 2:
            min_value, max_value = numbers[0], numbers[1]
        elif len(numbers) == 1:
            # Einzelnes Feld: in der alten Fassung war das die Obergrenze.
            min_value, max_value = None, numbers[0]
        else:
            min_value = max_value = None
        min_words, max_words = cls._word_range(min_value, max_value)
        return think, min_words, max_words

    def _control_components(self):
        """Die Regler, die fuer beide Knoepfe gelten: Think, Min, Max."""
        fields = (
            getattr(self, "_think_checkbox", None),
            getattr(self, "_min_words_field", None),
            getattr(self, "_max_words_field", None),
        )
        return [field for field in fields if field is not None]

    def _attach_word_fields(self, target):
        """Die beiden Wort-Regler in den Plugin-Tab umhaengen.

        Sie entstehen in create_inline_button() - die Knoepfe in Zeile 1
        brauchen sie dort schon als Klick-Eingaben - und parken bis create_ui()
        in der Knopfreihe (self._word_fields_home). create_ui() laeuft laut Host
        erst danach (wgp.py:13628 vor 13976) und holt sie hierher.

        WICHTIG: erst NACH dem Verlassen des `with gr.Row()`-Blocks aufrufen.
        Beim Verlassen eines BlockContexts gruppiert Gradio aufeinanderfolgende
        Formularfelder in einen gr.Form (BlockContext.__exit__ ->
        fill_expected_parents, blocks.py:456-486), und ein gr.Form stapelt seine
        Kinder vertikal - die beiden Felder stuenden dann untereinander statt
        nebeneinander.
        """
        fields = [
            field
            for field in (
                getattr(self, "_min_words_field", None),
                getattr(self, "_max_words_field", None),
            )
            if field is not None
        ]
        if target is None or not fields:
            return fields

        def _current_home(field):
            """Container, der das Feld wirklich in children fuehrt (sonst None).

            component.parent ist nach dem Auspacken aus dem gr.Form-Wrapper
            nicht mehr verlaesslich - deshalb der Blick in children und der
            Rueckfall auf den geparkten Container.
            """
            candidates = (
                getattr(field, "parent", None),
                getattr(self, "_word_fields_home", None),
            )
            for candidate in candidates:
                if candidate is not None and any(
                    child is field for child in (getattr(candidate, "children", None) or [])
                ):
                    return candidate
            return None

        for field in fields:
            try:
                # Erst aus dem alten Elterncontainer entfernen, dann beim
                # Zielcontainer anhaengen: bleibt das Entfernen aus, steht die
                # Komponente in zwei Eltern und erscheint doppelt im Layout.
                home = _current_home(field)
                if home is not None:
                    home.children.remove(field)
                if not any(child is field for child in (getattr(target, "children", None) or [])):
                    target.children.append(field)
                field.parent = target
            except Exception as exc:  # noqa: BLE001
                print(f"[{PlugIn_Name}] Could not attach the word-limit fields: {exc}")
        return fields

    def _image_components(self):
        """Die aufgeloesten Bild-Komponenten in fester Reihenfolge.

        Modelle ohne Bild-Eingaben haben weniger (oder keine) davon - die Liste
        ist ueber die Sitzung stabil, weil die Attribute nur einmal beim
        Verdrahten gesetzt werden.
        """
        return [
            component
            for name in _IMAGE_INPUT_NAMES
            if (component := getattr(self, name, None)) is not None
        ]

    def _mode_components(self):
        """WanGPs versteckter Modus-Text als Klick-Eingabe.

        Fehlt die Komponente (aeltere WanGP-Fassung, Modell ohne Enhancer-Zeile),
        bleibt die Liste leer - dann greift in _effective_mode() der
        Modell-Default. Der PluginManager ueberspringt unbekannte Namen still,
        das Attribut kann also fehlen oder None sein.
        """
        component = getattr(self, "prompt_enhancer", None)
        return [component] if component is not None else []

    def _split_image_inputs(self, values):
        """Klick-Eingaben in (Regler, Bilder) trennen.

        Gradio liefert alles positional: erst die Regler, dann die Bilder. Die
        Bilder sind der bekannte Suffix (dieselbe Liste wie beim Verdrahten),
        deshalb wird von rechts getrennt - die Grenze bleibt so auch dann
        richtig, wenn links ein Regler fehlt.
        """
        values = tuple(values or ())
        names = [
            name for name in _IMAGE_INPUT_NAMES if getattr(self, name, None) is not None
        ]
        if not names:
            return values, {}
        controls_count = max(0, len(values) - len(names))
        return values[:controls_count], dict(zip(names, values[controls_count:]))

    def _split_mode_input(self, values):
        """Modus-Eingabe von den uebrigen Klick-Eingaben abziehen.

        Steht die Modus-Komponente in der Verdrahtung, ist sie die erste
        Eingabe nach (state, text) und muss vor _split_image_inputs() weg - sonst
        verschieben sich die Eingaben um eins.
        """
        values = tuple(values or ())
        if self._mode_components() and values:
            return values[0], values[1:]
        return None, values

    @classmethod
    def _fallback_instructions(cls, is_image, audio_only, min_words=None, max_words=None, with_images=False):
        """Dieselben eingebauten Anweisungen, die der lokale Pfad benutzt.

        `resolve_prompt_enhancer_settings()` (wgp.py:6457) holt die Anweisungen
        ausschliesslich aus `model_def`. Die meisten Modelle definieren keine -
        `models/krea2/` etwa gar keine -, und dann geht ein LEERER System-Prompt
        an die Remote-Engine. OpenCode's build-Agent weiss dadurch nicht, dass er
        umschreiben soll, stellt eine Rueckfrage ("asking questions=1") und
        blockiert; WanGP wartet bis zum POST-Timeout von 3600 s.

        Der lokale Pfad faellt in diesem Fall auf die eingebauten Anweisungen
        zurueck (generate_cinematic_prompt, prompt_enhance_utils.py:241). Die
        Auswahl hier ist mit dem lokalen Aufruf identisch: text_prompt=audio_only,
        video_prompt=not is_image. Die Wortgrenze wird dabei ersetzt.

        `with_images`: Es gehen Bilder an das Modell, dann gelten die
        Bild-Anweisungen (IT2I/IT2V, prompt_enhance_utils.py:65/113) - genau die,
        die generate_cinematic_prompt() selbst waehlen wuerde. Beide enthalten
        dieselben Wortgrenzen-Saetze, _apply_word_limit greift also weiter.
        """
        from shared.prompt_enhancer.prompt_enhance_utils import (
            IT2I_VISUAL_PROMPT,
            IT2V_CINEMATIC_PROMPT,
            T2I_VISUAL_PROMPT,
            T2T_TEXT_PROMPT,
            T2V_CINEMATIC_PROMPT,
        )
        if audio_only:
            text = T2T_TEXT_PROMPT
        elif with_images:
            text = IT2I_VISUAL_PROMPT if is_image else IT2V_CINEMATIC_PROMPT
        else:
            text = T2I_VISUAL_PROMPT if is_image else T2V_CINEMATIC_PROMPT
        return cls._apply_word_limit(text, *cls._word_range(min_words, max_words))

    @staticmethod
    def _image_note(labels):
        """Kurzer Hinweis auf die benutzten Bilder (fuer die Statuszeile)."""
        labels = list(labels or [])
        if not labels:
            return ""
        if len(labels) > 3:
            return f", {len(labels)} images"
        return ", images: " + ", ".join(labels)

    @staticmethod
    def _local_engine_name():
        """Engine-Name, der zu enhancer_enabled gehoert (3 -> qwen35_4b usw.)."""
        config = _main("server_config") or {}
        try:
            number = int(config.get("enhancer_enabled", 0) or 0)
        except (TypeError, ValueError):
            number = 0
        return engine_from_legacy_enhancer(number)

    # ---------------------------------------------------------- Modell-Katalog

    @staticmethod
    def _has_enhancer_instructions(model_def):
        """Bringt die Definition irgendeinen Enhancer-Anweisungs-Schluessel?

        Geprueft wird GROB - nur die Schluesselform zaehlt
        (_ENHANCER_INSTRUCTION_RE). Ob der Host den Schluessel im gewaehlten
        Modus wirklich benutzt, entscheidet er zusaetzlich am Modus: die erste
        Ziffer im Modus waehlt ein Profil, und nur der Schluessel mit genau
        dieser Ziffer gewinnt gegen die Anweisungen des Plugins
        (wgp.py:6461-6480).
        """
        if not isinstance(model_def, dict):
            return False
        return any(_ENHANCER_INSTRUCTION_RE.match(str(key)) for key in model_def)

    @staticmethod
    def _media_tokens(outputs):
        """Medien-Token aus metadata.main_output, grob normalisiert."""
        tokens = []
        for value in outputs if isinstance(outputs, (list, tuple, set)) else ():
            match = _MEDIA_TOKEN_RE.match(str(value or "").strip())
            if match is None:
                continue
            token = match.group(1).lower()
            if token not in tokens:
                tokens.append(token)
        return tokens

    @classmethod
    def _enhancer_media_group(cls, model_def):
        """Medienart einer Definition als (Gruppe, Untergruppe).

        Primaer entscheidet `metadata.main_output` des Hosts (z. B. ["audio"],
        ["image"], ["image", "video"]). Fehlt `metadata`, gilt dieselbe Regel
        wie im Host (models/model_metadata.py:92): `audio_only` -> Audio,
        `image_outputs` -> Image, `v2i_switch_supported` oder `inpaint_support`
        -> Image + Video, sonst Video.

        Audio wird zusaetzlich nach `family_label` unterteilt (typisch "TTS"
        und "Music"); ohne Label bleibt die Untergruppe leer. Bei allen anderen
        Medienarten ist die Untergruppe immer leer.
        """
        model_def = model_def if isinstance(model_def, dict) else {}
        metadata = model_def.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        tokens = cls._media_tokens(metadata.get("main_output"))
        if not tokens:
            if model_def.get("audio_only", False):
                tokens = ["audio"]
            elif model_def.get("image_outputs", False):
                tokens = ["image"]
            elif model_def.get("v2i_switch_supported", False) or model_def.get(
                "inpaint_support", False
            ):
                tokens = ["image", "video"]
            else:
                tokens = ["video"]

        if "audio" in tokens:
            return _ENHANCER_GROUP_AUDIO, str(metadata.get("family_label") or "").strip()
        if "image" in tokens and "video" in tokens:
            return _ENHANCER_GROUP_IMAGE_VIDEO, ""
        if "image" in tokens:
            return _ENHANCER_GROUP_IMAGE, ""
        return _ENHANCER_GROUP_VIDEO, ""

    @staticmethod
    def _enhancer_base_model_type(model_type, model_def):
        """Buendelungsschluessel einer Definition.

        Quelle ist das Feld `base_model_type` aus `metadata` der Definition. Der
        Host schreibt es in `store_metadata()` (models/model_metadata.py:238) und
        setzt es auf `model_def["architecture"]` bzw. den internen Typ
        (models/model_metadata.py:232) - verifiziert im Host-Quelltext. Fehlt der
        Eintrag (aelterer Zwischenspeicher, Testfixture), gilt `architecture`,
        zuletzt der interne Typ selbst.
        """
        model_def = model_def if isinstance(model_def, dict) else {}
        metadata = model_def.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        base = str(metadata.get("base_model_type") or "").strip()
        if not base:
            base = str(model_def.get("architecture") or "").strip()
        if not base:
            base = str(model_type or "").strip()
        return base

    @staticmethod
    def _enhancer_family_name(base_model_type, entries, definitions):
        """Anzeigename einer Familie.

        Erste Wahl ist der Name der Definition, deren INTERNER Typ dem Basistyp
        entspricht (typisch die Hauptdefinition der Familie). Gibt es keine,
        gewinnt der kuerzeste Name der Gruppe (bei Gleichstand alphabetisch),
        zuletzt der Basistyp selbst.
        """
        base_def = (
            definitions.get(base_model_type)
            if isinstance(definitions, dict)
            else None
        )
        if isinstance(base_def, dict):
            name = str(base_def.get("name") or "").strip()
            if name:
                return name
        names = sorted(
            {name for _type, name in entries},
            key=lambda value: (len(value), value.casefold()),
        )
        return names[0] if names else str(base_model_type)

    @classmethod
    def _enhancer_families(cls, bucket, definitions):
        """Eine Gruppe von Varianten zu Familien buendeln (alphabetisch).

        bucket: {Basistyp: [(interner Typ, Anzeigename), ...]}. Varianten
        desselben Basistyps ergeben genau eine _EnhancerFamily-Zeile; count ist
        die Zahl der Varianten.
        """
        families = []
        for base, entries in (bucket or {}).items():
            entries = sorted(entries, key=lambda item: (item[1].casefold(), item[0]))
            families.append(
                _EnhancerFamily(
                    base_model_type=base,
                    name=cls._enhancer_family_name(base, entries, definitions),
                    count=len(entries),
                    model_types=tuple(
                        sorted(model_type for model_type, _name in entries)
                    ),
                )
            )
        families.sort(key=lambda family: (family.name.casefold(), family.base_model_type))
        return tuple(families)

    @classmethod
    def _collect_enhancer_overrides(cls, models_def):
        """Modelle sammeln, die eigene Enhancer-Anweisungen mitbringen.

        Reine Funktion: kein UI, kein Dateizugriff, keine Host-Importe, keine
        Nebenwirkungen. Den Katalog liefert der Aufrufer - zur Laufzeit
        `_main("models_def")` (das Modul-Dict des Hosts), im Test eine Fixture.

        Geprueft wird GROB: betroffen ist jede Definition mit irgendeinem
        Schluessel der Form text_/image_/video_prompt_enhancer_instructions
        (Ziffernsuffix beliebig, auch mehrere Ziffern - der Host nimmt die erste
        Ziffer, die irgendwo im Modus steht). Ob der Host den Schluessel im
        gewaehlten Modus wirklich benutzt, entscheidet er zusaetzlich am Modus -
        die erste Ziffer im Modus waehlt ein Profil, nur der passende Schluessel
        gewinnt. Ohne Modus sammelt diese Funktion deshalb lieber zu viel als zu
        wenig.

        Statt jeder Variante landet genau eine Zeile je Modellfamilie in der
        Ausgabe (Buendelung ueber _enhancer_base_model_type). Varianten mit
        demselben Anzeigenamen zaehlen weiterhin zusammen.

        Nicht-Dict-Eintraege, fehlende Namen und fehlende Metadaten sind erlaubt
        und werden still uebergangen. Ausgeblendete Modelle (visible == False)
        fehlen in der Ausgabe, zaehlen aber als untersucht.
        """
        definitions = models_def if isinstance(models_def, dict) else {}
        examined = 0
        affected = 0
        collected = {}
        for model_type, model_def in definitions.items():
            examined += 1
            if not cls._has_enhancer_instructions(model_def):
                continue
            if model_def.get("visible", True) is False:
                continue
            name = str(model_def.get("name") or "").strip()
            if not name:
                continue
            affected += 1
            group, subgroup = cls._enhancer_media_group(model_def)
            base = cls._enhancer_base_model_type(model_type, model_def)
            bucket = collected.setdefault((group, subgroup), {})
            bucket.setdefault(base, []).append((str(model_type), name))

        groups = []
        for group in _ENHANCER_GROUPS:
            families = cls._enhancer_families(collected.get((group, "")), definitions)
            if families:
                groups.append((group, families))
        # Audio: eine Zeile je family_label, alphabetisch.
        for group, subgroup in sorted(collected):
            if group != _ENHANCER_GROUP_AUDIO:
                continue
            families = cls._enhancer_families(
                collected.get((group, subgroup)), definitions
            )
            if not families:
                continue
            label = (
                f"{_ENHANCER_GROUP_AUDIO} ({subgroup})"
                if subgroup
                else _ENHANCER_GROUP_AUDIO
            )
            groups.append((label, families))

        return _EnhancerOverrides(examined, affected, tuple(groups))

    @staticmethod
    def _render_enhancer_overrides(overrides):
        """HTML-Text zu _collect_enhancer_overrides(): Familie fuer Familie.

        Form je Gruppe: fetter Titel, darunter eine Zeile je Modellfamilie, die
        Zahl der Varianten in Klammern nur bei mehr als einer. Titel und
        Familien sind mit <br> getrennt (ein einfacher Zeilenumbruch wuerde in
        HTML zu einem Absatz verschmelzen), die Gruppen zusaetzlich durch eine
        Leerzeile (<br><br>). Keine Tabelle. Ohne betroffene Modelle bleibt der
        Text leer.

        Die Namen stammen aus den Modelldefinitionen und gehen durch
        html.escape(), weil die Liste als gr.HTML ausgegeben wird.

        Auch hier gilt die grobe Pruefung: gelistet ist, wer irgendeinen
        Enhancer-Anweisungs-Schluessel mitbringt. Ob der Host ihn im gewaehlten
        Modus benutzt, haengt zusaetzlich am Modus (die erste Ziffer im Modus
        waehlt ein Profil) und wird hier nicht entschieden.
        """
        groups = getattr(overrides, "groups", None)
        if groups is None and isinstance(overrides, (list, tuple)):
            groups = overrides
        rendered_groups = []
        for entry in groups or ():
            try:
                label, families = entry
            except (TypeError, ValueError):
                continue
            lines = []
            for family in families or ():
                name = str(getattr(family, "name", family) or "").strip()
                if not name:
                    continue
                try:
                    count = int(getattr(family, "count", 1) or 1)
                except (TypeError, ValueError):
                    count = 1
                suffix = f" ({count})" if count > 1 else ""
                lines.append(html.escape(name) + suffix)
            if not lines:
                continue
            rendered_groups.append(
                "<b>" + html.escape(str(label)) + "</b><br>"
                + "<br>".join(lines)
            )
        return "<br><br>".join(rendered_groups)

    @staticmethod
    def _model_check_box(content):
        """Liste in die scrollbare Box legen (feste Hoehe, eigener Scrollbalken).

        Der Stil sitzt inline am umschliessenden div - _UI_CSS bleibt unberuehrt.
        """
        return f'<div style="{_MODEL_CHECK_BOX_STYLE}">{content}</div>'

    # -------------------------------------------------------- Zwischenspeicher

    @staticmethod
    def _model_check_cache_path():
        """Pfad des Zwischenspeichers: enhancer_models.json neben plugin.py."""
        return Path(__file__).resolve().parent / _MODEL_CHECK_CACHE_NAME

    @classmethod
    def _read_model_check_cache(cls):
        """Zwischenspeicher lesen. Fehlende oder kaputte Datei ergibt None."""
        try:
            with open(cls._model_check_cache_path(), "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    @classmethod
    def _write_model_check_cache(cls, payload):
        """Ergebnis des Checks ablegen (JSON, UTF-8)."""
        with open(cls._model_check_cache_path(), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    @classmethod
    def _model_check_texts(cls):
        """(Liste, Status) fuer den Tab-Aufbau - ausschliesslich aus dem Speicher.

        Beim Aufbau des Tabs wird nichts berechnet: ohne (oder mit kaputtem)
        Zwischenspeicher steht dort der Hinweis auf den Knopf und eine leere
        Statuszeile.
        """
        payload = cls._read_model_check_cache()
        if payload is None:
            return _MODEL_CHECK_EMPTY, ""
        listing = str(payload.get("list") or "").strip()
        status = str(payload.get("status") or "").strip()
        return (listing or _MODEL_CHECK_EMPTY), status

    @staticmethod
    def _definition_file_count():
        """Definitionsdateien auf der Platte: defaults/*.json + finetunes/*.json.

        Gezaehlt wird im Verzeichnis des Host-Hauptmoduls (`_main("__file__")`,
        beim Start also neben wgp.py). Frueher hing der Zaehler am
        Arbeitsverzeichnis: lief der Prozess woanders, fand er still 0 Dateien
        und der Hinweis "model files on disk are not loaded yet" verschwand.
        Ist der Pfad des Hauptmoduls nicht zu bekommen (oder nicht benutzbar),
        bleibt das Arbeitsverzeichnis die Basis.

        Rein informativ: ist die Zahl groesser als die der Katalogeintraege, hat
        der Host noch nicht alle Modelle aufgeloest. Fehler (fehlender Ordner,
        keine Rechte) werden verschluckt - der Check darf daran nicht scheitern.
        """
        count = 0
        try:
            main_file = _main("__file__", "")
            base = Path(".")
            if isinstance(main_file, str) and main_file.strip():
                host_dir = Path(main_file).resolve().parent
                if host_dir.is_dir():
                    base = host_dir
            for folder in ("defaults", "finetunes"):
                count += len(list(base.joinpath(folder).glob("*.json")))
        except Exception:  # noqa: BLE001 - Zaehler ist nur Beiwerk
            return 0
        return count

    # ------------------------------------------------- aktuelles Modell (live)

    def _resolve_current_model_type(self, state_value):
        """Interner Typ des aktuellen Modells - "" wenn nicht ermittelbar.

        Reihenfolge, alle Quellen im Host-Quelltext verifiziert:
        1. `get_state_model_type` (wgp.py:356-358): liefert
           `state["model_type"]`, bei aktivem Bearbeiten `state["edit_model_type"]`
           (wgp.py:357). Die Funktion ist in setup_ui() per request_global
           angefragt und liegt damit als Attribut an.
        2. Derselbe Schluessel direkt aus dem Settings-Snapshot des state, falls
           der Host die Funktion einmal nicht bereitstellt.
        3. `server_config["last_model_type"]` aus den Globals des Hauptmoduls -
           der Host schreibt den Schluessel bei jedem Modellwechsel (wgp.py:10728)
           und liest ihn beim Start aus der gespeicherten Config (wgp.py:3366).

        Jede Stufe steht in try/except: die Zeile darf nie werfen, im Zweifel
        gilt "unknown".
        """
        resolver = getattr(self, "get_state_model_type", None)
        if callable(resolver) and isinstance(state_value, dict):
            try:
                model_type = resolver(state_value)
            except Exception:  # noqa: BLE001 - Snapshot kann unvollstaendig sein
                model_type = None
            if model_type:
                return str(model_type)
        if isinstance(state_value, dict):
            try:
                key = (
                    "model_type"
                    if state_value.get("active_form", "add") == "add"
                    else "edit_model_type"
                )
                model_type = state_value.get(key)
            except Exception:  # noqa: BLE001 - siehe oben
                model_type = None
            if model_type:
                return str(model_type)
        config = _main("server_config") or {}
        if isinstance(config, dict) and config.get("last_model_type"):
            return str(config["last_model_type"])
        return ""

    def _current_model_line(self, state_value):
        """Sichtbare Zeile zum aktuellen Modell (englisch, wortgetreu).

        Die Entscheidung "eigenes Anweisungen?" nutzt die vorhandene Erkennung
        des Plugins (_has_enhancer_instructions) gegen den Katalog aus
        `_main("models_def")` - nur lesend, kein refresh_model_defs, kein
        map_family_handlers, kein Host-Import. Ist der Typ nicht ermittelbar oder
        nicht im Katalog, steht dort "unknown." - ohne Fehler. Die Zeile wird
        NICHT zwischengespeichert: sie haengt am Live-Zustand und wird bei jedem
        Tab-Aufbau und Tab-Wechsel neu berechnet.
        """
        try:
            model_type = self._resolve_current_model_type(state_value)
            if not model_type:
                return _MODEL_CHECK_CURRENT_UNKNOWN
            models_def = _main("models_def") or {}
            model_def = (
                models_def.get(model_type) if isinstance(models_def, dict) else None
            )
            if not isinstance(model_def, dict):
                return _MODEL_CHECK_CURRENT_UNKNOWN
            name = str(model_def.get("name") or "").strip() or str(model_type)
            if self._has_enhancer_instructions(model_def):
                return _MODEL_CHECK_CURRENT_OWN.format(name=name)
            return _MODEL_CHECK_CURRENT_PLAIN.format(name=name)
        except Exception:  # noqa: BLE001 - die Zeile darf nie werfen
            return _MODEL_CHECK_CURRENT_UNKNOWN

    def _run_model_check(self):
        """Knopf "Check models": Katalog lesen, zaehlen, rendern, ablegen.

        Der Katalog kommt ausschliesslich aus `_main("models_def")` und wird nur
        GELESEN - der Host wird nicht zum Neuaufloesen bewegt (kein
        refresh_model_defs, kein map_family_handlers, kein Import von
        Host-Modulen). Der Klick laeuft in der Host-Oberflaeche, deshalb darf
        hier nichts nach aussen fliegen: der Rumpf steht in try/except und
        liefert im Fehlerfall HTML statt einer Exception.
        """
        try:
            models_def = _main("models_def") or {}
            overrides = self._collect_enhancer_overrides(models_def)
            examined = int(getattr(overrides, "examined", 0) or 0)
            affected = int(getattr(overrides, "affected", 0) or 0)
            listing = self._render_enhancer_overrides(overrides)
            stamp = time.strftime("%Y-%m-%d %H:%M")
            files = self._definition_file_count()
            if not examined:
                # Leerer Katalog: verstaendliche Zeile statt einer leeren Liste.
                listing = _MODEL_CHECK_NO_CATALOG
                status = f"Checked {stamp} - the model catalog is empty, nothing to check."
            else:
                status = f"Checked {stamp} - {affected} of {examined} model definitions"
                if files > examined:
                    status += (
                        f" - {files - examined} model files on disk are not loaded yet, "
                        "refresh the model catalog in WanGP first."
                    )
                if not listing:
                    listing = _MODEL_CHECK_NO_MODEL
            payload = {
                # Zeitstempel als ISO, dazu die beiden Zaehler des Laufs, die
                # Zahl der Katalogeintraege und der fertig gerenderte Listentext.
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "affected": affected,
                "examined": examined,
                "catalog_entries": examined,
                "definitions_on_disk": files,
                "list": listing,
                "status": status,
            }
            try:
                self._write_model_check_cache(payload)
            except Exception as exc:  # noqa: BLE001 - Liste trotzdem anzeigen
                status += f" (Could not save the result: {type(exc).__name__}: {exc})"
            # Der Zwischenspeicher haelt den Listentext OHNE die Box; die
            # scrollbare Huelle kommt erst beim Ausgeben an die Komponente.
            return self._model_check_box(listing), status
        except Exception as exc:  # noqa: BLE001 - der Klick laeuft in der Host-UI
            return self._model_check_box(""), f"**Model check failed:** `{type(exc).__name__}: {exc}`"

    # -------------------------------------------------------------- Kernlogik

    @classmethod
    def _enhancer_images(cls, settings, model_def, model_type, mode, audio_only, prompt_text, live):
        """Bilder fuer den lokalen Enhancer bestimmen.

        Vorbild ist enhance_prompt() (wgp.py:6629-6682), das den eingebauten
        Knopf bedient: aus den Bild-Eingaben werden Kontexte mit Labels gebaut
        (Start-/Endbild, Control Image, Referenzen). Primaerpfad ist derselbe
        prepare_manual()-Aufruf; scheitert er (Fenstermodell, ungewoehnliche
        Eingaben), wird auf die einfache Auswahl zurueckgefallen, die
        process_prompt_enhancer() selbst kennt (select_images,
        shared/prompt_enhancer/images.py:247-257).

        Nur ein Modus mit "I" benutzt Bilder (WanGPs eigene Bedingung,
        images.py:20). Ohne "I" bleibt alles leer - der Klick laeuft dann wie
        bisher als reiner Textauftrag.
        """
        from shared.prompt_enhancer import images as prompt_enhancer_images

        if "I" not in str(mode or ""):
            return _EnhancerImages(None, None, {}, ())

        convert_image = _main("convert_image")
        if not callable(convert_image):
            print(f"[{PlugIn_Name}] convert_image() not found - images are ignored.")
            return _EnhancerImages(None, None, {}, ())

        # Live-Komponenten schlagen den Snapshot: der wird beim Hinzufuegen eines
        # Bildes nicht fortgeschrieben (siehe _IMAGE_INPUT_NAMES).
        inputs = dict(settings or {})
        inputs.update(
            {key: value for key, value in (live or {}).items() if value is not None}
        )
        image_prompt_type = inputs.get("image_prompt_type") or ""
        video_prompt_type = inputs.get("video_prompt_type") or ""
        inputs["image_prompt_type"] = image_prompt_type
        inputs["video_prompt_type"] = video_prompt_type
        try:
            inputs["image_mode"] = int(inputs.get("image_mode") or 0)
        except (TypeError, ValueError):
            inputs["image_mode"] = 0

        get_fps = _main("get_computed_fps")
        get_base = _main("get_base_model_type")
        estimate_overlap = _main("estimate_first_window_overlap_frames")
        multi_output = _main("prompt_enhancer_outputs_multiple_prompts")

        if callable(get_fps) and callable(get_base):
            fps = get_fps(
                inputs.get("force_fps", "auto"),
                get_base(model_type),
                inputs.get("video_guide"),
                inputs.get("video_source"),
            )
        else:
            fps = 16
        if callable(estimate_overlap):
            source_frames = estimate_overlap(
                inputs.get("image_start"),
                inputs.get("video_source")
                if ("V" in image_prompt_type or "L" in image_prompt_type)
                else None,
                inputs.get("keep_frames_video_source"),
                fps,
            )
        else:
            source_frames = 1 if inputs.get("image_start") else 0
        multi_prompt_output = (
            bool(multi_output(mode)) if callable(multi_output) else ("M" in str(mode))
        )

        contexts = None
        try:
            _prompts, contexts = prompt_enhancer_images.prepare_manual(
                [prompt_text],
                inputs,
                model_def or {},
                fps=fps,
                source_frames=source_frames,
                open_image=convert_image,
                multi_prompt_output=multi_prompt_output,
            )
        except Exception as exc:  # noqa: BLE001 - Fallback statt Fehlermeldung
            print(
                f"[{PlugIn_Name}] Could not prepare the image contexts "
                f"({type(exc).__name__}: {exc}) - using the simple selection."
            )

        if contexts:
            labels = tuple(label for context in contexts for label in context.labels)
            return _EnhancerImages(
                None,
                None,
                {
                    "image_prompt_type": image_prompt_type,
                    "video_prompt_type": video_prompt_type,
                    "image_contexts": contexts,
                },
                labels,
            )

        # Fallback: genau das, was process_prompt_enhancer() ohne Kontexte selbst
        # auswaehlt - Startbild (sonst Endbild) plus erste Referenz.
        sliding = (
            bool((model_def or {}).get("sliding_window", False))
            and inputs["image_mode"] == 0
            and not audio_only
        )
        start_value = inputs.get("image_start") if "S" in image_prompt_type else None
        if sliding and (model_def or {}).get("fake_start_image", False):
            # prepare_manual verwirft den Fake-Anker nur im Sliding-Zweig
            # (images.py:201) - der Fallback hier haelt sich daran.
            start_value = None
        from_end = start_value is None
        if from_end:
            start_value = inputs.get("image_end") if "E" in image_prompt_type else None
        reference_value = inputs.get("image_refs") if "I" in video_prompt_type else None
        try:
            control_image = prompt_enhancer_images.control_image_input(inputs)
        except Exception:  # noqa: BLE001
            control_image = None

        def _open(gallery):
            items = gallery if isinstance(gallery, list) else ([gallery] if gallery else [])
            opened = []
            for item in items:
                if item is None:
                    continue
                try:
                    opened.append(
                        convert_image(item[0] if isinstance(item, (list, tuple)) else item)
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[{PlugIn_Name}] Could not open an image: {type(exc).__name__}: {exc}")
            return opened

        labels = []
        image_start = _open(start_value)[:1] or None
        if image_start:
            labels.append("end image" if from_end else "start image")
        image_refs = _open(reference_value) or None
        for index in range(1, len(image_refs or []) + 1):
            labels.append(prompt_enhancer_images.reference_name(index))
        # control_image nutzt der Aufruf nur als Ersatz-Startbild (wgp.py:6394).
        if control_image is not None and not image_start:
            labels.append("Control Image")

        return _EnhancerImages(
            image_start,
            image_refs,
            {
                "image_prompt_type": image_prompt_type,
                "video_prompt_type": video_prompt_type,
                "control_image": control_image,
            },
            tuple(labels),
        )

    def enhance(self, state, text, *values):
        """Lokalen Enhancer auf `text` anwenden. Laeuft im GPU-Kontext.

        `values` sind erst der Modus, dann die Regler (Think/Min/Max),
        danach die Bild-Eingaben - siehe _split_mode_input() und
        _split_image_inputs().
        """
        mode_value, values = self._split_mode_input(values)
        controls, live_images = self._split_image_inputs(values)
        think, min_words, max_words = self._read_controls(controls)
        self._remember_word_range(min_words, max_words)
        text = str(text or "").strip()
        if not text:
            return "", "Enter a prompt first."

        if not self._local_enhancer_ready():
            return "", (
                "**No local enhancer model configured.**\n\n"
                "Set *Configuration → Prompt Enhancer / Deepy → Prompt Enhancer / Deepy LLM Engine* "
                "to a local Qwen model (4B, 9B or 27B) and save. The enhancer then "
                "uses that model even while Deepy stays remote."
            )

        get_state_model_type = _main("get_state_model_type")
        get_model_def = _main("get_model_def")
        get_model_settings = _main("get_model_settings")
        ensure_loaded = _main("ensure_prompt_enhancer_loaded")
        process = _main("process_prompt_enhancer")
        unload_runtime = _main("unload_prompt_enhancer_runtime")
        wait_for_unload = _main("wait_for_model_unload")

        if not all((get_state_model_type, get_model_def, ensure_loaded, process)):
            return "", "**Internal error:** WanGP functions not found. Please report."

        model_type = get_state_model_type(state)
        if not model_type:
            return "", "No model selected - pick one in the Media Generator first."

        model_def = get_model_def(model_type) or {}
        settings = get_model_settings(state, model_type) or {}
        audio_only = bool(model_def.get("audio_only", False))
        try:
            image_mode = int(settings.get("image_mode", 0) or 0)
        except (TypeError, ValueError):
            image_mode = 0
        is_image = image_mode > 0
        # Checkbox "Think" -> 'K' im Modus. Ohne das denkt die 27B nie. Der Modus
        # selbst kommt live aus WanGPs verstecktem `prompt_enhancer`-Text, nur
        # bei leerem Wert aus dem Modell-Default.
        mode = self._effective_mode(mode_value, model_def, audio_only, image_mode)
        # 'K' nur anfassen, wenn die Think-Checkbox wirklich aufgeloest wurde:
        # fehlt sie, bleibt think=False, und _with_thinking() wuerde ein 'K' aus
        # WanGPs Checkbox entfernen, das der Remote-Pfad (ohne _with_thinking)
        # behaelt.
        if getattr(self, "_think_checkbox", None) is not None:
            mode = self._with_thinking(mode, think)

        # Ans Modell geht nur der sichtbare Prompt, nicht die Historienzeile:
        # sonst wird '#!PROMPT!:' mitverbessert und erscheint danach doppelt.
        enhancer_input = self._visible_prompt(text)
        if not enhancer_input:
            return "", "Der Prompt besteht nur aus Kommentar-/Historienzeilen."

        if callable(wait_for_unload):
            wait_for_unload()
        acquire_GPU_ressources(state, PlugIn_Id, PlugIn_Name, gr=gr)
        started = time.time()

        # Der lokale Pfad muss ERZWUNGEN werden. process_prompt_enhancer() prueft
        # selbst noch einmal resolve_role_engine(server_config, "prompt_enhancer")
        # und schickt die Anfrage sonst an die Remote-Engine (wgp.py:6409) - der
        # lokale Loader allein genuegt also nicht. Genau daran ist der erste
        # Versuch dieses Plugins gescheitert: die 9B wurde geladen, geantwortet
        # hat trotzdem OpenCode.
        config = _main("server_config") or {}
        llm_section = config.get("llm_engines")

        # Der Knopf heisst "Local 27B" - also muss auch die 27B geladen werden,
        # selbst wenn die Config als lokales Modell eine andere Groesse fuehrt.
        # ensure_prompt_enhancer_loaded() laedt NICHT neu, solange ueberhaupt
        # etwas geladen ist (if enhancer_offloadobj is None) - ohne den Reset
        # wuerde stillschweigend weiter das alte Modell antworten.
        previous_enhancer = config.get("enhancer_enabled")
        previous_quant = config.get("prompt_enhancer_quantization")
        swapped_model = False
        if int(previous_enhancer or 0) != 5 or str(previous_quant or "") != "gguf_ptq1":
            config["enhancer_enabled"] = 5
            config["prompt_enhancer_quantization"] = "gguf_ptq1"
            swapped_model = True
            reset_enhancer = _main("reset_prompt_enhancer")
            if callable(reset_enhancer):
                reset_enhancer()

        local_engine = self._local_engine_name()
        previous_engine = None
        flipped = False
        if isinstance(llm_section, dict) and llm_section.get("deepy") != local_engine:
            previous_engine = llm_section.get("deepy")
            llm_section["deepy"] = local_engine
            flipped = True

        try:
            # Bilder erst hier bestimmen: die Engine steht jetzt lokal und das
            # Modell auf 27B, genau wie beim Aufruf selbst (images.enabled()
            # prueft beides, shared/prompt_enhancer/images.py:20).
            images = self._enhancer_images(
                settings, model_def, model_type, mode, audio_only, enhancer_input, live_images
            )
            ensure_loaded(override_profile=-1)
            prompts = process(
                model_type,
                model_def,
                mode,
                [enhancer_input],
                images.image_start,
                images.image_refs,
                is_image,
                audio_only,
                -1,        # seed -> zufaellig
                # Wortgrenze steckt in den Anweisungen; das Token-Budget muss
                # mitwachsen, sonst schneidet das Limit den Prompt ab. Mit Bildern
                # gelten die Bild-Anweisungen (IT2x), sonst die reinen Text-T2x.
                prompt_enhancer_instructions=self._fallback_instructions(
                    is_image, audio_only, min_words, max_words,
                    with_images=bool(images.labels),
                ),
                text_encoder_max_tokens=self._output_token_budget(min_words, max_words),
                enhancer_kwargs=images.kwargs or None,
            )
        except Exception as exc:  # noqa: BLE001 - Fehler soll in der UI landen
            return "", f"**Enhancer failed:** `{type(exc).__name__}: {exc}`"
        finally:
            # Engine sofort zurueckstellen - sie darf keinen Moment laenger
            # verstellt bleiben als der Aufruf dauert.
            if flipped and isinstance(llm_section, dict):
                llm_section["deepy"] = previous_engine
            # Auch das lokale Modell zurueckstellen, falls wir es getauscht haben.
            if swapped_model:
                config["enhancer_enabled"] = previous_enhancer
                config["prompt_enhancer_quantization"] = previous_quant
            # Modell sofort wieder freigeben: es teilt sich den VRAM mit dem
            # Generierungsmodell, und ein zweiter Klick laedt es in Sekunden neu.
            try:
                if callable(unload_runtime):
                    unload_runtime()
                offloadobj = _main("enhancer_offloadobj")
                if offloadobj is not None:
                    offloadobj.unload_all()
            except Exception:
                pass
            release_GPU_ressources(state, PlugIn_Id)

        if not prompts:
            return "", "The enhancer returned no prompt."
        # process_prompt_enhancer() liefert pro Prompt eine Liste - WanGP liest
        # das Ergebnis ebenfalls als value[0] aus (siehe wgp.py:6696).
        first = prompts[0] if isinstance(prompts, (list, tuple)) else prompts
        while isinstance(first, (list, tuple)):
            first = first[0] if first else ""
        result = str(first or "").strip()
        if not result:
            return "", "The enhancer returned an empty prompt."
        self._last_enhanced = result
        self._last_source = text
        self._last_image_labels = images.labels
        seconds = time.time() - started
        return result, (
            f"Enhanced locally with **{self._variant_label()}** "
            f"(mode `{mode}`{self._image_note(images.labels)}) in {seconds:.1f}s. "
            "Not happy? Click again."
        )

    @staticmethod
    def _sanitize_original(text):
        """Marker- und Kommentarzeilen aus einem Original entfernen.

        Steht dort bereits '#!PROMPT!: #!PROMPT!:', bleibt nach dem Abtragen
        aller fuehrenden Marker nichts uebrig - die Verdopplung wird also
        bereinigt statt weitergetragen.
        """
        parts = []
        for raw_line in str(text or "").replace("\r\n", "\n").split("\n"):
            line = raw_line.strip()
            while line.startswith(PROMPT_UNIT_PREFIX):
                line = line[len(PROMPT_UNIT_PREFIX):].strip()
            if not line or line.startswith("#"):
                continue
            parts.append(line)
        return " ".join(parts).strip()

    @classmethod
    def _visible_prompt(cls, text):
        """Sichtbaren Prompt ohne Historien-/Kommentarzeilen.

        Ein '#!PROMPT!:'-Block ist reine Information fuer die Anzeige. Ginge er
        ans Modell, wuerde er mitverbessert - und stuende danach doppelt da.
        """
        raw = str(text or "").replace("\r\n", "\n").strip()
        if not raw:
            return ""
        try:
            units = split_prompt_units(raw, "FG")
            if units:
                visible = str(units[0] or "").strip()
                if visible:
                    return visible
        except Exception:
            pass
        # split_prompt_units verwirft jede Zeile, die mit '#' beginnt - also auch
        # eine Zeile, die nur aus Markern plus Text besteht. Dann selbst abtragen.
        parts = []
        for raw_line in raw.split("\n"):
            line = raw_line.strip()
            while line.startswith(PROMPT_UNIT_PREFIX):
                line = line[len(PROMPT_UNIT_PREFIX):].strip()
            if not line or line.startswith("#"):
                continue
            parts.append(line)
        return "\n".join(parts).strip()

    @classmethod
    def _original_for_history(cls, source):
        """Urspruenglichen Prompt fuer die Historienzeile bestimmen.

        Enthaelt der Quelltext schon eine Historienzeile, wird deren Inhalt
        weiterverwendet (die Herkunft bleibt erhalten), sonst der sichtbare
        Text. Das Ergebnis wird von Markern bereinigt, damit ein bereits
        verdoppelter Block nicht erhalten bleibt.
        """
        raw = str(source or "").replace("\r\n", "\n").strip()
        if not raw:
            return ""
        candidate = ""
        try:
            originals = split_prompt_units(raw, "FG", originals=True)
            if originals:
                candidate = cls._sanitize_original(originals[0])
        except Exception:
            candidate = ""
        return candidate or cls._sanitize_original(raw)

    def _with_history(self, enhanced):
        """Historienzeile wie beim eingebauten Knopf voranstellen.

        Ergebnis::

            #!PROMPT!: der urspruengliche Prompt
            der verbesserte Prompt

        Dafuer wird WanGPs eigene Funktion benutzt, damit Format und
        Bereinigung (Zeilenumbrueche, Slash-Bloecke) identisch sind. Beim
        Generieren verwirft split_prompt_units() jede Zeile, die mit '#' beginnt,
        die Zeile ist also reine Information und stoert das Ergebnis nicht.
        """
        enhanced = str(enhanced or "").strip()
        if not enhanced:
            return enhanced
        # Steckt bereits ein Marker im Ergebnis, ist es schon eine gueltige
        # Historie - dann darf kein zweiter davor gesetzt werden.
        if PROMPT_UNIT_PREFIX in enhanced:
            return enhanced
        source = self._original_for_history(self._last_source)
        if not source or enhanced == source:
            return enhanced
        try:
            return serialize_prompt_blocks_with_prefix([enhanced], [source])
        except Exception:
            return enhanced

    @staticmethod
    def _remote_server_command(engine):
        """Start command and address of the remote engine, for the help text."""
        from urllib.parse import urlparse

        config = _main("server_config") or {}
        llm = config.get("llm_engines") or {}
        profile = (llm.get("profiles") or {}).get(engine) or {}
        base_url = str(profile.get("base_url", "") or "").rstrip("/")
        executable = str(profile.get("executable", "opencode") or "opencode")
        return base_url or "<not configured>", executable, (urlparse(base_url).port or 4096)

    def enhance_remote(self, state, text, *values):
        """Verbessern ueber die Remote-Engine - ohne lokalen Modell-Load.

        Anders als enhance() wird hier kein VRAM belegt: process_prompt_enhancer()
        erkennt an der Engine, dass remote gearbeitet wird (wgp.py:6409), und
        ueberspringt den lokalen Loader (local_runtime, wgp.py:6505).

        `values` sind erst der Modus, dann die Regler (Think/Min/Max).
        """
        mode_value, values = self._split_mode_input(values)
        think, min_words, max_words = self._read_controls(values)
        self._remember_word_range(min_words, max_words)
        text = str(text or "").strip()
        if not text:
            return "", "Enter a prompt first."

        engine = self._remote_engine_name()
        if not engine:
            return "", (
                "**No remote engine configured.** Pick one in the Config tab "
                "under *Prompt Enhancer / Deepy*."
            )

        get_state_model_type = _main("get_state_model_type")
        get_model_def = _main("get_model_def")
        get_model_settings = _main("get_model_settings")
        process = _main("process_prompt_enhancer")
        if not all((get_state_model_type, get_model_def, process)):
            return "", "**Internal error:** WanGP functions not found. Please report."

        model_type = get_state_model_type(state)
        if not model_type:
            return "", "No model selected - pick one in the Media Generator first."

        model_def = get_model_def(model_type) or {}
        settings = get_model_settings(state, model_type) or {}
        audio_only = bool(model_def.get("audio_only", False))
        try:
            image_mode = int(settings.get("image_mode", 0) or 0)
        except (TypeError, ValueError):
            image_mode = 0
        is_image = image_mode > 0
        # Wie in enhance(), nur ohne Think: der Modus kommt live aus WanGPs
        # verstecktem `prompt_enhancer`-Text, sonst aus dem Modell-Default.
        mode = self._effective_mode(mode_value, model_def, audio_only, image_mode)

        enhancer_input = self._visible_prompt(text)
        if not enhancer_input:
            return "", "Der Prompt besteht nur aus Kommentar-/Historienzeilen."

        # Engine nur fuer diesen Aufruf umstellen; danach exakt zurueck.
        config = _main("server_config") or {}
        llm_section = config.get("llm_engines")
        previous_engine = None
        flipped = False
        if isinstance(llm_section, dict) and llm_section.get("deepy") != engine:
            previous_engine = llm_section.get("deepy")
            llm_section["deepy"] = engine
            flipped = True

        # Denk-Level ebenfalls nur fuer diesen Aufruf setzen. create_backend()
        # liest das Profil erst im Aufruf (registry.py:11-13), die Aenderung
        # wirkt also sofort - und wird unten exakt zurueckgesetzt.
        profiles = llm_section.get("profiles") if isinstance(llm_section, dict) else None
        profile = profiles.get(engine) if isinstance(profiles, dict) else None
        previous_effort = None
        effort_changed = False
        effort = ""
        if isinstance(profile, dict):
            effort = self._remote_reasoning_effort(profile, think)
            if effort:
                previous_effort = profile.get("reasoning_effort")
                if str(previous_effort or "") != effort:
                    profile["reasoning_effort"] = effort
                    effort_changed = True
        started = time.time()
        try:
            prompts = process(
                model_type,
                model_def,
                mode,
                [enhancer_input],
                None,      # image_start
                None,      # original_image_refs
                is_image,
                audio_only,
                -1,        # seed -> zufaellig
                # Ohne Anweisung geht ein LEERER System-Prompt an die Remote-
                # Engine und der Agent fragt zurueck statt umzuschreiben.
                prompt_enhancer_instructions=self._fallback_instructions(is_image, audio_only, min_words, max_words),
                text_encoder_max_tokens=self._output_token_budget(min_words, max_words),
            )
        except Exception as exc:  # noqa: BLE001 - Fehler soll in der UI landen
            import traceback
            traceback.print_exc()
            print(f"[{PlugIn_Name}] Remote enhancer failed: {type(exc).__name__}: {exc}")
            return "", f"**Remote enhancer failed:** `{type(exc).__name__}: {exc}`"
        finally:
            if flipped and isinstance(llm_section, dict):
                llm_section["deepy"] = previous_engine
            if effort_changed and isinstance(profile, dict):
                profile["reasoning_effort"] = previous_effort

        result = self._first_prompt(prompts)
        if not result:
            return "", "The enhancer returned an empty prompt."
        self._last_enhanced = result
        self._last_source = text
        seconds = time.time() - started
        effort_note = f" Reasoning effort `{effort}`." if effort else ""
        return result, (
            f"Enhanced remotely with **{engine}** (mode `{mode}`) in {seconds:.1f}s."
            f"{effort_note}{self._word_note(min_words, max_words)}. No local VRAM used."
        )

    def write_back(self, state, text):
        """Verbesserten Prompt in den Entwurf des Media Generators uebernehmen."""
        text = str(text or "").strip()
        if not text:
            return time.time(), "Nothing to apply."
        get_settings = self.get_current_model_settings
        try:
            settings = get_settings(state)
            settings["prompt"] = self._with_history(text)
        except Exception as exc:  # noqa: BLE001
            return time.time(), f"**Apply failed:** `{exc}`"
        return time.time(), "Applied to the Media Generator prompt."

    # ------------------------------------------------- Knopf neben dem Original

    def _info_tooltip_js(self):
        """Hover-Tooltips fuer die beiden Knoepfe.

        field_help.bind() scheidet aus: sein JavaScript verschiebt den Marker in
        den [data-testid="block-info"]-Label seines Ziels, und Knoepfe haben
        keinen - der Marker bliebe als eigene Komponente in der Reihe stehen und
        zerlegte das Layout. Ein title-Attribut braucht kein zusaetzliches
        Element und kann daher nichts verschieben.
        """
        import json

        engine = self._remote_engine_name()
        base_url, _exe, _port = self._remote_server_command(engine)
        tips = {
            "local_enhance_remote_btn": (
                f"{self._remote_button_label()} - enhance remotely\n"
                f"Engine: {engine or 'not configured'}\n"
                "No local VRAM; the engine is switched for this click only.\n"
                f"WanGP starts the server at {base_url} on demand and applies the\n"
                "OpenCode configuration from the settings when it does.\n"
                "The plugin supplies the enhancer instructions, so the agent\n"
                "rewrites the prompt instead of asking a question.\n"
                "Think: sends the highest reasoning level of the selected model;\n"
                "unticked it sends the lowest one - providers have no real off.\n"
                "Words: the Min words / Max words fields at the top of the\n"
                "plugin tab apply to this click (0 removes that bound)."
            ),
            "local_enhance_local_btn": (
                f"{self._button_label()} - enhance on this GPU\n"
                "Uses Qwen3.8-27B and forces it even if the config selects\n"
                "another local model.\n"
                "An already loaded model is unloaded first, so this can take\n"
                "30-60 s. No remote tokens are used.\n"
                "Think: Qwen reasons before rewriting, with its own thinking\n"
                "budget; unticked it answers straight away.\n"
                "Words: the Min words / Max words fields at the top of the\n"
                "plugin tab apply to this click and the token budget grows\n"
                "with max (0 removes that bound).\n"
                "Images: in mode 'Based on Text Prompt and Images' the selected\n"
                "start/end/reference images are read by the vision part of the\n"
                "model; every other mode stays text-only."
            ),
        }
        return """
(function () {
  var style = document.createElement('style');
  style.textContent = __CSS__;
  document.head.appendChild(style);
  var tips = __TIPS__;
  function apply() {
    Object.keys(tips).forEach(function (id) {
      var host = document.getElementById(id);
      if (!host) return;
      var btn = host.tagName === 'BUTTON' ? host : host.querySelector('button');
      if (btn && !btn.title) btn.title = tips[id];
    });
  }
  apply();
  var n = 0;
  var t = setInterval(function () { apply(); if (++n > 60) clearInterval(t); }, 500);
})();
""".replace("__TIPS__", json.dumps(tips, ensure_ascii=False)).replace(
            "__CSS__", json.dumps(_UI_CSS, ensure_ascii=False)
        )

    def create_inline_button(self):
        """Zeile 1: Beschriftung, beide Knoepfe und die Think-Checkbox.
        Zeile 2: nur noch das Modus-Dropdown des Hosts.

        Die beiden Wort-Regler (Min words / Max words) entstehen hier, weil die
        Knoepfe sie schon jetzt als Klick-Eingaben brauchen. Angezeigt werden sie
        aber im Plugin-Tab: create_ui() laeuft laut Host erst nach dieser
        Funktion (wgp.py:13628 vor 13976) und holt sie mit
        _attach_word_fields() dorthin.

        run_component_insertion_and_setup() verschiebt nur das ZULETZT erzeugte
        Kind an die Zielposition (shared/utils/plugins.py:1659). Diese Reihe ist
        das einzige neue Kind, landet also direkt hinter dem ausgeblendeten
        Original-Knopf und damit VOR dem Dropdown. Das Dropdown wird per CSS
        (flex-basis:100%) in die zweite Zeile gezwungen.

        Die Info steckt als Hover-Tooltip an den Knoepfen selbst (siehe
        _info_tooltip_js) - kein zusaetzliches Element, das die Reihe sprengen
        koennte.
        """
        prompt_component = getattr(self, "prompt", None)
        if prompt_component is None:
            # Ohne Zugriff auf das Prompfeld waeren die Knoepfe nutzlos.
            return gr.Button(self._button_label(), visible=False)

        remote_label = self._remote_button_label()
        # Startwerte der beiden Felder kommen nur noch aus der Config
        # (_word_range), Presets gibt es nicht mehr.
        min_words, max_words = self._word_range()

        with gr.Row(elem_id="local_enhance_row") as button_row:
            gr.HTML(
                "<span style='font-weight:600; white-space:nowrap;'>Enhance Prompt:</span>",
                elem_classes=["local-enhance-label"],
            )
            # size="sm" + scale=0: die Knoepfe nehmen nur ihre naturale Breite
            # statt die halbe Reihe zu fuellen.
            remote_btn = gr.Button(
                f"{remote_label} \u24d8", size="sm", scale=0, min_width=0,
                elem_id="local_enhance_remote_btn", elem_classes="btn_centered",
            )
            local_btn = gr.Button(
                f"{self._button_label()} \u24d8", size="sm", scale=0, min_width=0,
                elem_id="local_enhance_local_btn", elem_classes="btn_centered",
            )
            # Wortgrenze: die beiden Zahlenfelder fuer Min und Max. Sie entstehen
            # hier, weil die Klick-Verdrahtung weiter unten sie schon braucht -
            # angezeigt werden sie aber nicht in Zeile 1, sondern ganz oben im
            # Plugin-Tab: _attach_word_fields() holt sie in create_ui() dorthin.
            # Bis dahin parken sie in dieser Knopfreihe.
            # min_width gibt die sichtbare Breite vor (scale=0: naturale Breite
            # statt ueber die Zeile wachsen), ohne eigene CSS-Regel.
            min_field = gr.Number(
                value=min_words,
                label="Min words",
                show_label=True,
                precision=0,
                minimum=0,
                maximum=_WORD_LIMIT_MAX,
                step=10,
                scale=0,
                min_width=_WORD_FIELD_WIDTH,
                elem_id="local_enhance_min_words",
            )
            max_field = gr.Number(
                value=max_words,
                label="Max words",
                show_label=True,
                precision=0,
                minimum=0,
                maximum=_WORD_LIMIT_MAX,
                step=10,
                scale=0,
                min_width=_WORD_FIELD_WIDTH,
                elem_id="local_enhance_max_words",
            )
            words_children = (min_field, max_field)

        # Die Regler aus ihrem gr.Form-Wrapper loesen: Gradio gruppiert
        # aufeinanderfolgende Formularfelder, sie stecken also gemeinsam in einem
        # Wrapper, der hier leer laeuft und verschwindet.
        ours = {id(child) for child in words_children}
        try:
            for candidate in list(getattr(button_row, "children", []) or []):
                inner = getattr(candidate, "children", None)
                if not inner or not any(id(item) in ours for item in inner):
                    continue
                for item in list(inner):
                    if id(item) in ours:
                        inner.remove(item)
                        item.parent = None
                if not inner and any(existing is candidate for existing in button_row.children):
                    button_row.children.remove(candidate)
        except Exception as exc:  # noqa: BLE001
            print(f"[{PlugIn_Name}] Could not unwrap the word-limit fields: {exc}")

        # Nach dem Auspacken haengen die Felder in keinem Container mehr. Sie
        # kommen zurueck in die Knopfreihe: _attach_word_fields() braucht einen
        # bekannten Elterncontainer, aus dem es sie entfernen kann, und bis
        # create_ui() laeuft, ist das hier ihr einziger. Beim Umzug in den Tab
        # werden sie wieder entfernt - sichtbar sind sie in Zeile 1 also nie.
        self._word_fields_home = button_row
        try:
            for child in words_children:
                if not any(existing is child for existing in button_row.children):
                    button_row.children.append(child)
                child.parent = button_row
        except Exception as exc:  # noqa: BLE001
            print(f"[{PlugIn_Name}] Could not park the word-limit fields: {exc}")

        parent = getattr(button_row, "parent", None)
        think_checkbox = None
        dropdown_container = None

        # Die Think-Checkbox hierher holen. Gradio gruppiert aufeinanderfolgende
        # Formularfelder in EINEN gr.Form-Container, in dem Dropdown und Checkbox
        # gemeinsam liegen (wgp.py:12168-12174) - ein direkter Blick in
        # parent.children findet sie deshalb nicht.
        if parent is not None:
            def _is_think(component):
                return (
                    isinstance(component, gr.Checkbox)
                    and str(getattr(component, "label", "")).strip().lower() == "think"
                )

            found = None
            candidates = list(getattr(parent, "children", []) or [])
            for container in candidates:
                if not getattr(container, "children", None):
                    continue
                for child in list(container.children):
                    if _is_think(child):
                        found = (container, child)
                        break
                if found:
                    break
            if found is None:
                found = next(((parent, child) for child in candidates if _is_think(child)), None)
            if found is not None:
                container, checkbox = found
                try:
                    container.children.remove(checkbox)
                    button_row.children.append(checkbox)
                    checkbox.parent = button_row
                    checkbox.scale = 0          # naturale Breite statt strecken
                    think_checkbox = checkbox
                    dropdown_container = container
                except Exception as exc:  # noqa: BLE001
                    print(f"[{PlugIn_Name}] Could not move the Think checkbox: {exc}")

        # Nach dem Herausholen der Checkbox bleiben leere Formular-Wrapper uebrig.
        # Gradio legt beim Schliessen der Knopfreihe einen gr.Form um die
        # aufeinanderfolgenden Formularfelder (fill_expected_parents,
        # blocks.py:456-479) und registriert ihn in der Komponentenliste des
        # Blocks (root_context.blocks, blocks.py:477). Das Auspacken oben hat den
        # Wrapper aus den Kindern der Reihe genommen, aber nicht aus dieser
        # Liste: dort steht er weiter als leerer "form"-Knoten, obwohl der
        # Layout-Baum ihn nicht mehr kennt - demo.get_config_file() liefert ihn
        # deshalb mit. Entfernt wird er, damit die Komponentenliste der
        # Konfiguration sauber bleibt.
        # Die Massnahme ist rein defensiv: angefasst werden ausschliesslich
        # Container ohne Kinder; Checkbox und Zahlenfelder sind zu diesem
        # Zeitpunkt schon woanders (die Checkbox hier umgehaengt, die
        # Zahlenfelder fuer den Tab geparkt).
        try:
            # Die Komponentenliste haengt am Wurzel-Blocks; er ist ueber die
            # Elternkette erreichbar und traegt default_config (blocks.py:1170).
            registry = None
            node = getattr(button_row, "parent", None)
            walked = set()
            while node is not None and id(node) not in walked:
                walked.add(id(node))
                if hasattr(node, "default_config"):
                    registry = getattr(node, "blocks", None)
                    break
                node = getattr(node, "parent", None)

            def _is_empty_wrapper(candidate):
                """Nur echte BlockContexts ohne Kinder sind Wrapper-Muell."""
                inner = getattr(candidate, "children", None)
                return inner is not None and not inner

            orphans = [
                child
                for child in list(getattr(button_row, "children", []) or [])
                if _is_empty_wrapper(child)
            ]
            if isinstance(registry, dict):
                # Wrapper, die nur noch hier registriert sind: ihr parent zeigt
                # auf die Knopfreihe, in deren Kindern stehen sie nicht mehr.
                orphans += [
                    candidate
                    for candidate in list(registry.values())
                    if getattr(candidate, "parent", None) is button_row
                    and not any(candidate is child for child in button_row.children)
                    and _is_empty_wrapper(candidate)
                ]

            for orphan in orphans:
                if any(orphan is child for child in button_row.children):
                    button_row.children.remove(orphan)
                unrender = getattr(orphan, "unrender", None)
                if callable(unrender):
                    unrender()      # nimmt ihn aus Layout und Komponentenliste
                if isinstance(registry, dict):
                    registry.pop(getattr(orphan, "_id", None), None)
        except Exception as exc:  # noqa: BLE001
            print(f"[{PlugIn_Name}] Could not drop the empty form wrapper: {exc}")

        # Den Container des Modus-Dropdowns nur noch suchen, um WanGPs Caption
        # wieder einzuschalten - angehaengt wird dort nichts mehr. Der Container
        # ist der gr.Form, in dem die Think-Checkbox lag; fehlt er, wird er ueber
        # das Dropdown gesucht.
        if dropdown_container is None and parent is not None:
            dropdown_container = next(
                (
                    candidate
                    for candidate in (getattr(parent, "children", []) or [])
                    if getattr(candidate, "children", None)
                    and any(isinstance(child, gr.Dropdown) for child in candidate.children)
                ),
                None,
            )
        if dropdown_container is not None:
            # WanGP blendet die Caption des Modus-Dropdowns im On-Demand-Modus aus
            # (wgp.py:12176: show_label = not on_demand_prompt_enhancer), weil dort
            # der eingebaute Knopf daneben steht. Hier steht das Dropdown allein in
            # Zeile 2; ohne Caption sitzt seine Eingabe 32px hoeher als unsere
            # beschrifteten Regler (live gemessen). Die Caption ist WanGPs eigene,
            # wir schalten sie nur ein. Ein Modellwechsel setzt sie nicht zurueck:
            # refresh_prompt_enhancer_labels schickt nur choices (wgp.py:10898).
            mode_dropdown = next(
                (
                    child
                    for child in (getattr(dropdown_container, "children", []) or [])
                    if isinstance(child, gr.Dropdown)
                ),
                None,
            )
            if mode_dropdown is not None:
                mode_dropdown.show_label = True

        # Fuer den Tab-Knopf bereithalten: create_ui() laeuft erst nach dieser
        # Funktion (wgp.py:13628 vor 13976) und verdrahtet dieselben Regler; die
        # beiden Wort-Regler holt es dort mit _attach_word_fields() in den Tab.
        self._think_checkbox = think_checkbox
        self._min_words_field = min_field
        self._max_words_field = max_field

        # Alle Regler gelten fuer BEIDE Knoepfe: die Checkbox schaltet lokal das
        # Denken und remote den Reasoning-Level, Min/Max die Wortgrenze. Fehlt
        # ein Widget, bleibt der jeweilige Default aktiv.
        # Der Modus steht ganz vorne: WanGPs versteckter `prompt_enhancer`-Text
        # traegt die Nutzerauswahl, ohne ihn liefe alles auf dem Modell-Default.
        # Die Bilder haengen nur am lokalen Knopf: nur der lokale 27B-Pfad hat
        # einen Vision-Teil, und sie muessen live aus den Komponenten kommen
        # (der Settings-Snapshot ist nach einem frisch hinzugefuegten Bild alt).
        controls = self._mode_components() + self._control_components()
        image_components = self._image_components()
        remote_btn.click(
            fn=self.enhance_inline_remote,
            inputs=[self.state, prompt_component] + controls,
            outputs=[prompt_component],
            show_progress="hidden",
        )
        local_btn.click(
            fn=self.enhance_inline,
            inputs=[self.state, prompt_component] + controls + image_components,
            outputs=[prompt_component],
            show_progress="hidden",
        )
        # Den eingebauten "Enhance Prompt"-Knopf ausblenden. visible=False allein
        # genuegt nicht: beim Modellwechsel setzt WanGPs modellabhaengiges
        # UI-Update ihn wieder auf sichtbar. Deshalb zusaetzlich eine eigene
        # elem_id vergeben, die das CSS unten per display:none !important
        # ausblendet - daran kommt kein gr.update(visible=...) vorbei.
        if parent is not None:
            for child in list(getattr(parent, "children", []) or []):
                if isinstance(child, gr.Button):
                    child.elem_id = "local_enhance_builtin_btn"
                    child.visible = False
                    break

        return button_row

    def enhance_inline_remote(self, state, text, *controls):
        """Wie enhance_remote(), schreibt das Ergebnis direkt ins Prompfeld."""
        result, status = self.enhance_remote(state, text, *controls)
        if not result:
            gr.Warning(str(status).replace("**", "").replace("`", ""))
            return gr.update()
        gr.Info(str(status).replace("**", "").replace("`", ""))
        return self._with_history(result)

    def enhance_inline(self, state, text, *values):
        """Wie enhance(), schreibt das Ergebnis aber direkt ins Prompfeld."""
        result, status = self.enhance(state, text, *values)
        if not result:
            gr.Warning(str(status).replace("**", "").replace("`", ""))
            return gr.update()
        # Fuer die Statuszeile dieselbe Trennung wie in enhance(): erst den
        # Modus abziehen, sonst verschieben sich die Eingaben um eins.
        _mode_value, values = self._split_mode_input(values)
        controls, _live_images = self._split_image_inputs(values)
        think, min_words, max_words = self._read_controls(controls)
        marker = " + Think" if think else ""
        gr.Info(
            f"{self._button_label()}: enhanced with {self._variant_label()}"
            f"{marker}{self._word_note(min_words, max_words)}"
            f"{self._image_note(getattr(self, '_last_image_labels', ()))}"
        )
        return self._with_history(result)

    # ------------------------------------------------------------------- UI

    def _build_model_check_section(self):
        """Zeile zum aktuellen Modell, Hinweiszeile, eingeklappter Detailbereich,
        Knopf "Check models" und die scrollbare Liste.

        Eigener Block, weil create_ui() ein Session-Argument entgegennimmt, das
        im Nachbauskript (dev/ui_preview.py) fehlt - so laesst sich genau dieser
        Teil ohne Session aufbauen und pruefen. Der Block wird im Tab-Container
        erzeugt und laesst die Reihenfolge der uebrigen Kinder unberuehrt.

        Die Zeile zum aktuellen Modell steht AUSSERHALB des eingeklappten
        Bereichs, direkt unter der Hinweiszeile: sie ist die eigentlich
        nuetzliche Antwort und wird live berechnet (nicht zwischengespeichert).
        Die Liste darunter kommt beim Aufbau ausschliesslich aus dem
        Zwischenspeicher (_model_check_texts): hier wird nichts berechnet. Erst
        der Klick auf "Check models" liest den Katalog und schreibt ihn.

        Rueckgabe: (Knopf, Markdown des aktuellen Modells, Listen-HTML,
        Status-Markdown) - der Knopf und die Zeile zum aktuellen Modell werden in
        create_ui() bzw. on_tab_select() weiterverdrahtet.
        """
        gr.Markdown(_MODEL_CHECK_HINT)
        current_out = gr.Markdown(value=self._current_model_line(self._state_value()))
        listing, status = self._model_check_texts()
        with gr.Accordion("Which models ignore Min/Max?", open=False):
            # Der Knopf steht allein in seiner Zeile und bekommt normale Breite
            # (min_width) - scale=0 allein quetschte ihn auf zwei Zeilen.
            with gr.Row():
                check_btn = gr.Button(
                    "Check models",
                    size="sm",
                    scale=0,
                    min_width=_MODEL_CHECK_BUTTON_WIDTH,
                )
            # Statuszeile darunter statt daneben.
            status_out = gr.Markdown(value=status)
            # Einleitender Text ueber der Liste, darunter die Liste in der
            # scrollbaren Box (gr.HTML, Inline-Stil am div).
            gr.Markdown(_MODEL_CHECK_INTRO)
            list_out = gr.HTML(value=self._model_check_box(listing))
        # Keine Eingaben: der Klick liest den Katalog selbst. Reihenfolge der
        # Ausgaben wie in _run_model_check(): erst die Liste, dann die Statuszeile.
        check_btn.click(
            fn=self._run_model_check,
            inputs=None,
            outputs=[list_out, status_out],
            show_progress="hidden",
        )
        return check_btn, current_out, list_out, status_out

    def _state_value(self):
        """Wert des state-Snapshots beim Tab-Aufbau - None, wenn er fehlt."""
        try:
            return getattr(self.state, "value", None)
        except Exception:  # noqa: BLE001 - beim Nachbau kann state fehlen
            return None

    def create_ui(self, api_session):
        state = self.state
        refresh_trigger = getattr(self, "refresh_form_trigger", None)

        try:
            current_prompt = str(self.get_current_model_settings(state.value).get("prompt", "") or "")
        except Exception:
            current_prompt = ""

        with gr.Column():
            # Ganz oben im Tab stehen die beiden Wort-Regler. Sie gehoeren zu
            # beiden Knoepfen in Zeile 1 und wandern hierher, nachdem
            # create_inline_button() sie erzeugt und verdrahtet hat.
            # Die Zeile wird leer geoeffnet, die Felder kommen erst NACH dem
            # Block hinein: beim Verlassen gruppiert Gradio aufeinanderfolgende
            # Formularfelder in einen gr.Form (BlockContext.__exit__ ->
            # fill_expected_parents, blocks.py:456-486), der seine Kinder
            # vertikal stapelt - die beiden Felder stuenden sonst untereinander.
            with gr.Row() as word_row:
                pass
            self._attach_word_fields(word_row)
            # Direkt unter den Wort-Reglern: die Zeile zum aktuellen Modell, der
            # Hinweis, der eingeklappte Detailbereich mit dem Knopf und die Liste
            # aus dem Zwischenspeicher.
            _check_btn, current_model_out, _list_out, _status_out = (
                self._build_model_check_section()
            )
            gr.HTML(
                "<b>Enhance: OpenCode / Bonsai 27B</b><br>"
                "Adds two buttons next to <i>Enhance Prompt</i>: "
                "<b>OpenCode</b> enhances remotely through the configured engine, "
                "<b>Local 27B</b> enhances on this GPU with Qwen3.8-27B. "
                "Both write the result straight into the prompt field. "
                "<b>Think</b> and the <b>Min words</b> / <b>Max words</b> fields "
                "at the top of this tab apply to every button. "
                "In the <i>Based on Text Prompt and Images</i> mode the Local 27B "
                "button also reads the selected images with the model's vision part. "
                "Hover the info button for details."
            )
            text_in = gr.Textbox(
                label="Prompt",
                value=current_prompt,
                lines=5,
                placeholder="Type a prompt, or pull one from the Media Generator ...",
            )
            with gr.Row():
                enhance_btn = gr.Button("Local 27B", variant="primary")
                copy_btn = gr.Button(
                    "Pull prompt from Media Generator",
                    visible=True,
                )
            text_out = gr.Textbox(label="Enhanced prompt", lines=5, interactive=True)
            with gr.Row():
                if refresh_trigger is not None:
                    apply_btn = gr.Button("Send to Media Generator")
                else:
                    apply_btn = None
            status = gr.Markdown()

        # Der Tab-Wechsel setzt den Prompt UND die Zeile zum aktuellen Modell:
        # beide haengen am Live-Zustand. Die Reihenfolge muss zur Rueckgabe von
        # on_tab_select() passen; der Host verdrahtet sie als outputs
        # (shared/utils/plugins.py:1797-1804).
        self.on_tab_outputs = [text_in, current_model_out]

        enhance_btn.click(
            fn=self.enhance,
            inputs=[state, text_in] + self._mode_components()
            + self._control_components() + self._image_components(),
            outputs=[text_out, status],
        )

        def pull_from_form(state_value):
            try:
                return str(self.get_current_model_settings(state_value).get("prompt", "") or "")
            except Exception:
                return ""

        copy_btn.click(fn=pull_from_form, inputs=[state], outputs=[text_in], show_progress="hidden")

        if apply_btn is not None:
            apply_btn.click(
                fn=self.write_back,
                inputs=[state, text_out],
                outputs=[refresh_trigger, status],
            )

        return None

    # ------------------------------------------------------------ Tab-Wechsel

    def on_tab_select(self, state):
        """Beim Wechsel auf den Tab den aktuellen Prompt des Panels anzeigen.

        Zweite Ausgabe ist die Zeile zum aktuellen Modell (on_tab_outputs); sie
        wird hier neu berechnet, weil sie am Live-Zustand haengt und nicht
        zwischengespeichert wird. Beide Rueckgaben sind gegen Fehler gesichert -
        der Tab-Wechsel darf nie werfen.
        """
        try:
            prompt = str(self.get_current_model_settings(state).get("prompt", "") or "")
        except Exception:  # noqa: BLE001 - Prompt ist nur die erste Ausgabe
            prompt = ""
        return prompt, self._current_model_line(state)
