"""Extra named poses (SNA low-E frets) load without warnings and gate the riff."""
import fret
import pytest

POSE = {str(s): 1000 for s in fret.MOTOR_IDS}


def entries(*names):
    return [{"name": name, "time": "t", "positions": dict(POSE)} for name in names]


def test_extras_are_parsed_not_warned():
    m = fret.load_map(entries=entries("rest", "pose-r1-c1", "7", "10", "2"))
    assert sorted(m["extras"]) == ["10", "2", "7"]
    assert m["warns"] == []
    assert (1, 1) in m["cells"]


def test_near_miss_grid_names_still_warn():
    m = fret.load_map(entries=entries("rest", "pose-r1c9x"))
    assert m["extras"] == {} and len(m["warns"]) == 1


def test_riff_requires_all_extra_poses():
    arm = object.__new__(fret.FretArm)
    arm.extras = {"7": POSE, "10": POSE}
    with pytest.raises(ValueError, match="not recorded"):
        arm.play_riff(fret.SNA_RIFF)


def test_sna_riff_uses_only_the_recorded_pose_names():
    assert {name for name, _ in fret.SNA_RIFF} == {"2", "3", "5", "7", "10"}
    assert len(fret.SNA_RIFF) == 16  # 7 7 10 7 5 3 2 | 7 7 10 7 5 3 5 3 2


def test_v4_shorthand_cell_names_parse():
    m = fret.load_map(entries=entries("rest", "r1_1", "r4_6", "r2-3", "neutral"))
    assert set(m["cells"]) == {(1, 1), (6, 4), (3, 2)}
    assert "neutral" in m["extras"] and m["warns"] == []
