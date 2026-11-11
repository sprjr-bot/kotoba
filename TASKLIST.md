# TASKLIST

| Task | Status | Note |
|------|--------|------|
| T0: Repo bootstrap | done | pyproject, uv.lock, CI workflow, wheel builds |
| T1: Data model | done | model.py, 2 tests |
| T2: Jisho client | done | jisho.py, live response verified against jisho.org |
| T3: WordNet client | done | wordnet.py, parser fixture pending a host with `wn` |
| T4: Query resolution | done | selection.py, primary → clipboard → empty |
| T5: Plain renderer | done | render.py, golden tests |
| T6: Textual query screen | done | app.py, pilot tests |
| T7: Results pager | done | app.py + app.tcss, keymap q/esc/y/o/?</* |
| T8: CLI entry point | done | cli.py, `--print` never imports Textual |
| T9: Nix packaging | done | package.nix, flake.nix — not built (no Nix in build container) |
| T10: Container | done | container.nix — not built (no Nix in build container) |

## History note

The per-task commit chain (963ca7e … aca4da9) is gone: eight objects under
`.git/objects` were found zero-byte, so `HEAD` was unreadable. The working tree
survived intact and history was rebuilt as a single commit on `feat/kotoba`.

## Post-audit fixes

- `package.nix`: `src = ../.` resolved to the repo's parent; now `./.`
- `cli.py`: `--selection` passed `args.query` (default `""`) to `initial_query`, so
  the selection was never read — the flag silently did nothing
- `app.py`: escape-to-edit called a `_focus_input` on the wrong screen (raised
  `NoMatches`); `QueryScreen.focus_input` is now public and used with
  `call_after_refresh`
- removed `tests/default.nix`: referenced undefined `pkgs.kotoba`, wired into no check
- `pyproject.toml`: registered the `network` marker

## CLI ergonomics (post-review)

- Bare query: `kotoba 猫` / `kotoba love` infers the source from the script.
- `-p/--print`, `--json`, `--limit N` for one-off lookups.
- Pager wraps long senses with a hanging indent instead of wrapping to column 0.
- `--help` documents flag semantics, examples, and exit codes; `--version`; usage errors exit 64.

## Verification

`./.venv/bin/pytest -q` → 40 passed, 1 skipped (live network test), 1 xfailed
(WordNet fixture). Live checks: `kotoba 猫 -p` (exit 0), `kotoba 猫 --json --limit 2`,
`kotoba love -p` (exit 2, `wn` absent here), `kotoba jp --print` (exit 64).

The TUI was driven headlessly with Textual's `run_test()` pilot: initial query screen,
submit → results, `esc` → query with text preserved, second submit, `q` exits. Screenshots
rendered from `App.export_screenshot()` SVG.

## Closure size

Runtime closure contributors and whether the code actually needs them:
- `python3` + stdlib: required (interpreter).
- `httpx` tree (`httpcore`, `h11`, `anyio`, `sniffio`, `certifi`, `idna`): required
  by `jisho.py`; all are pulled in by declared `httpx` dependency.
- `textual` tree (`rich`, `pygments`, `markdown-it-py`, `typing-extensions`,
  `platformdirs`, etc.): required only when TUI path is taken. `--print`/`--json`
  never imports it. Declared dependency, so always in closure.
- `wordnet` (binary + WordNet 3.0 DB files): required only for the English path
  (`wordnet.py` shells out to `wn`). ~30–40 MB estimated, mostly the database.
- `wl-clipboard` (`wl-copy`/`wl-paste`): required only for clipboard read/write,
  gated by `shutil.which` at runtime. Linux Wayland only; dead weight on X11 or
  headless servers.
- `xdg-open`: not bundled; `app.py` calls it if available, otherwise silently fails.

No measured Nix closure size is available (no Nix in this container). Measure on a
host with Nix:

```bash
nix path-info -rSsh $(nix build --no-link --print-out-paths .#default) | sort -k2 -h | tail -20
```

Likely top entries: `wordnet` data files, `python3`, `textual` + `rich`/`pygments`,
`httpx` + `httpcore` + `certifi` CA bundle.

Options to make it lighter:
1. **Drop `wordnet` from default dependency; make `kotoba-en` a separate output/package.**
   Trade-off: users who only look up Japanese lose ~30–40 MB. Effort: low.
2. **Replace Textual with a minimal curses/urwid renderer.** Trade-off: removes
   `textual`/`rich`/`pygments` (~10–20 MB estimated) but costs UX and keybinding work.
   Effort: medium.
3. **Lazily fetch WordNet data instead of bundling it.** Trade-off: first `en` query
   downloads data; offline path lost. Effort: high (needs own `wn` data store).

Recommended: option 1 (split package) for the biggest verified saving with the least
work.

## Unverified (needs a host with Nix)

- `nix build` of the package and `nix build .#container`
- WordNet parsing against real `wn <word> -over` output
- floating window rule + keybind in the wiring PR
