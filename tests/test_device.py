"""What is decided about a device without one attached."""

from bcgacha import device


def test_the_tested_iphone_shape_is_known_either_way_round():
    assert device.tested_shape(2532, 1170)
    assert device.tested_shape(1170, 2532)


def test_an_ipad_shape_is_untested():
    assert not device.tested_shape(2360, 1640)


def test_a_version_reads_up_to_its_first_non_number():
    assert device.version_tuple("27.0.1") == (27, 0, 1)
    assert device.version_tuple("26.4b2") == (26,)
