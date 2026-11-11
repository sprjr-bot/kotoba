# kotoba — dictionary TUI + CLI Implementation Plan

**Goal:** Replace the two `notify-send` shell helpers in `waybar.nix` (`jp-lookup`, `dict-lookup`) with one standalone Python/Textual application that queries Jisho (JP) or WordNet (EN), renders results in a scrollable pager inside a floating terminal, and still works as a plain CLI.

**Architecture:** One package, two backends behind a common `LookupResult` model. Textual app has two screens: a query input and a results pager. A `--print` path renders the same model as plain text so the tool is usable in a pipe, over SSH, or in a container. Distribution is a flake in its own repo (`packages`, `apps`, `container`, `checks`); nixos-configs consumes it as a flake input and owns the keybinds.

**Stack:** Python 3.13, Textual, httpx (Jisho), `wordnet` CLI (`wn`), pytest; Nix `buildPythonApplication`, `dockerTools.buildLayeredImage`; GitHub Actions for checks and GHCR publish.

**Decisions already made (user, 2026-11-10):**
- Both lookups in one app; Japanese is the Super+Shift+D path, English is Super+D.
- Results shown as a pager in an inline terminal window, not notifications.
- Floating window for the keybind; the binary works standalone from any shell.
- Query source: primary selection → clipboard → empty focused input, no fuzzel.
- Python + Textual.

**Decisions confirmed (2026-11-10, second round):**
- Public repo `sprjr/kotoba`, created by `sprjr-bot`, MIT licence, package-only flake.
- Container is a buildable artifact only — no GHCR workflow, no registry publish.
- Progress must be checkpointed to `TASKLIST.md` in the repo root so compression or a fresh agent can resume without re-deriving state.

---

## Task 0: Repo bootstrap

**Files:** `README.md`, `LICENSE`, `pyproject.toml`, `.gitignore`, `src/kotoba/__init__.py`, `.github/workflows/ci.yml`

1. `pyproject.toml` — hatchling, `requires-python = ">=3.11"`, `dependencies = ["textual>=0.80", "httpx>=0.27"]`, `[project.scripts] kotoba = "kotoba.cli:main"`, pytest in `[dependency-groups]`.
2. Public API in `src/kotoba/__init__.py`: `__version__`.
2. CI: `pytest` on 3.13 plus `nix build .#default` on `ubuntu-latest`.
3. `TASKLIST.md` — one row per task from this plan with `todo / doing / done`, the commit sha when done, and a `## Resume notes` section: last command run, next action, open blocker. Update it after every task, before every commit. It is the source of truth across context loss, not the conversation.

**Verify:** `uv run pytest` collects 0 tests, exit 5 is acceptable at this stage; `uv build` produces a wheel.

---

## Task 1: Data model

**Files:** `src/kotoba/model.py`, `tests/test_model.py`

```python
@dataclass(frozen=True)
class Sense:
    pos: tuple[str, ...]
    glosses: tuple[str, ...]

@dataclass(frozen=True)
class Entry:
    headword: str
    reading: str | None
    senses: tuple[Sense, ...]
    tags: tuple[str, ...] = ()

@dataclass(frozen=True)
class LookupResult:
    query: str
    source: Literal["jisho", "wordnet"]
    entries: tuple[Entry, ...]
    url: str | None = None
```

**Verify:** round-trip construction test, empty-entries repr test.

---

## Task 2: Jisho client

**Files:** `src/kotoba/jisho.py`, `tests/test_jisho.py` (canned JSON fixture, no network)

1. `fetch(query: str, *, timeout: float = 8.0) -> LookupResult` via `httpx.get("https://jisho.org/api/v1/search/words", params={"keyword": query})`.
2. Map `data[]` → `Entry`: `japanese[0].word`, `japanese[0].reading`, `senses[].english_definitions`, `senses[].parts_of_speech`, `is_common`/`jlpt`/`tags` into `tags`.
3. Cap at 12 entries. Raise `LookupError` (own type) on transport error, non-200, or unparseable body — the UI renders the message inline.
4. `url` → `https://jisho.org/search/<quoted query>`.

