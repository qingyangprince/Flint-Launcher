# third_party/sha2

No third-party SHA-2 code is vendored. `native/src/hash.cpp` implements streaming
SHA-1 and SHA-256 directly from FIPS 180-4, which keeps the licence surface small
and is validated against Python's `hashlib` in `tests/test_hash.py`.

If a vetted implementation is preferred later, drop it here and update
`native/CMakeLists.txt` (add the sources) plus this file.
