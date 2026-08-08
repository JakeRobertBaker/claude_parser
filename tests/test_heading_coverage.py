from claude_parser.application.batch_tools.heading_coverage import (
    source_heading_advisories,
)
from claude_parser.domain.annotation_parser import parse_annotations


def test_reports_missing_generic_headings_without_confusing_later_theorem() -> None:
    raw = [
        "# E Sequences and Continuity\n",
        "# Bolzano-Weierstrass Theorem\n",
        "# 0.66 Definition monotone\n",
        "# 0.73 Bolzano-Weierstrass Theorem\n",
        "# Continuity and Uniform Continuity\n",
    ]
    cleaned = """\
@ - id="sec_e" title="E Sequences and Continuity"
@ -- id="def_0_66" type="definition" title="monotone"
@ -- id="thm_0_73" type="theorem" title="Bolzano-Weierstrass Theorem"
@ -- id="sec_e_continuity" title="Continuity and Uniform Continuity"
"""

    advisories = source_heading_advisories(
        raw, len(raw), parse_annotations(cleaned)
    )

    assert advisories == [
        {
            "code": "possibly_unrepresented_source_heading",
            "raw_line": 2,
            "title": "Bolzano-Weierstrass Theorem",
        }
    ]


def test_normalizes_tex_in_matching_container_titles() -> None:
    raw = ["# Open Subsets of $\\mathbf { R } ^ { n }$\n"]
    cleaned = '@ - id="open" title="Open Subsets of Rn"\n'

    assert source_heading_advisories(raw, 1, parse_annotations(cleaned)) == []