**Verify (TDD):** failing test first with the fixture; then `pytest tests/test_jisyo.py -v` → 4 passed. A separate `@pytest.mark.network` test hits the live API and is skipped by default.

---

## Task 3: WordNet client

**Files:** `src/kotoba/wordnet.py`, `tests/test_wordnet.py`

1. `fetch(query) -> LookupResult` shells out to `wn <query> -over` (the same call the current `dict-lookup` makes), captures stdout+stderr.
2. Parse the WordNet 3.0 license banner off the top, then group output by part of speech into `Sense`s.
3. No `wn` on PATH → `LookupError("wordnet not installed")`.
4. Preserve parity with today's output: same senses, same order, no invented definitions.

**Verify:** parser unit tests against two captured fixtures (a noun with several senses, a miss). Capture the fixtures on a host that has `nix run nixpkgs#wordnet -- love -over` available; if unavailable, mark `xfail` and note it — do not fabricate output.

---

## Task 4: Query resolution

**Files:** `src/kotoba/selection.py`, `tests/test_selection.py`

1. `initial_query(arg: str | None) -> str`: explicit arg wins; else `--selection` triggers `wl-paste --primary`, then `wl-paste`; every failure path returns `""`.
2. Strip, collapse internal whitespace, trim to first line, cap 64 chars (Jisho chokes on pasted paragraphs).
3. No `wl-paste` binary (SSH, container, non-Wayland) → `""`, no error.

**Verify:** tests with a fake `subprocess.run`.

---

## Task 5: Plain renderer

**Files:** `src/kotoba/render.py`, `tests/test_render.py`

1. `render_text(result) -> str`: `headword【reading】` then `  • POS: gloss, gloss` per sense, entries separated by a blank line; no ANSI, no box drawing.
2. `render_error(query, msg) -> str`.
3. This is what `--print` emits and what the pager renders inside Textual (`Static` with `markup=False` or a `Rich` group — one renderer, two consumers).

**Verify:** golden-file tests; output ends with exactly one newline.

---

## Task 6: Textual app — query screen

**Files:** `src/kotoba/app.py`, `tests/test_app.py` (Textual `run_test` pilot)

1. `KotobaApp(source, query, print_only)`; `on_mount` goes straight to results when the initial query is non-empty, otherwise focuses the `Input`.
2. `Input` placeholder `日本語` / `define`, `Enter` → results, `ctrl+c` quits, `Esc` quits from the query screen.
3. Async lookup via `@work(thread=True)` so the UI never blocks; a `LoadingIndicator` on the status line.

**Verify:** `pytest --asyncio-mode=auto tests/test_app.py` with the pilot typing a query and asserting the results screen mounted.

---

## Task 7: Results pager

**Files:** `src/kotoba/app.py`, `src/kotoba/app.tcss`

1. `VerticalScroll` holding one `Static` per entry; `q` quit, `Esc` back to query with the text preserved, `/` focus query, `j/k/up/down/pgup/pgdn/home/end` scroll, `y` copy the current headword via `wl-copy` (silently ignored when absent), `o` open the Jisho URL via `xdg-open`, `?` toggle help footer.
2. Footer always shows `q quit · esc edit · y copy · o open`; status line shows `jisho · 12 results · 340 ms` or the error text.
3. Window title set to `kotoba — <query>` so the compositor rule and terminal tab both read well.

**Verify:** pilot test asserting `Esc` returns to the query screen with the same text; manual run in ghostty.

---

## Task 8: CLI entry point

**Files:** `src/kotoba/cli.py`, `tests/test_cli.py`

```
kotoba jp [--selection] [--print] [QUERY]
kotoba en [--selection] [--print] [QUERY]
```

1. `--print` or `not sys.stdout.isatty()` → plain renderer, no Textual import at module scope (lazy import keeps `--print` startup near-instant).
2. Exit codes: `0` results, `1` no results, `2` upstream error, `64` usage.
3. Errors to stderr for `--print`, inline in the pager otherwise.

