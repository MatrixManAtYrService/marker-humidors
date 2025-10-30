{
  description = "marker-humidor: feedback pages for dry-erase marker humidors, on Unison Cloud";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs = {
        pyproject-nix.follows = "pyproject-nix";
        uv2nix.follows = "uv2nix";
        nixpkgs.follows = "nixpkgs";
      };
    };
  };

  outputs = { self, nixpkgs, flake-utils, uv2nix, pyproject-nix, pyproject-build-systems }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        inherit (pkgs) lib;

        python = pkgs.python312;
        workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

        pythonSet = (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope (
          lib.composeManyExtensions [
            pyproject-build-systems.overlays.default
            (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
          ]
        );

        editablePythonSet = pythonSet.overrideScope (
          lib.composeManyExtensions [
            (workspace.mkEditablePyprojectOverlay { root = "$REPO_ROOT"; })
            (final: prev: {
              marker-humidor = prev.marker-humidor.overrideAttrs (old: {
                nativeBuildInputs = old.nativeBuildInputs ++ final.resolveBuildSystem { editables = [ ]; };
              });
            })
          ]
        );

        venv = pythonSet.mkVirtualEnv "marker-humidor" workspace.deps.default;
        devVenv = editablePythonSet.mkVirtualEnv "marker-humidor-dev" workspace.deps.all;

        # humidor with ucm on its PATH, so `nix run . -- serve` works outside the devshell.
        humidor = pkgs.writeShellApplication {
          name = "humidor";
          runtimeInputs = [ venv pkgs.unison-ucm pkgs.git ];
          text = ''exec ${venv}/bin/humidor "$@"'';
        };
      in
      {
        packages = {
          default = humidor;
          inherit humidor;
          codegen = pkgs.callPackage ./nix/codegen.nix { };
          nix-analysis = pkgs.callPackage ./nix/nix-analysis.nix { };
        };

        checks = {
          ruff = pkgs.runCommand "ruff" { nativeBuildInputs = [ pkgs.ruff ]; } ''
            export RUFF_CACHE_DIR=$(mktemp -d)
            cd ${self}
            ruff check humidor tests
            ruff format --check humidor tests
            touch $out
          '';
          pytest = pkgs.runCommand "pytest" { nativeBuildInputs = [ devVenv pkgs.git ]; } ''
            cp -r ${self} src && chmod -R u+w src && cd src
            HUMIDOR_SKIP_UCM_TESTS=1 pytest -q -p no:cacheprovider
            touch $out
          '';
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            devVenv
            pkgs.uv
            pkgs.ruff
            pkgs.unison-ucm
            pkgs.nixpkgs-fmt
            pkgs.nix-output-monitor
          ];
          env = {
            UV_NO_SYNC = "1";
            UV_PYTHON = python.interpreter;
            UV_PYTHON_DOWNLOADS = "never";
          };
          shellHook = ''
            export REPO_ROOT=$(pwd)
          '';
        };
      });
}
