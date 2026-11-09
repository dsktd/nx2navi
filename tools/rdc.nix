# nixpkgs' renderdoc with its Python module (ENABLE_PYRENDERDOC, left off in nixpkgs: the module has no install rule).
# Built by tools/rdc: the module lands in lib/python/renderdoc.so and bin/rdc-python is the matching interpreter.
pkgs:
pkgs.renderdoc.overrideAttrs (o: {
  pname = "renderdoc-py";
  buildInputs = o.buildInputs ++ [ pkgs.python3 ];
  cmakeFlags = map (f: if pkgs.lib.hasPrefix "-DENABLE_PYRENDERDOC" f then "-DENABLE_PYRENDERDOC:BOOL=TRUE" else f) o.cmakeFlags;
  postInstall = (o.postInstall or "") + ''
    mkdir -p $out/lib/python
    cp lib/renderdoc.so $out/lib/python/   # the build tree's lib/, beside librenderdoc.so
    ln -s ${pkgs.python3}/bin/python3 $out/bin/rdc-python
  '';
})
