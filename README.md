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
kotoba jp [--selection] [--print] [QUERY]
kotoba en [--selection] [--print] [QUERY]
```

`--selection` uses the Wayland primary selection, then clipboard, then falls back to an empty input. `--print` forces plain text output and also activates automatically when stdout is not a TTY.

Exit codes: `0` results, `1` no results, `2` upstream/network error, `64` usage error.

## TUI keymap

- `Enter` search
- `Esc` back to query (text preserved) or quit from query screen
- `q` quit from results
- `/` focus query
- `j`/`k`, arrows, `pgup`/`pgdn`, `home`/`end` scroll
- `y` copy current headword (`wl-copy`)
- `o` open Jisho URL (`xdg-open`)
- `?` toggle help footer

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
