# Part D — C++ behavior proof without pixels (engine/gem changes)

When the change is reflection/logic (not visual), prove it with a unit test using
a `ScriptContext`, not a screenshot. A bundled template is at
`scripts/scriptcontext_test_template.cpp`.

## Pattern

1. Build a fresh `AZ::BehaviorContext`, reflect the types under test PLUS their
   dependencies. Dependencies are the usual trap:
   - `AZ::MathReflect(behaviorContext)` for `Vector2`/`Vector3`/`Color`.
   - For an EBus addressed by id, reflect the bus-id type too (the `Event(id)`
     binding treats the bus address as an argument; if the id type is not
     reflected the bus will not bind and you get
     "argument type ... is not serialized and/or reflected for scripting").
2. Bind an `AZ::ScriptContext` to the behavior context.
3. Connect a stub handler that returns known values.
4. `Execute()` a Lua snippet that calls the reflected API, and bridge results back
   to C++ via reflected `Property(name, BehaviorValueProperty(&staticVar))` so the
   test can assert on them.
5. Add the test file to the module's `*_tests_files.cmake` (O3DE uses explicit file
   lists; Ninja re-runs cmake when the `.cmake` changes).

Build + run on a from-source engine/fork:

```
cmake --build <build_dir> --config <config> --target <Module>.Tests
<build_dir>/bin/<config>/AzTestRunner "$(readlink -f <build_dir>/bin/<config>/lib<Module>.Tests.so)" \
    AzRunUnitTests --gtest_filter='*YourTest*'
```

## The mandatory revert-cycle

A test that passes both with and without your change proves nothing. Always:

1. Run with the fix present → expect PASS.
2. Restore the pre-change source (`git show <base>:<file> > <file>`), rebuild, run →
   expect FAIL.
3. Restore the fix (`git checkout HEAD -- <file>`), rebuild, run → expect PASS
   again.
4. Only then commit the test, and say "revert-cycle verified" honestly.

## Two flavors of proof

- **Registration test** (Tier 1): assert the reflected EBus/method/enum exists in
  the `BehaviorContext` (`m_ebuses`, `ebus->m_events`, `m_properties`). Fast,
  catches typos and missing reflection.
- **Behavior test** (Tier 2): the ScriptContext + Lua + stub-handler flow above.
  Proves it actually works from script, end to end. This is the one that justifies
  the change to a reviewer.

See `scripts/scriptcontext_test_template.cpp` for a complete working example
(a reflected EBus called from Lua, with the dependency reflection and the
static-property bridge).
