# flint_native

Optional C++17 helper library used by `flint.infra` for hashing, big-file copies
and ZIP extraction. Python always has a pure-Python fallback, so a missing or
incompatible library never breaks the launcher.

## Build

```bash
cmake -S flint/native -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release
cmake --build build/native --target stage   # copies the library into flint/lib/
```

`stage` is what `build/cmake_build.py` and CI call; it drops the artifact into
`flint/lib/`, the first package-local search path used by
`flint.infra.native_loader`.

## Artifact names

| Platform | File                   |
|----------|------------------------|
| Windows  | `flint_native.dll`     |
| macOS    | `libflint_native.dylib`|
| Linux    | `libflint_native.so`   |

## ABI

`include/flint_native.h` is the single source of truth. `FLINT_NATIVE_ABI_VERSION`
is mirrored in `flint/infra/native_loader.py`; a mismatch makes the loader reject
the library and fall back to Python (logged at debug level).

Bump the version when you:

* change an existing function signature, semantics or error code, or
* remove an exported symbol.

Adding a new function is backwards compatible and does **not** require a bump,
but the Python loader must tolerate the symbol being absent.

## Cancellation

Functions that can run for a long time take a `flint_cancel_fn` callback plus an
opaque `void *user_data`. The callback is polled from the working thread and must
return non-zero to abort; aborted calls return `FLINT_ERR_CANCELLED`.

## Third-party code

* `third_party/miniz` - public domain ZIP/deflate implementation (see LICENSE).
* `third_party/sha2` - intentionally empty: SHA-1/SHA-256 live in `src/hash.cpp`
  and are verified against `hashlib` in `tests/test_hash.py`.