**Verify:** `kotoba jp --print 猫 | head` in a pipe returns text and `0`; `kotoba xx` returns `64`.

---

## Task 9: Nix packaging

**Files:** `flake.nix`, `package.nix`, `tests/default.nix`

1. `package.nix` — `python3Packages.buildPythonApplication`, `pyproject = true`, `build-system = [ hatchling ]`, `dependencies = [ textual httpx ]` from pinned nixpkgs, `nativeCheckInputs = [ pytest pytest-asyncio ]`, `pytestCheckHook`.
2. `flake.nix` — `nixpkgs` + `flake-utils`; outputs `packages.<sys>.{default,kotoba}`, `apps.default`, `devShells.default` (python + pytest + ruff), `checks.<sys>.{build,tests}`.
3. `wordnet` is a runtime dependency of the EN path only: `runtimeDependencies` via `makeWrapper` adding `pkgs.wordnet` and `pkgs.wl-clipboard` to PATH.

**Verify:** `nix build .#default` and `nix run .# -- jp --print 猫` on a Linux host with Nix. Container has no Nix store — this task is host-verified only.

---

## Task 10: Container

**Files:** `container.nix`, `.github/workflows/release.yml`

1. `dockerTools.buildLayeredImage`, `entrypoint = ["/bin/kotoba"]`, includes wordnet + wl-clipboard; `contents` limited to the app closure.
2. `nix build .#container` is the whole deliverable — no registry, no publish workflow. README documents `docker load < result` then `docker run --rm -it <image> jp --print 猫`.
3. TUI usage inside the container is `docker run --rm -it` with `TERM` set; selection capture is inert there (no Wayland socket) and the CLI arg path is what gets tested.

**Verify:** `nix build .#container` → `docker load < result`; `docker run --rm image jp --print 猫` prints entries.

---

## Task 11: nixos-configs wiring (second PR, separate repo)

**Files:** `flake.nix`, `nixos/modules/user/patrick.nix:54`, `home/modules/general/workstation-packages.nix`, `home/modules/user-space/hyprland/waybar.nix`, `home/modules/user-space/hyprland/keybinds.nix:103`, `home/modules/user-space/hyprland/default.nix:520`

1. Input `kotoba.url = "github:sprjr/kotoba"`, `inputs.nixpkgs.follows = "nixpkgs"`.
2. `inherit … kotoba;` in `patrick.nix`; add `kotoba.packages.${system}.default` to `workstationPackages`.
3. Delete `jpLookup` and `dictLookup` from `waybar.nix`; keep both modules, `on-click = "$terminal -e kotoba jp --selection"` / `… en --selection`.
4. Keybinds: `"$mainMod, D, exec, $terminal -e kotoba en --selection"`, `"$mainMod SHIFT, D, exec, $terminal -e kotoba jp --selection"`.
5. Windowrule:
   ```nix
   "windowrule[kotoba]" = {
     "match:class" = "^(kotoba)$";
     float = true;
     size = "55% 60%";
     center = true;
   };
   ```
6. `ghostty --class=kotoba` on the exec lines so the class matches; keep `-e` last.

**Verify:** `nixos-rebuild dry-build --flake .#seanix` evaluates; then Super+Shift+D with text selected opens a floating ghostty showing Jisho entries, `q` closes, selection empty → empty input.

---

## Risks / open questions

- **Jisho API is undocumented and unversioned.** No SLA, no key. Mitigation: 8 s timeout, inline error, retry key `r`. Accept as-is (user, 2026-11-10).
- **`wn` output parsing is brittle** across WordNet builds. Mitigation: fixture tests pinned to nixpkgs' wordnet; parser isolated in one module.
- **Textual startup latency** on a cold cache is ~250–400 ms; acceptable for a keybind but worth measuring in Task 7.
- **`wl-copy` under a floating terminal** copies to the regular clipboard, not primary — that is the intended behavior for `y`.
- **Wordnet verification** requires a Nix host; the build container has no store. Tasks 3 and 9 must be validated on seanix.
