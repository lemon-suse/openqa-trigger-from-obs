import io
from xml.etree import ElementTree

import pytest

from script.scriptgen import ActionBatch, ActionGenerator


def make_batch() -> ActionBatch:
    ag = ActionGenerator(
        envdir="/tmp",
        project="openSUSE:Factory:Staging:J",
        productpath="",
        version="Factory",
        brand="obs",
    )
    # normally set by doFile(), needed by p()
    ag.iso_path = ""
    ag.repo_path = "repo"
    ag.domain = ""
    return ActionBatch("default", ag)


def flavor_node(attributes: str) -> ElementTree.Element:
    return ElementTree.fromstring(f"<flavor {attributes}/>")


def test_flavor_sha_is_empty_without_the_attribute():
    batch = make_batch()
    batch.doFlavor(flavor_node('name="Tumbleweed-DVD" iso="1"'))
    assert batch.flavor_sha == {}
    assert batch.sha == "256"


def test_flavor_sha_records_the_override_per_name():
    batch = make_batch()
    batch.doFlavor(flavor_node('name="Tumbleweed-DVD" iso="1"'))
    batch.doFlavor(flavor_node('name="offline-installer" iso="1" sha="512"'))
    assert batch.flavor_sha == {"offline-installer": "512"}
    assert batch.sha == "256"


def test_flavor_sha_splits_alternative_names():
    batch = make_batch()
    batch.doFlavor(flavor_node('name="offline-installer|offline-install" sha="512"'))
    assert batch.flavor_sha == {"offline-installer": "512", "offline-install": "512"}


def test_sha_on_a_node_without_name_sets_the_batch_default():
    batch = make_batch()
    batch.doFlavor(ElementTree.fromstring('<batch sha="512"/>'))
    assert batch.flavor_sha == {}
    assert batch.sha == "512"


@pytest.mark.parametrize(
    "sha,expected_ext,expected_len",
    [
        pytest.param("256", ".sha256", "64", id="default_sha256"),
        pytest.param("512", ".sha512", "128", id="batch_wide_sha512"),
    ],
)
def test_p_bakes_the_default_when_no_flavor_overrides_it(
    sha, expected_ext, expected_len
):
    batch = make_batch()
    batch.sha = sha
    out = io.StringIO()
    batch.p("FLAVORSHALOOKUP\nfile$srcSHAEXT cut -b-SHALEN ASSET_SHAVALUE", out)
    assert (
        out.getvalue() == f"file$src{expected_ext} cut -b-{expected_len} ASSET_{sha}\n"
    )


def test_p_resolves_at_run_time_when_a_flavor_overrides_the_sha():
    batch = make_batch()
    batch.doFlavor(flavor_node('name="offline-installer" sha="512"'))
    out = io.StringIO()
    batch.p("FLAVORSHALOOKUP\nfile$srcSHAEXT cut -b-SHALEN ASSET_SHAVALUE", out)
    assert out.getvalue() == (
        "        shavalue=256\n"
        '        [ -z "${flavor_sha[$flavor]}" ] || shavalue=${flavor_sha[$flavor]}\n'
        '        shaext=".sha$shavalue"\n'
        "        shalen=128\n"
        '        [ "$shavalue" != 256 ] || shalen=64\n'
        "file$src${shaext} cut -b-${shalen} ASSET_${shavalue}\n"
    )


def test_gen_print_array_flavor_sha_is_silent_without_overrides():
    batch = make_batch()
    out = io.StringIO()
    batch.gen_print_array_flavor_sha(out)
    assert out.getvalue() == ""


def test_gen_print_array_flavor_sha_declares_the_overrides():
    batch = make_batch()
    batch.doFlavor(flavor_node('name="offline-installer|offline-install" sha="512"'))
    out = io.StringIO()
    batch.gen_print_array_flavor_sha(out)
    assert out.getvalue() == (
        "declare -A flavor_sha\n"
        "flavor_sha[offline-installer]='512'\n"
        "flavor_sha[offline-install]='512'\n"
    )


NO_BATCH_XML = """<openQA archs="x86_64" dist_path="images/x86_64">
    <flavor name="DVD" distri="opensuse" iso="1" folder="*product*"/>
    <flavor name="offline-installer" distri="opensuse" iso="1" folder="*product*" sha="512"/>
</openQA>"""

BATCH_XML = """<openQA archs="x86_64" dist_path="images/x86_64">
    <batch name="dvd" folder="*product*">
        <flavor name="DVD" distri="opensuse" iso="1"/>
        <flavor name="offline-installer" distri="opensuse" iso="1" sha="512"/>
    </batch>
</openQA>"""

NO_SHA_XML = """<openQA archs="x86_64" dist_path="images/x86_64">
    <batch name="dvd" folder="*product*">
        <flavor name="DVD" distri="opensuse" iso="1"/>
        <flavor name="offline-installer" distri="opensuse" iso="1"/>
    </batch>
</openQA>"""


def generate(tmp_path, xml, generator="gen_print_rsync_iso"):
    xmlfile = tmp_path / "project.xml"
    xmlfile.write_text(xml)
    ag = ActionGenerator(
        envdir=str(tmp_path),
        project="openSUSE:Factory:Staging:J",
        productpath="images/x86_64",
        version="Factory",
        brand="obs",
    )
    ag.doFile(str(xmlfile))
    out = io.StringIO()
    for batch in ag.batches:
        getattr(batch, generator)(out)
    return out.getvalue()


@pytest.mark.parametrize(
    "xml",
    [
        pytest.param(NO_BATCH_XML, id="without_batch"),
        pytest.param(BATCH_XML, id="with_batch"),
    ],
)
@pytest.mark.parametrize(
    "generator",
    ["gen_print_rsync_iso", "gen_print_openqa"],
    ids=["rsync_iso", "openqa"],
)
def test_generated_script_resolves_the_sha_per_flavor(tmp_path, xml, generator):
    script = generate(tmp_path, xml, generator)
    assert "declare -A flavor_sha" in script
    assert "flavor_sha[offline-installer]='512'" in script
    assert "flavor_sha[DVD]" not in script
    assert (
        '[ -z "${flavor_sha[$flavor]}" ] || shavalue=${flavor_sha[$flavor]}' in script
    )
    # nothing is baked in any more, the loop decides
    assert ".sha256" not in script
    assert ".sha512" not in script


@pytest.mark.parametrize(
    "generator",
    ["gen_print_rsync_iso", "gen_print_openqa"],
    ids=["rsync_iso", "openqa"],
)
def test_generated_script_is_untouched_without_an_override(tmp_path, generator):
    script = generate(tmp_path, NO_SHA_XML, generator)
    assert "flavor_sha" not in script
    assert "shavalue" not in script
    assert ".sha256" in script
