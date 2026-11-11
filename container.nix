{ pkgs ? import <nixpkgs> { }, kotoba }:

pkgs.dockerTools.buildLayeredImage {
  name = "kotoba";
  tag = "latest";
  contents = [ kotoba pkgs.wordnet pkgs.wl-clipboard ];
  config = {
    Entrypoint = [ "${kotoba}/bin/kotoba" ];
    Env = [ "TERM=xterm-256color" "PATH=/bin" ];
  };
}
