# kotoba

A tiny Japanese/English dictionary TUI and CLI.

- Japanese lookup queries Jisho.
- English lookup queries WordNet via `wn`.
- Launch interactively for a scrollable pager, or use `--print` for plain text.

## Install

With Nix flakes:

```
nix run github:sprjr/kotoba -- jp 猫
```

From a local checkout:

```
uv sync --group test
uv run kotoba jp 猫
```

## CLI usage

```
kotoba jp [--selection] [-p|--print] [--json] [--limit N] [QUERY]
kotoba en [--selection] [-p|--print] [--json] [--limit N] [QUERY]
kotoba QUERY            # source inferred from the script
```

One-off lookups:

```
kotoba 猫                # Jisho, opens the pager
kotoba 猫 -p             # plain text to stdout, no TUI
kotoba love -p           # WordNet, inferred from ASCII
kotoba 猫 --json --limit 3
kotoba jp --selection -p # lookup whatever is selected
```

`--selection` uses the Wayland primary selection, then clipboard, then falls back to an empty input. `--print` forces plain text output and also activates automatically when stdout is not a TTY. `--json` emits the same data as structured objects. `--limit` caps entries (default 12 for Jisho, all for WordNet). `kotoba --help` and `kotoba jp --help` document every flag, with examples and exit codes; `kotoba --version` prints the version.

Exit codes: `0` results, `1` no results, `2` upstream/network error, `64` usage error (including an empty query).

## TUI keymap

- `Enter` search
- `Esc` back to query (text preserved) or quit from query screen
- `q` quit from results
- `/` focus query
- `j`/`k`, arrows, `pgup`/`pgdn`, `home`/`end` scroll
- `y` copy current headword (`wl-copy`)
- `o` open Jisho URL (`xdg-open`)
- `a` add selected entry to the current list
- `A` pick a list (or create a new one) and add the selected entry
- `l` open saved lists: `Enter` view, `d` delete entry, `x` delete list, `e` export
- `?` toggle help footer

## Lists and export

Save results to a JSON-backed word list and export to Anki:

```
kotoba list add 猫
cat kotoba list show default
kotoba list export default -f both
```

`kotoba list add` looks up the word and stores the first result. Lists live in
`${XDG_DATA_HOME:-~/.local/share}/kotoba/lists.json` with mode `0600`. Export
writes `${XDG_DATA_HOME:-~/.local/share}/kotoba/exports/kotoba-<list>-<date>.apkg`
(or `.tsv`). The TSV includes Anki import pragmas; the APKG uses the `genanki`
package and can be imported directly into Anki.

## Container

Build and load:

```
nix build .#container
docker load < result
```

Run the CLI path:

```
docker run --rm -it <image> jp --print 猫
```
