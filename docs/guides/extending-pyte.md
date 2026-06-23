# Extending pyte (the pattern)

Worked example — how `rpc_listen()` was added:

1. **C wrapper** in `shim/pyte_shim.c`, declaration in
   `shim/pyte_shim.h`.  Guarded, te_errno + out-param, awaiting-error
   re-armed:

   ```c
   te_errno
   pyte_rpc_listen(rcf_rpc_server *rpcs, int s, int backlog, int *out)
   {
       RPC_AWAIT_ERROR(rpcs);
       PYTE_GUARD(*out = rpc_listen(rpcs, s, backlog));
       return 0;
   }
   ```

   `PYTE_GUARD`'s statement must not return early (see the macro
   comment in `pyte_shim.h`); use `PYTE_GUARD_RC` for calls that
   already return `te_errno`.

2. **cdef line** in `shim/pyte_shim_cdef.h` (kept in sync with the
   header, minus `extern`):

   ```c
   te_errno pyte_rpc_listen(rcf_rpc_server *rpcs, int s, int backlog,
                            int *out);
   ```

3. **Facade method** (here in `src/pyte/rpc/socket.py`) routing the
   trampoline status and the call result through `_check_call`:

   ```python
   def listen(self, backlog: int = 5) -> None:
       from pyte._shim import ffi, lib
       out = ffi.new("int *")
       rc = lib.pyte_rpc_listen(self.server._h, self.fd, backlog, out)
       self.server._check_call(rc, out[0], lambda v: v == 0,
                               f"listen({backlog})")
   ```

   Non-RPC wrappers just call `pyte.errors.check(rc, where)`.

4. **Rebuild** the extension:

   ```sh
   TE_INSTALL=/path/to/te/inst uv sync --reinstall-package pyte
   ```

5. **Test**: a unit test if the logic is pure Python, plus a showcase
   test in a consuming suite (e.g. python-ts) for end-to-end behaviour.
