{
  # A dev shell with every tool NX2navi's Linux build wants (docs/building.md, "Linux"), from nixpkgs instead of
  # pacman, and nixGL so the game finds a Vulkan driver built against the same glibc as the shell's libraries.
  # Nothing of the game is built by Nix: the build reads your dump and writes 60 GB, so it runs in the NX2navi
  # checkout as upstream documents, from inside `nix develop`.
  description = "NX2navi build environment (toolchain from nixpkgs, Vulkan through nixGL)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    nixgl = {
      url = "github:nix-community/nixGL";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, nixgl }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      llvm = pkgs.llvmPackages_23;
      gl = nixgl.packages.${system};
      # The Vulkan wrapper for the host's GPU. Mesa (AMD RADV, Intel) is pure; NVIDIA reads the host driver's version
      # and needs `nix develop --impure`.
      vulkan = if builtins.getEnv "NX2NAVI_NVIDIA" == "1" then gl.nixVulkanNvidia else gl.nixVulkanIntel;
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        name = "nx2navi";
        # The nixpkgs compiler wrapper adds fortify, stack protector and PIE flags; the build sets its own.
        hardeningDisable = [ "all" ];
        # the libraries go in buildInputs: the compiler wrapper then adds their -L and an rpath to every link
        buildInputs = with pkgs; [
          vulkan-headers
          vulkan-loader
          vulkan-validation-layers
          vulkan-memory-allocator
          sdl3
          libopus
          libvpx
          dav1d
          zstd
        ];
        packages = with pkgs; [
          llvm.clang
          llvm.lld
          llvm.bintools
          ninja
          gnumake
          pkg-config
          git
          # shader tools and the translator's runtime
          shaderc
          spirv-tools
          dotnet-sdk_10
          # the two Python environments (tools/requirements*.txt): 3.12 for the lifter, 3.14 for extraction
          uv
          python312
          python314
          vulkan
        ];
        env = {
          # uv uses the two interpreters above, never a downloaded python-build-standalone
          UV_PYTHON_DOWNLOADS = "never";
          # the game's $ORIGIN rpath expects libSDL3.so.0 beside it; here the libraries are found through this path, and
          # the manylinux wheels (numpy, unicorn, lief...) find libstdc++ and libz the same way
          LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath (with pkgs; [ vulkan-loader sdl3 libopus libvpx dav1d zstd stdenv.cc.cc.lib zlib ]);
          # build-linux.py: the directory holding vk_mem_alloc.h
          NX2NAVI_VMA_INCLUDE = "${pkgs.vulkan-memory-allocator}/include";
          VK_LAYER_PATH = "${pkgs.vulkan-validation-layers}/share/vulkan/explicit_layer.d";
          # .NET without the first-run chatter and telemetry
          DOTNET_CLI_TELEMETRY_OPTOUT = "1";
          DOTNET_NOLOGO = "1";
        };
        shellHook = ''
          # build_game.py links libstdc++ statically (-l:libstdc++.a); the static archive lives in gcc's own output
          export NIX_LDFLAGS="-L${pkgs.gcc.cc}/lib $NIX_LDFLAGS"
          echo "nx2navi shell: clang $(clang --version | head -1 | cut -d' ' -f3), dotnet $(dotnet --version), run the game as: ${vulkan.name} build/<ver>/nx2navi"
        '';
      };
    };
}
