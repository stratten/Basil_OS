from pathlib import Path

import pytest

from api.services.meeting_companion.context_pack import ContextPack
from api.services.meeting_companion.context_search import FileEntry, validate_root
from api.services.meeting_companion.context_service import ContextService
from api.services.meeting_companion.prefetch import PrefetchCache, derive_queries, queries_fingerprint
from api.services.meeting_companion.symbol_vocabulary import SymbolVocabulary, build_symbol_vocabulary, normalize_key


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    write(root / "src" / "retry_policy.py", "class RetryPolicy:\n    max_attempts = 5\n\n\ndef generate_invoice(customer):\n    return customer\n")
    write(root / "README.md", "Notes about the project.\n")
    return root


def attach(service: ContextService, root: Path, root_id: str = "r1") -> None:
    resolved, kind = validate_root(str(root), home=root.parent.parent)
    service.attach_root(root_id, resolved, kind, root.name)


def test_normalize_key_collides_across_spellings():
    assert normalize_key("RetryPolicy") == normalize_key("retry_policy") == normalize_key("retry policy") == "retrypolicy"


def test_vocabulary_ignores_generic_and_short_names_and_matches_word_runs():
    vocabulary = SymbolVocabulary()
    for name in ("index", "main", "abc", "RetryPolicy", "generate_invoice"):
        vocabulary.add(name)
    assert len(vocabulary) == 2
    assert vocabulary.match_words(["how", "does", "retry", "policy", "work"]) == ["RetryPolicy"]
    assert vocabulary.match_words(["generate", "invoice", "and", "retry", "policy", "retry", "policy"]) == ["generate_invoice", "RetryPolicy"]
    assert vocabulary.match_words([]) == []


def test_vocabulary_respects_capacity():
    vocabulary = SymbolVocabulary(max_names=2)
    for name in ("alphabeta", "gammadelta", "epsilonzeta"):
        vocabulary.add(name)
    assert len(vocabulary) == 2 and vocabulary.full


def test_build_vocabulary_from_stems_and_definitions(project):
    entries = [
        ("r1", FileEntry("src/retry_policy.py", project / "src" / "retry_policy.py", 100, 2.0)),
        ("r1", FileEntry("README.md", project / "README.md", 10, 1.0)),
    ]
    vocabulary = build_symbol_vocabulary(entries)
    assert [normalize_key(name) for name in vocabulary.match_words(["generate", "invoice"])] == ["generateinvoice"]
    assert [normalize_key(name) for name in vocabulary.match_words(["retry", "policy"])] == ["retrypolicy"]
    assert vocabulary.match_words(["readme"]) == []


def test_build_vocabulary_stops_at_time_budget(project):
    ticks = iter(float(index) for index in range(100))
    entries = [("r1", FileEntry("src/retry_policy.py", project / "src" / "retry_policy.py", 100, 2.0))]
    vocabulary = build_symbol_vocabulary(entries, time_budget_seconds=0.5, clock=lambda: next(ticks))
    assert vocabulary.match_words(["generate", "invoice"]) == []
    assert [normalize_key(name) for name in vocabulary.match_words(["retry", "policy"])] == ["retrypolicy"]


def test_derive_queries_identifiers_first_and_deduplicated_by_key():
    queries = derive_queries("we call getRetryPolicy then retry_policy.py and billing_service plus RetryPolicy")
    assert queries[0] == "getRetryPolicy"
    assert "billing_service" in queries and len(queries) <= 4
    assert len({normalize_key(query) for query in queries}) == len(queries)


def test_derive_queries_uses_vocabulary_and_skips_frequency_fallback_when_found():
    vocabulary = SymbolVocabulary()
    vocabulary.add("RetryPolicy")
    assert derive_queries("how does the retry policy handle timeouts", vocabulary) == ["RetryPolicy"]


def test_derive_queries_frequency_fallback_only_when_nothing_else_found():
    queries = derive_queries("the deployment pipeline keeps failing on deployment checks")
    assert queries[0] == "deployment" and len(queries) <= 2
    assert derive_queries("yeah okay so right") == []
    assert derive_queries("") == []


def test_cache_exact_overlap_ttl_and_lru():
    cache = PrefetchCache(max_entries=2, ttl_seconds=10.0)
    pack = ContextPack(queries=["a"])
    assert queries_fingerprint(["B_two", "a_one"]) == queries_fingerprint(["a one", "b two"])
    cache.put(["alpha_one", "beta_two"], pack, now=0.0)
    assert cache.get(["beta_two", "alpha_one"], now=1.0) is pack
    assert cache.find(["alpha_one"], now=1.0) is pack
    assert cache.find(["gamma_three"], now=1.0) is None
    assert cache.get(["alpha_one", "beta_two"], now=11.5) is None
    assert len(cache) == 0
    cache.put(["aaaa_one"], pack, now=20.0)
    cache.put(["bbbb_two"], pack, now=20.0)
    cache.put(["cccc_three"], pack, now=20.0)
    assert len(cache) == 2 and cache.get(["aaaa_one"], now=20.0) is None
    cache.put([], pack, now=20.0)
    assert len(cache) == 2


@pytest.mark.asyncio
async def test_service_prefetch_then_lookup_hits_cache(project):
    service = ContextService()
    attach(service, project)
    assert await service.rebuild_vocabulary() > 0
    first = await service.prefetch("how does the retry policy handle timeouts")
    assert first is not None and first.cache == "miss" and first.pack.hit_count > 0
    assert await service.prefetch("how does the retry policy handle timeouts") is None
    second = await service.lookup("what is the retry policy again")
    assert second is not None and second.cache == "hit" and second.pack.hit_count > 0


@pytest.mark.asyncio
async def test_service_without_roots_or_queries_returns_none(project):
    service = ContextService()
    assert await service.prefetch("how does the retry policy work") is None
    assert await service.lookup("how does the retry policy work") is None
    attach(service, project)
    assert await service.prefetch("yeah okay") is None
    assert await service.lookup("yeah okay") is None


@pytest.mark.asyncio
async def test_roots_change_clears_cache_and_detach_disables(project, tmp_path):
    service = ContextService()
    attach(service, project)
    await service.rebuild_vocabulary()
    assert (await service.lookup("the retry policy")).cache == "miss"
    assert (await service.lookup("the retry policy")).cache == "hit"
    other = tmp_path / "other"
    write(other / "billing_service.py", "def run():\n    pass\n")
    attach(service, other, "r2")
    assert (await service.lookup("the retry policy")).cache == "miss"
    service.detach_root("r1")
    service.detach_root("r2")
    assert service.has_roots() is False
    assert await service.lookup("the retry policy") is None


@pytest.mark.asyncio
async def test_lookup_uses_extra_queries(project):
    service = ContextService()
    attach(service, project)
    result = await service.lookup("what does that do", extra_queries=["generate_invoice"])
    assert result is not None and result.queries == ["generate_invoice"] and result.pack.hit_count > 0
