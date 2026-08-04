# Judge specification differences

The Playwright suite keeps the behavior documented by `docs/` as its expected
result. Confirmed differences in the current external Judge implementation are
listed here instead of weakening the assertions to match a defect.

## Fatal signals are reported as WA instead of RESIG

`docs/system.md` defines **Runtime Error Killed by signal (RESIG)** for a Judge
run that terminates because of a signal. The legacy integrated test agrees: it
submits `resig.cpp` and expects `STATE_RESIG`.

Against the current `NTOJ-Judge-Rewrite` image (source commit
`333334293b97aa65f506ec1bab8bab320570228b`), this deterministic submission:

```cpp
#include <csignal>
int main() {
  std::raise(SIGSEGV);
}
```

is recorded by the sandbox as `wait4: 0` and `executed normally`. The output
checker then exits with code 1, so the final challenge state becomes WA (3)instead of RESIG (5).

`judge-extended.spec.ts` retains RESIG as the assertion and marks this case as
an expected failure. It therefore remains visible in the HTML report and will
become an unexpected pass when the Judge is fixed; at that point, remove the
`test.fail` annotation.
