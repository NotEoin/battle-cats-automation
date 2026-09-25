"""What is on the Storage screen: a capsule's panel, or the field itself."""

from bcgacha import perception, storage


def _t(text, x, y):
    return perception.Text(text, (x - 0.05, y - 0.02, x + 0.05, y + 0.02), 0.9)


def test_a_panel_is_known_by_its_buttons_even_without_a_count():
    """Bounty Up's panel never says how many there are."""
    texts = [_t("Bounty Up", 0.5, 0.53), _t("Use", 0.31, 0.78), _t("Exchange for XP", 0.5, 0.78),
             _t("Trade-in", 0.65, 0.77)]
    assert storage.is_panel(texts)


def test_the_storage_field_is_not_a_panel():
    """Its own Use all and Exchange all sit lower, along the bottom bar."""
    texts = [_t("Storage", 0.1, 0.04), _t("Use all", 0.47, 0.91), _t("Exchange all for NP/XP", 0.64, 0.91)]
    assert not storage.is_panel(texts)
