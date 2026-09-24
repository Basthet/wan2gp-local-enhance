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

import re
import sys
import time

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
# Presets des Wortzahl-Dropdowns in Zeile 2: (Schluessel, Anzeige, (Min, Max)).
# Presets setzen Min bewusst auf 0 - eine Untergrenze gibt es nur im Custom-Fall,
# wo die beiden kleinen Zahlenfelder erscheinen.
_WORD_PRESETS = (
    ("off", "no limit", (0, 0)),
    ("150", "short - 150 words", (0, 150)),
    ("300", "medium - 300 words", (0, 300)),
    ("500", "long - 500 words", (0, 500)),
)
_WORD_PRESET_CUSTOM = "custom"
_WORD_PRESET_CUSTOM_LABEL = "custom (min/max)"
_WORD_PRESET_BY_KEY = {key: words for key, _label, words in _WORD_PRESETS}
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
    # Die Modus-Zeile: der gr.Form hinter der Knopfreihe, in dem das Dropdown,
    # das Wortzahl-Preset und die beiden Zahlenfelder sitzen.
    "#local_enhance_row + .form{flex-basis:100% !important;}"
    # Das Preset-Dropdown bleibt schmal und nimmt nur seine Textbreite.
    "#local_enhance_row + .form > .local-enhance-preset{"
    "width:190px !important;max-width:190px !important;"
    "flex:0 0 190px !important;min-width:0 !important;}"
    # Min/Max bleiben winzig: Gradio setzt width:100% und min_width (Default
    # 160px) auf jedes Kind, beides muss weg. 84px passt auch fuer vierstellige
    # Werte (maximal erlaubt sind 2000).
    "#local_enhance_row + .form > .local-enhance-words{"
    "width:84px !important;max-width:84px !important;"
    "flex:0 0 84px !important;min-width:0 !important;}"
    # "min:" / "max:" steht als Gradio-Label ueber der Eingabe und darf die
    # Breite nicht mitwachsen lassen.
    "#local_enhance_row + .form > .local-enhance-words label{"
    "font-size:11px !important;line-height:1.2 !important;margin:0 !important;"
    "padding:0 !important;white-space:nowrap !important;}"
    "#local_enhance_row + .form > .local-enhance-words input{"
    "font-size:12px !important;padding:2px 4px !important;text-align:center !important;}"
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

    @classmethod
    def _preset_choices(cls):
        """Dropdown-Optionen: (Anzeige, Schluessel) plus Custom-Eintrag."""
        return [(label, key) for key, label, _words in _WORD_PRESETS] + [
            (_WORD_PRESET_CUSTOM_LABEL, _WORD_PRESET_CUSTOM)
        ]

    @classmethod
    def _preset_key(cls, min_words, max_words):
        """Passender Preset-Schluessel, sonst 'custom'."""
        pair = (int(min_words), int(max_words))
        for key, _label, words in _WORD_PRESETS:
            if words == pair:
                return key
        return _WORD_PRESET_CUSTOM

    @classmethod
    def _preset_range(cls, preset_key, min_value=None, max_value=None):
        """Preset-Schluessel in (Min, Max) uebersetzen; Custom nutzt die Felder."""
        key = str(preset_key or "")
        if key in _WORD_PRESET_BY_KEY:
            return _WORD_PRESET_BY_KEY[key]
        return min_value, max_value

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
        """Think-Checkbox, Wortzahl-Preset und Min/Max aus den Eingaben lesen.

        Die Widgets koennen fehlen (WanGP legt die Think-Checkbox nur fuer lokale
        Enhancer an), deshalb wird nach Typ ausgewertet: bool = Think, str =
        Preset-Schluessel, Zahlen = die beiden Custom-Felder (erst Min, dann Max).
        Ein Preset gewinnt gegen die Felder, denn nur im Custom-Fall sind sie
        sichtbar und gemeint.
        """
        think = False
        preset = None
        numbers = []
        for value in controls:
            if isinstance(value, bool):        # vor int pruefen: bool ist int
                think = value
            elif isinstance(value, str):
                preset = value
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
        min_value, max_value = cls._preset_range(preset, min_value, max_value)
        min_words, max_words = cls._word_range(min_value, max_value)
        return think, min_words, max_words

    def _control_components(self):
        """Die optionalen Regler: Think, Wortzahl-Preset, Min, Max."""
        fields = (
            getattr(self, "_think_checkbox", None),
            getattr(self, "_word_preset_field", None),
            getattr(self, "_min_words_field", None),
            getattr(self, "_max_words_field", None),
        )
        return [field for field in fields if field is not None]

    @staticmethod
    def _on_word_preset_change(preset_key):
        """Custom zeigt die beiden Zahlenfelder, jedes Preset versteckt sie.

        Die Felder behalten dabei ihren Wert: Wer zurueck auf Custom schaltet,
        findet dort seine zuletzt eingegebenen Grenzen wieder.
        """
        custom = str(preset_key or "") == _WORD_PRESET_CUSTOM
        return gr.update(visible=custom), gr.update(visible=custom)

    @classmethod
    def _fallback_instructions(cls, is_image, audio_only, min_words=None, max_words=None):
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
        """
        from shared.prompt_enhancer.prompt_enhance_utils import (
            T2I_VISUAL_PROMPT,
            T2T_TEXT_PROMPT,
            T2V_CINEMATIC_PROMPT,
        )
        if audio_only:
            text = T2T_TEXT_PROMPT
        else:
            text = T2I_VISUAL_PROMPT if is_image else T2V_CINEMATIC_PROMPT
        return cls._apply_word_limit(text, *cls._word_range(min_words, max_words))

    @staticmethod
    def _local_engine_name():
        """Engine-Name, der zu enhancer_enabled gehoert (3 -> qwen35_4b usw.)."""
        config = _main("server_config") or {}
        try:
            number = int(config.get("enhancer_enabled", 0) or 0)
        except (TypeError, ValueError):
            number = 0
        return engine_from_legacy_enhancer(number)

    # -------------------------------------------------------------- Kernlogik

    def enhance(self, state, text, *controls):
        """Lokalen Enhancer auf `text` anwenden. Laeuft im GPU-Kontext."""
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
        # Checkbox "Think" -> 'K' im Modus. Ohne das denkt die 27B nie.
        mode = self._with_thinking(self._resolve_mode(model_def, audio_only, image_mode), think)

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
            ensure_loaded(override_profile=-1)
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
                # Wortgrenze steckt in den Anweisungen; das Token-Budget muss
                # mitwachsen, sonst schneidet das Limit den Prompt ab.
                prompt_enhancer_instructions=self._fallback_instructions(is_image, audio_only, min_words, max_words),
                text_encoder_max_tokens=self._output_token_budget(min_words, max_words),
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
        seconds = time.time() - started
        return result, (
            f"Enhanced locally with **{self._variant_label()}** "
            f"(mode `{mode}`) in {seconds:.1f}s. Not happy? Click again."
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

    def enhance_remote(self, state, text, *controls):
        """Verbessern ueber die Remote-Engine - ohne lokalen Modell-Load.

        Anders als enhance() wird hier kein VRAM belegt: process_prompt_enhancer()
        erkennt an der Engine, dass remote gearbeitet wird (wgp.py:6409), und
        ueberspringt den lokalen Loader (local_runtime, wgp.py:6505).
        """
        think, min_words, max_words = self._read_controls(controls)
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
        mode = self._resolve_mode(model_def, audio_only, image_mode)

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
                "Words: presets no limit / 150 / 300 / 500 words;\n"
                "'custom' reveals the min:/max: fields (0 removes that bound,\n"
                "presets set min to 0)."
            ),
            "local_enhance_local_btn": (
                f"{self._button_label()} - enhance on this GPU\n"
                "Uses Qwen3.8-27B and forces it even if the config selects\n"
                "another local model.\n"
                "An already loaded model is unloaded first, so this can take\n"
                "30-60 s. No remote tokens are used.\n"
                "Think: Qwen reasons before rewriting, with its own thinking\n"
                "budget; unticked it answers straight away.\n"
                "Words: presets no limit / 150 / 300 / 500 words;\n"
                "'custom' reveals the min:/max: fields and the token budget\n"
                "grows with max (0 removes that bound, presets set min to 0)."
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
        Zeile 2: das Modus-Dropdown, daneben das Wortzahl-Preset und - nur bei
        "custom" - die beiden kleinen Felder "min:" / "max:".

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
        min_words, max_words = self._word_range()
        preset_key = self._preset_key(min_words, max_words)
        custom_words = preset_key == _WORD_PRESET_CUSTOM

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
            # Wortgrenze: ein Preset-Dropdown (no limit / short / medium / long)
            # und dahinter die beiden winzigen Zahlenfelder fuer freie Werte.
            # Die Felder sind nur bei "custom" sichtbar; umgeschaltet wird per
            # change() weiter unten. Alle drei wandern gleich in den Container
            # des Modus-Dropdowns (Zeile 2); die Breiten begrenzt das CSS.
            preset_field = gr.Dropdown(
                choices=self._preset_choices(),
                value=preset_key,
                label="words",
                show_label=True,
                scale=0,
                min_width=0,
                elem_id="local_enhance_word_preset",
                elem_classes=["local-enhance-preset"],
            )
            # Gradios eigenes Label ("min:" / "max:") sitzt ueber der Eingabe -
            # ein zusaetzliches HTML-Element waere nur Ballast.
            min_field = gr.Number(
                value=min_words,
                label="min:",
                show_label=True,
                visible=custom_words,
                precision=0,
                minimum=0,
                maximum=_WORD_LIMIT_MAX,
                step=10,
                scale=0,
                min_width=0,
                elem_id="local_enhance_min_words",
                elem_classes=["local-enhance-words"],
            )
            max_field = gr.Number(
                value=max_words,
                label="max:",
                show_label=True,
                visible=custom_words,
                precision=0,
                minimum=0,
                maximum=_WORD_LIMIT_MAX,
                step=10,
                scale=0,
                min_width=0,
                elem_id="local_enhance_max_words",
                elem_classes=["local-enhance-words"],
            )
            words_children = (preset_field, min_field, max_field)

        # Preset umschalten: "custom" zeigt die beiden Felder, jedes Preset
        # versteckt sie wieder.
        preset_field.change(
            fn=self._on_word_preset_change,
            inputs=[preset_field],
            outputs=[min_field, max_field],
            show_progress="hidden",
        )

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

        # Min/Max neben das Modus-Dropdown: so bleibt Zeile 1 genau so, wie sie
        # war. Der Zielcontainer ist der gr.Form, in dem die Think-Checkbox lag -
        # darin steckt das Dropdown. Fehlt er, wird er ueber das Dropdown gesucht.
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
            try:
                for child in words_children:
                    # Die Felder haengen noch direkt in der Knopfreihe; ohne
                    # dieses Entfernen staenden sie in zwei Eltern gleichzeitig.
                    if any(existing is child for existing in button_row.children):
                        button_row.children.remove(child)
                    dropdown_container.children.append(child)
                    child.parent = dropdown_container
            except Exception as exc:  # noqa: BLE001
                print(f"[{PlugIn_Name}] Could not attach the word-limit fields: {exc}")

        # Fuer den Tab-Knopf bereithalten: create_ui() laeuft erst nach dieser
        # Funktion (wgp.py:13628 vor 13976) und kann die Regler mitverdrahten.
        self._think_checkbox = think_checkbox
        self._word_preset_field = preset_field
        self._min_words_field = min_field
        self._max_words_field = max_field

        # Alle Regler gelten fuer BEIDE Knoepfe: die Checkbox schaltet lokal das
        # Denken und remote den Reasoning-Level, Min/Max die Wortgrenze. Fehlt
        # ein Widget, bleibt der jeweilige Default aktiv.
        controls = self._control_components()
        remote_btn.click(
            fn=self.enhance_inline_remote,
            inputs=[self.state, prompt_component] + controls,
            outputs=[prompt_component],
            show_progress="hidden",
        )
        local_btn.click(
            fn=self.enhance_inline,
            inputs=[self.state, prompt_component] + controls,
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

    def enhance_inline(self, state, text, *controls):
        """Wie enhance(), schreibt das Ergebnis aber direkt ins Prompfeld."""
        result, status = self.enhance(state, text, *controls)
        if not result:
            gr.Warning(str(status).replace("**", "").replace("`", ""))
            return gr.update()
        think, min_words, max_words = self._read_controls(controls)
        marker = " + Think" if think else ""
        gr.Info(
            f"{self._button_label()}: enhanced with {self._variant_label()}"
            f"{marker}{self._word_note(min_words, max_words)}"
        )
        return self._with_history(result)

    # ------------------------------------------------------------------- UI

    def create_ui(self, api_session):
        state = self.state
        refresh_trigger = getattr(self, "refresh_form_trigger", None)

        try:
            current_prompt = str(self.get_current_model_settings(state.value).get("prompt", "") or "")
        except Exception:
            current_prompt = ""

        with gr.Column():
            gr.HTML(
                "<b>Enhance: OpenCode / Bonsai 27B</b><br>"
                "Adds two buttons next to <i>Enhance Prompt</i>: "
                "<b>OpenCode</b> enhances remotely through the configured engine, "
                "<b>Local 27B</b> enhances on this GPU with Qwen3.8-27B. "
                "Both write the result straight into the prompt field. "
                "<b>Think</b> and the <b>words</b> preset apply to every button "
                "(<i>custom</i> reveals the min:/max: fields). "
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

        self.on_tab_outputs = [text_in]

        enhance_btn.click(
            fn=self.enhance,
            inputs=[state, text_in] + self._control_components(),
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
        """Beim Wechsel auf den Tab den aktuellen Prompt des Panels anzeigen."""
        try:
            return str(self.get_current_model_settings(state).get("prompt", "") or "")
        except Exception:
            return ""
