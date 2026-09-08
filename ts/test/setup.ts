// Test preload: strip Precept's environment before any test runs.
//
// Every suite points PRECEPT_HOME, PRECEPT_STATE_DIR and PRECEPT_VAULT at temp
// directories in its own setup, but an inherited value still leaks into the gaps:
// a suite that sets only two of the three picks up the third from the shell. That
// is not hypothetical, because the hooks are configured with PRECEPT_VAULT set,
// so exporting it to run the CLI is the normal thing to do. With it set, an
// index rebuild walks the real vault, and the suite went from one second to
// seventy-six and failed eleven tests on timeouts.
//
// Clearing here makes the default state "no vault, no catalog, no state" so a
// suite that forgets to isolate something fails loudly on an empty fixture
// rather than quietly reading the developer's real data.
for (const key of Object.keys(process.env)) {
  if (key.startsWith("PRECEPT_")) delete process.env[key];
}
