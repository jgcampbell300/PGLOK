import re
from pathlib import Path


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{1,}")


class LocalSpellChecker:
    def __init__(self):
        self.words = set()
        self._load_dictionary()
        self.words.update(
            {
                "pglok",
                "gorgon",
                "serbule",
                "rahu",
                "povus",
                "vidaria",
                "gazluk",
                "itemizer",
                "chatlogs",
                "json",
                "sqlite",
                "cdn",
                "npc",
                "ui",
            }
        )

    def _load_dictionary(self):
        candidates = [
            Path("/usr/share/dict/words"),
            Path("/usr/dict/words"),
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    w = line.strip().lower()
                    if w:
                        self.words.add(w)
            except OSError:
                continue
        if not self.words:
            # Fallback baseline if system dictionary is unavailable.
            self.words.update(
                {
                    "a",
                    "an",
                    "and",
                    "are",
                    "be",
                    "by",
                    "character",
                    "chat",
                    "data",
                    "file",
                    "for",
                    "from",
                    "in",
                    "is",
                    "item",
                    "map",
                    "name",
                    "notes",
                    "of",
                    "on",
                    "page",
                    "rows",
                    "search",
                    "server",
                    "status",
                    "the",
                    "to",
                    "total",
                    "value",
                    "with",
                }
            )

    def misspelled_words(self, text):
        if not text or self._skip_full_text(text):
            return []

        bad = []
        for word in _WORD_RE.findall(text):
            lowered = word.lower()
            if len(lowered) <= 2:
                continue
            if any(ch.isdigit() for ch in lowered):
                continue
            if lowered not in self.words:
                bad.append(word)
        return bad

    @staticmethod
    def _skip_full_text(text):
        lowered = text.lower()
        return "/" in text or "\\" in text or lowered.startswith("http://") or lowered.startswith("https://")


class EntrySpellcheckBinder:
    def __init__(self, default_style="App.TEntry", error_style="App.SpellError.TEntry", delay_ms=250):
        self.checker = LocalSpellChecker()
        self.default_style = default_style
        self.error_style = error_style
        self.delay_ms = int(delay_ms)
        self._after_ids = {}

    def register(self, entry_widget):
        entry_widget.bind("<KeyRelease>", lambda _e, w=entry_widget: self._schedule(w), add="+")
        entry_widget.bind("<FocusOut>", lambda _e, w=entry_widget: self._check_now(w), add="+")
        entry_widget.bind("<Return>", lambda _e, w=entry_widget: self._check_now(w), add="+")
        self._schedule(entry_widget)

    def _schedule(self, widget):
        try:
            if widget in self._after_ids:
                widget.after_cancel(self._after_ids[widget])
            self._after_ids[widget] = widget.after(self.delay_ms, lambda w=widget: self._check_now(w))
        except Exception:
            return

    def _check_now(self, widget):
        try:
            if widget in self._after_ids:
                widget.after_cancel(self._after_ids[widget])
                self._after_ids.pop(widget, None)
            state = str(widget.cget("state"))
            if state in {"disabled", "readonly"}:
                return
            text = widget.get().strip()
            misspelled = self.checker.misspelled_words(text)
            widget.configure(style=self.error_style if misspelled else self.default_style)
        except Exception:
            return
