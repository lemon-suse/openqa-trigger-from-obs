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


def test_batch_node_sha_sets_the_batch_default():
    # doBatch() appends to ag.batches; make_batch() sets iso_path, repo_path,
    # domain by hand because only doFile() normally sets them
    ag = ActionGenerator(
        envdir="/tmp",
        project="openSUSE:Factory:Staging:J",
        productpath="",
        version="Factory",
        brand="obs",
    )
    ag.iso_path = ""
    ag.repo_path = "repo"
    ag.domain = ""
    ag.doBatch(ElementTree.fromstring('<batch name="caribe" sha="512"/>'))
    batch = ag.batches[0]
    assert batch.sha == "512"
    assert batch.flavor_sha == {}


def test_root_node_sha_is_not_a_batch_default():
    # Batch-level sha must be guarded by node.tag == "batch" because doBatch()
    # is also called with the root openQA node when no explicit batches exist
    ag = ActionGenerator(
        envdir="/tmp",
        project="openSUSE:Factory:Staging:J",
        productpath="",
        version="Factory",
        brand="obs",
    )
    ag.iso_path = ""
    ag.repo_path = "repo"
    ag.domain = ""
    ag.doBatch(ElementTree.fromstring('<openQA name="x" sha="512"/>'))
    batch = ag.batches[0]
    assert batch.sha == "256"


def test_p_resolves_at_run_time_when_no_flavor_overrides_it():
    batch = make_batch()
    batch.sha = "256"
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


def test_gen_print_array_flavor_sha_always_declares_the_array():
    batch = make_batch()
    out = io.StringIO()
    batch.gen_print_array_flavor_sha(out)
    assert out.getvalue() == "declare -A flavor_sha\n"


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

BATCH_SHA_XML = """<openQA archs="x86_64" dist_path="images/x86_64">
    <batch name="dvd" folder="*product*" sha="512">
        <flavor name="DVD" distri="opensuse" iso="1"/>
        <flavor name="offline-installer" distri="opensuse" iso="1" sha="256"/>
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
def test_generated_script_with_no_overrides_uses_per_flavor_resolution(
    tmp_path, generator
):
    script = generate(tmp_path, NO_SHA_XML, generator)
    assert "declare -A flavor_sha" in script
    assert (
        '[ -z "${flavor_sha[$flavor]}" ] || shavalue=${flavor_sha[$flavor]}' in script
    )
    assert "shavalue=256" in script
    # per-flavor resolution uses shell variables, not constants
    assert ".sha256" not in script
    assert ".sha512" not in script


@pytest.mark.parametrize(
    "generator",
    ["gen_print_rsync_iso", "gen_print_openqa"],
    ids=["rsync_iso", "openqa"],
)
def test_batch_sha_default_with_flavor_override(tmp_path, generator):
    # Batch-level sha sets the default; flavor-level sha overrides it
    script = generate(tmp_path, BATCH_SHA_XML, generator)
    assert "declare -A flavor_sha" in script
    assert "shavalue=512" in script
    assert "flavor_sha[offline-installer]='256'" in script
    assert "flavor_sha[DVD]" not in script
    assert (
        '[ -z "${flavor_sha[$flavor]}" ] || shavalue=${flavor_sha[$flavor]}' in script
    )
    # per-flavor resolution uses shell variables, not constants
    assert ".sha256" not in script
    assert ".sha512" not in script
