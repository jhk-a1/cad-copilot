"""Manufacturability, ISO-286 fit & mobility gates (ADR-010, Pillars C+D).

The fit tests check against PUBLISHED ISO-286 values (the IT tables and textbook H7/g6 clearances),
so a passing suite means the formulas are the real standard, not invented numbers. The mobility
tests check against known mechanisms (a four-bar is 1-DOF with 1 loop).
"""

from __future__ import annotations

import pytest

from ai_server.services.genome.dfm import (
    Joint,
    analyze_mechanism,
    iso_fit,
    it_tolerance_um,
    manufacturability_certificate,
)

# --------------------------------------------------------------------------- manufacturability


def test_wall_thinner_than_process_minimum_fails():
    cert = manufacturability_certificate(process="injection", wall_mm=0.6)
    assert not cert.ok
    assert "DFM FAIL" in cert.summary()


def test_adequate_wall_passes():
    cert = manufacturability_certificate(process="fdm", wall_mm=4.0, min_feature_mm=1.2)
    assert cert.ok
    assert "DFM OK" in cert.summary()


def test_injection_without_draft_warns():
    cert = manufacturability_certificate(process="injection", wall_mm=2.0, draft_deg=0.0)
    assert cert.ok  # a draft shortfall is a warning, not an outright fail
    assert cert.warnings and any(f.rule == "draft" for f in cert.warnings)


def test_cnc_sharp_internal_corner_warns_not_fails():
    cert = manufacturability_certificate(process="cnc", internal_radius_mm=0.0)
    assert cert.ok
    assert any(f.rule == "internal_radius" and f.severity == "warn" for f in cert.findings)


def test_not_applicable_dims_are_skipped():
    cert = manufacturability_certificate(process="fdm")  # nothing supplied
    assert cert.ok and not cert.findings


# --------------------------------------------------------------------------- ISO-286 fits


@pytest.mark.parametrize("nominal,grade,expected_um", [
    (20, 7, 21),    # IT7 @ Ø18-30  -> 21 µm (published)
    (20, 6, 13),    # IT6 @ Ø18-30  -> 13 µm
    (50, 7, 25),    # IT7 @ Ø30-50  -> 25 µm
    (10, 7, 15),    # IT7 @ Ø6-10   -> 15 µm
])
def test_it_tolerance_matches_published_tables(nominal, grade, expected_um):
    assert it_tolerance_um(nominal, grade) == pytest.approx(expected_um, abs=1)


def test_h7_g6_sliding_fit_matches_textbook():
    fit = iso_fit(20, "H7", "g6")
    assert fit.kind == "clearance"
    # textbook H7/g6 Ø20: clearance 7..41 µm
    assert fit.min_clearance_um == pytest.approx(7, abs=1)
    assert fit.max_clearance_um == pytest.approx(41, abs=1)


def test_h7_h6_is_a_clearance_to_zero_fit():
    fit = iso_fit(20, "H7", "h6")
    assert fit.min_clearance_um == pytest.approx(0, abs=1)  # smallest hole meets largest shaft at 0
    assert fit.max_clearance_um > 0
    assert fit.kind == "clearance"


def test_h7_p6_is_interference():
    fit = iso_fit(20, "H7", "p6")
    assert fit.kind == "interference"
    assert fit.max_clearance_um <= 0  # even the loosest case is a press fit


def test_only_hole_basis_supported():
    with pytest.raises(ValueError):
        iso_fit(20, "G7", "h6")


# --------------------------------------------------------------------------- mobility / mate network


def test_four_bar_linkage_is_one_dof_with_one_loop():
    # 4 links (incl. ground), 4 revolute joints, planar -> M = 3*(4-1-4)+4 = 1; one kinematic loop
    links = {"ground", "crank", "coupler", "rocker"}
    joints = [Joint("ground", "crank", "revolute"), Joint("crank", "coupler", "revolute"),
              Joint("coupler", "rocker", "revolute"), Joint("rocker", "ground", "revolute")]
    cert = analyze_mechanism(links, joints, planar=True, expected="mechanism")
    assert cert.mobility == 1
    assert cert.loops == 1
    assert cert.classification == "mechanism" and cert.ok
    assert "loop closure" in cert.summary()


def test_handle_on_body_is_a_rigid_structure():
    # a part welded to ground: M=0, no loops -> a rigid structure (what the mug+handle is)
    links = {"body", "handle"}
    joints = [Joint("body", "handle", "fixed")]
    cert = analyze_mechanism(links, joints, expected="structure")
    assert cert.mobility == 0 and cert.loops == 0
    assert cert.classification == "structure" and cert.ok


def test_over_constrained_assembly_is_flagged():
    # two links pinned by THREE coincident revolute joints (spatial): redundant constraints -> M<0
    links = {"ground", "link"}
    joints = [Joint("ground", "link", "revolute")] * 3
    cert = analyze_mechanism(links, joints, expected="structure")
    assert cert.mobility < 0
    assert cert.classification == "over-constrained" and not cert.ok
    assert "redundant" in cert.summary()


def test_detached_part_is_reported():
    links = {"ground", "floating"}
    cert = analyze_mechanism(links, [], expected="structure")
    assert not cert.ok
    assert any("not attached" in n for n in cert.notes)
