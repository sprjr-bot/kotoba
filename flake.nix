{
  description = "kotoba — dictionary pager TUI for Jisho and WordNet";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachSystem [ "x86_64-linux" ] (system:
      let
        pkgs = import nixpkgs { inherit system; };
        kotoba = pkgs.callPackage ./package.nix { };
      in
      {
        packages = {
          default = kotoba;
          kotoba = kotoba;
          container = pkgs.callPackage ./container.nix { inherit kotoba; };
        };

        apps.default = {
          type = "app";
          program = "${kotoba}/bin/kotoba";
        };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            (python3.withPackages (ps: with ps; [ textual httpx pytest pytest-asyncio ]))
            wordnet
            wl-clipboard
            uv
          ];
        };

        checks = {
          build = kotoba;
        };
      });
}
