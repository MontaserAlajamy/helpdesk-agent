import pytest

from helpdesk import runbooks
from helpdesk.embeddings import HashingEmbedder, cosine, normalize


def test_normalize_strips_tashkeel_and_alef_forms():
    assert normalize("أَهْلاً") == normalize("اهلا")
    assert normalize("مدرسة") == "مدرسه"


def test_embedding_is_deterministic_and_unit_length():
    e = HashingEmbedder(64)
    a, b = e.embed("VPN will not connect"), e.embed("VPN will not connect")
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9


def test_similar_text_scores_higher_than_unrelated():
    e = HashingEmbedder(256)
    q = e.embed("printer offline")
    assert cosine(q, e.embed("The printer is offline and not printing")) > cosine(q, e.embed("forgot my password"))


def test_parse_runbook_rejects_missing_header():
    with pytest.raises(ValueError):
        runbooks.parse_runbook("# Title only\nbody")


def test_all_shipped_runbooks_parse():
    docs = runbooks.load_dir(runbooks.Path(__file__).resolve().parents[1] / "data" / "runbooks")
    assert len(docs) >= 9
    assert len({d.id for d in docs}) == len(docs)


async def test_search_finds_the_right_runbook(sessions):
    async with sessions() as s:
        hits = await runbooks.search(s, "الطابعة ما بتطبع", HashingEmbedder(256), k=3)
    assert hits[0].id == "printer-offline"
    assert hits[0].score >= hits[-1].score
