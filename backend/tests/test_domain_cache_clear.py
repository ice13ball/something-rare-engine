# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The admin cache sweep must reach every domain module's caches.

main.py used to clear a hand-written list of globals. As domains are extracted
their caches leave main.py, and a forgotten entry is invisible: the endpoint
still returns 200, it just serves stale data. This locks the contract.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import domains


def test_registry_exists_and_is_a_tuple_of_modules():
    assert hasattr(domains, "CACHE_CLEARING_DOMAINS")
    assert isinstance(domains.CACHE_CLEARING_DOMAINS, tuple)
    assert domains.CACHE_CLEARING_DOMAINS, "registry must not be empty"


def test_every_registered_domain_exposes_clear_caches():
    for mod in domains.CACHE_CLEARING_DOMAINS:
        fn = getattr(mod, "clear_caches", None)
        assert callable(fn), f"{mod.__name__} is registered but has no clear_caches()"


def test_clear_caches_is_idempotent_and_empties_module_caches():
    """Calling it twice must not raise, and must leave every cache global falsy.

    A registered entry can be a package (e.g. `domains.fields`), whose own
    `clear_caches()` aggregates its sub-modules' — so after calling it, the
    cache globals living inside `domains.fields.carbon`/`.habitat`/etc. must
    also come back falsy, not just anything on the package object itself
    (the package's own `dir()` never holds cache globals directly — they
    live one level down). `pkgutil.walk_packages` recurses; `iter_modules`
    does not.
    """
    import importlib
    import pkgutil
    import re

    # Skip dunders: Python sets __cached__ on every module and it matches the
    # cache-name pattern (_ + _ + cache + d__). Narrowing the regex instead would
    # stop matching a bare `_cache`, which is a real cache name. Still correctly
    # excluded below: `__cached__` starts with "__" so the startswith("__") guard
    # skips it regardless of the character class (verified — it has no digits, so
    # widening [a-z_] to [a-z0-9_] changes nothing about whether it matches; the
    # dunder check is what excludes it either way).
    #
    # Digits are included in the character class ([a-z0-9_], not [a-z_]) because
    # ordinary domain names carry them — `_co2_meta_cache` (fields/carbon.py) was
    # invisible to the old letters-only pattern and slipped straight through this
    # test undetected until a whole-branch review caught it by direct count. `co2`,
    # `o2`, `no3`, `h2o` etc. are routine in this codebase; the next digit-bearing
    # cache name is a matter of when, not if.
    def _assert_no_populated_cache(mod):
        for name in dir(mod):
            if name.startswith("__"):
                continue                      # __cached__ matches the pattern below
            if re.fullmatch(r"_[a-z0-9_]*cache[a-z0-9_]*", name):
                val = getattr(mod, name)
                if callable(val):
                    continue          # a helper *function* named *cache*, not cache data —
                                       # e.g. `_clear_blog_cache`; a function is always truthy,
                                       # so without this guard the mere existence of such a
                                       # helper fails this test unconditionally
                assert not val, f"{mod.__name__}.{name} still populated after clear_caches()"

    for mod in domains.CACHE_CLEARING_DOMAINS:
        mod.clear_caches()
        mod.clear_caches()  # idempotent
        _assert_no_populated_cache(mod)
        if hasattr(mod, "__path__"):  # a package — its clear_caches() must reach every sub-module
            for info in pkgutil.walk_packages(mod.__path__, prefix=mod.__name__ + "."):
                _assert_no_populated_cache(importlib.import_module(info.name))


