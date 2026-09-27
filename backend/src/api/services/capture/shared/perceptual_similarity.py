"""Hamming-distance comparison for native difference-hash fingerprints."""

SIMILARITY_HAMMING_THRESHOLD = 4


def hamming_distance(hash_a: str | None, hash_b: str | None) -> int:
    """Return a safe bit-level Hamming distance for two hexadecimal hashes."""
    try:
        value_a = int(hash_a, 16)
        value_b = int(hash_b, 16)
    except (TypeError, ValueError):
        return SIMILARITY_HAMMING_THRESHOLD + 1
    return (value_a ^ value_b).bit_count()


def is_functionally_unchanged(hash_a: str | None, hash_b: str | None) -> bool:
    """Return whether two difference hashes are within the similarity threshold."""
    return hamming_distance(hash_a, hash_b) <= SIMILARITY_HAMMING_THRESHOLD
