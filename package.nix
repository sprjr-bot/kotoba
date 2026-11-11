{
  lib,
  stdenv,
  python3Packages,
  wordnet,
  wl-clipboard,
}:

python3Packages.buildPythonApplication {
  pname = "kotoba";
  version = "0.1.0";
  pyproject = true;

  src = ./.;

  build-system = [ python3Packages.hatchling ];

  dependencies = with python3Packages; [
    textual
    httpx
    genanki
  ];

  nativeCheckInputs = with python3Packages; [
    pytest
    pytest-asyncio
  ];

  nativeBuildInputs = [ python3Packages.pytestCheckHook ];

  makeWrapperArgs = [
    "--suffix" "PATH" ":" (lib.makeBinPath (lib.optionals stdenv.hostPlatform.isLinux [ wl-clipboard ] ++ [ wordnet ]))
  ];

  meta = {
    description = "Dictionary pager TUI for Jisho and WordNet";
    license = lib.licenses.mit;
    mainProgram = "kotoba";
    platforms = lib.platforms.linux ++ lib.platforms.darwin;
  };
}