def test_every_domain_module_with_a_cache_is_registered():
    """A domain that declares a cache global but is not covered by the registry
    is exactly the silent-staleness bug this hook exists to prevent.

    Recurses with `pkgutil.walk_packages` (NOT `iter_modules`, which only lists
    direct children of `domains/` and would treat a package like
    `domains.fields` as a single opaque entry, never looking inside it — so a
    future `domains/fields/newthing.py` declaring a cache and never wired into
    `fields/__init__.py`'s `clear_caches()` would be completely invisible).
    A sub-module is "covered" when itself OR any ancestor package is
    registered — registering `domains.fields` must continue to satisfy
    `domains.fields.carbon`, since the package's `clear_caches()` aggregates
    all of its sub-modules'; requiring each sub-module to register
    individually would break that aggregate-`clear_caches()` design.
    """
    import importlib
    import pkgutil
    import re

    registered = {m.__name__ for m in domains.CACHE_CLEARING_DOMAINS}

    def _covered(name: str) -> bool:
        """`domains.fields.carbon` is covered by a registered `domains.fields`."""
        parts = name.split(".")
        return any(".".join(parts[:i]) in registered for i in range(len(parts), 1, -1))

    for info in pkgutil.walk_packages(domains.__path__, prefix="domains."):
        mod = importlib.import_module(info.name)
        # Skip dunders: Python sets __cached__ on every module and it matches the
        # cache-name pattern (_ + _ + cache + d__). Narrowing the regex instead would
        # stop matching a bare `_cache`, which is a real cache name. Still correctly
        # excluded below via the startswith("__") filter, independent of the digit
        # widening (`__cached__` has no digits either way).
        #
        # [a-z0-9_], not [a-z_]: digits are ordinary in this domain's cache names
        # (`_co2_meta_cache` in fields/carbon.py was invisible to the letters-only
        # pattern — caught by a whole-branch review, not by this test). Do not
        # narrow this back to [a-z_].
        has_cache = any(
            re.fullmatch(r"_[a-z0-9_]*cache[a-z0-9_]*", n) and not callable(getattr(mod, n))
            for n in dir(mod)
            if not n.startswith("__")
        )
        if has_cache:
            assert _covered(info.name), (
                f"{info.name} declares a cache global but is not covered by "
                f"CACHE_CLEARING_DOMAINS (neither it nor an ancestor package is "
                f"registered) — its caches would never be swept"
            )


def test_all_13_land_layer_caches_are_swept_by_the_admin_sweep():
    """land_layers.py was split into domains/land/{density,extractive,hazards,
    arctic}.py (2026-08-21). Before the split, land_layers.py owned 13 cache
    globals directly and a dedicated test locked that they were swept — that
    test's premise (land_layers OWNS caches) is now false: land_layers itself
    declares none, and every cache moved under domains/land/, which
    pkgutil.walk_packages over domains.__path__ already discovers via the
    generic tests above (land_layers stays registered only as a harmless
    delegating hook, not because it owns any caches).

    This test locks the invariant that actually matters and that the old one
    was really guarding: the live bug where 13 land caches were never swept
    by the admin sweep must not be able to recur. It walks domains.land
    directly (not land_layers) and hard-asserts the count is exactly 13 —
    a count drift means a cache was silently added or lost from the sweep,
    which is exactly the kind of regression this test exists to catch.
    """
    import importlib
    import pkgutil
    import re

    import domains.land as land_pkg

    registered = {m.__name__ for m in domains.CACHE_CLEARING_DOMAINS}

    def _covered(name: str) -> bool:
        parts = name.split(".")
        return any(".".join(parts[:i]) in registered for i in range(len(parts), 1, -1))

    cache_names = []  # (module, name)
    for info in pkgutil.walk_packages(land_pkg.__path__, prefix="domains.land."):
        mod = importlib.import_module(info.name)
        mod_caches = [
            name for name in dir(mod)
            if not name.startswith("__")
            and re.fullmatch(r"_[a-z0-9_]*cache[a-z0-9_]*", name)
            and not callable(getattr(mod, name))
        ]
        if mod_caches:
            assert _covered(info.name), f"{info.name} declares a cache but is not covered by CACHE_CLEARING_DOMAINS"
            cache_names.extend((mod, name) for name in mod_caches)

    # Hard count: 13 (density 2, extractive 5, hazards 4, arctic 2). A changed
    # count means a cache was added or lost from the sweep — update this
    # number deliberately, don't just bump it to make the test pass.
    assert len(cache_names) == 13, (
        f"expected exactly 13 land-layer cache globals under domains.land, found "
        f"{len(cache_names)}: {[(m.__name__, n) for m, n in cache_names]}"
    )

    for mod, name in cache_names:
        setattr(mod, name, "not-empty")

    import land_layers
    land_layers.clear_caches()
    land_layers.clear_caches()  # idempotent

    for mod, name in cache_names:
        val = getattr(mod, name)
        assert not val, f"{mod.__name__}.{name} still populated after clear_caches()"
