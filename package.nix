{
  lib,
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
  ];

  nativeCheckInputs = with python3Packages; [
    pytest
    pytest-asyncio
  ];

  nativeBuildInputs = [ python3Packages.pytestCheckHook ];

  makeWrapperArgs = lib.singleton (
    "--suffix PATH : " + lib.makeBinPath [ wordnet wl-clipboard ]
  );

  meta = {
    description = "Dictionary pager TUI for Jisho and WordNet";
    license = lib.licenses.mit;
    mainProgram = "kotoba";
  };
}
