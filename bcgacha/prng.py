"""The Battle Cats rare-gacha PRNG.

A single 32-bit xorshift state ("the seed") drives every rare capsule draw on an
account.  The shift triple is (13 left, 17 right, 15 left) -- note this is NOT
Marsaglia's classic (13, 17, 5).

The generator is exactly invertible, which is what lets a tracker step backwards
to recover the seed a player was on before a roll.
"""

MASK = 0xFFFFFFFF


def advance(seed: int) -> int:
    """Step the seed forward once."""
    seed ^= (seed << 13) & MASK
    seed ^= seed >> 17
    seed ^= (seed << 15) & MASK
    return seed


def retreat(seed: int) -> int:
    """Step the seed backwards once, the exact inverse of advance().

    Each shift-xor is undone in reverse order.  A left shift of n needs
    ceil(32 / n) - 1 extra terms to invert; the right shift of 17 needs none
    because 17 >= 16.
    """
    seed ^= (seed << 15) & MASK
    seed ^= (seed << 30) & MASK
    seed ^= seed >> 17
    seed ^= (seed << 13) & MASK
    seed ^= (seed << 26) & MASK
    return seed


def stream(seed: int, count: int) -> list[int]:
    """Return the next `count` seeds, excluding the one passed in."""
    out = []
    for _ in range(count):
        seed = advance(seed)
        out.append(seed)
    return out
