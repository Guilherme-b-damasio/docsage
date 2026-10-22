import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from docsage import __version__  # noqa: E402
from docsage.container import Container, Settings  # noqa: E402
from docsage.domain.models import TokenUsage  # noqa: E402
from docsage.interfaces.http_api import build_app  # noqa: E402


class FakeGenerator:
    last_usage = TokenUsage("claude-opus-5-5", 100, 20)

    def generate(self, question, context):
        return f"Alpha is described in [1]. ({len(context)} passages)"


class FakeUrlLoader:
    def load(self, url):
        raise OSError("offline")


@pytest.fixture
def docs(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.md").write_text("# Alpha\n\nalpha notes about retrieval", encoding="utf-8")
    (folder / "b.md").write_text("beta notes", encoding="utf-8")
    return folder


@pytest.fixture
def client(tmp_path):
    settings = Settings(index_path=tmp_path / "index.json")
    container = Container(settings, FakeGenerator(), url_loader=FakeUrlLoader())
    return TestClient(build_app(container))


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "version": __version__}


def test_index_then_search(client, docs):
    response = client.post("/index", json={"targets": [str(docs)]})

    assert response.status_code == 200
    assert response.json()["documents"] == 2

    results = client.get("/search", params={"q": "alpha", "top_k": 1}).json()
    assert results["query"] == "alpha"
    assert [item["chunk"]["source"] for item in results["results"]] == [str(docs / "a.md")]
    assert results["results"][0]["matched_terms"] == ["alpha"]


def test_index_skips_unchanged_documents_unless_forced(client, docs):
    client.post("/index", json={"targets": [str(docs)]})

    assert client.post("/index", json={"targets": [str(docs)]}).json()["unchanged"] == 2
    forced = client.post("/index", json={"targets": [str(docs)], "force": True}).json()
    assert forced["documents"] == 2


def test_index_reports_pages_that_fail_and_still_indexes_files(client, docs):
    payload = client.post(
        "/index", json={"targets": [str(docs / "a.md"), "https://example.com/guide"]}
    ).json()

    assert payload["documents"] == 1
    assert payload["failed"] == [{"url": "https://example.com/guide", "reason": "offline"}]


def test_index_rejects_missing_paths_and_empty_requests(client, tmp_path):
    missing = client.post("/index", json={"targets": [str(tmp_path / "nope")]})
    assert missing.status_code == 404
    assert "No such file or folder" in missing.json()["detail"]

    assert client.post("/index", json={"targets": []}).status_code == 422


def test_search_validates_its_parameters(client):
    assert client.get("/search").status_code == 422
    assert client.get("/search", params={"q": "alpha", "top_k": 0}).status_code == 422
    assert client.get("/search", params={"q": "alpha", "top_k": 51}).status_code == 422


def test_search_on_an_empty_index_returns_no_results(client):
    assert client.get("/search", params={"q": "alpha"}).json() == {
        "query": "alpha",
        "source": "",
        "results": [],
    }


def test_search_narrows_results_to_a_source(client, docs):
    client.post("/index", json={"targets": [str(docs)]})

    payload = client.get("/search", params={"q": "notes", "source": "docs"}).json()
    assert payload["source"] == "docs"
    assert len(payload["results"]) == 2

    other = client.get("/search", params={"q": "notes", "source": ".pdf"}).json()
    assert other["results"] == []


def test_ask_answers_with_sources_usage_and_cost(client, docs):
    client.post("/index", json={"targets": [str(docs)]})

    payload = client.post("/ask", json={"question": "what is alpha?", "top_k": 2}).json()

    assert payload["question"] == "what is alpha?"
    assert payload["answer"].startswith("Alpha is described in [1].")
    assert payload["sources"][0]["chunk"]["source"] == str(docs / "a.md")
    assert payload["usage"]["input_tokens"] == 100
    assert payload["cost_usd"] is not None


def test_ask_rejects_blank_questions_and_a_large_top_k(client):
    assert client.post("/ask", json={"question": ""}).status_code == 422
    assert client.post("/ask", json={"question": "   "}).status_code == 422
    assert client.post("/ask", json={"question": "x", "top_k": 99}).status_code == 422


def test_stats_summarizes_the_index(client, docs):
    client.post("/index", json={"targets": [str(docs)]})

    payload = client.get("/stats", params={"top": 2}).json()

    assert (payload["documents"], payload["chunks"]) == (2, 2)
    assert len(payload["top_terms"]) == 2
    assert client.get("/stats", params={"top": -1}).status_code == 422


def test_root_redirects_to_the_web_ui(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/ui"


def test_web_ui_home_shows_the_search_form(client):
    response = client.get("/ui")

    assert response.headers["content-type"].startswith("text/html")
    assert '<form class="search" method="get" action="/ui"' in response.text
    assert 'formaction="/ui/ask"' in response.text
    assert '<a href="/ui/dashboard">Dashboard</a>' in response.text


def test_web_ui_search_page_lists_highlighted_results(client, docs):
    client.post("/index", json={"targets": [str(docs)]})

    html = client.get("/ui", params={"q": "alpha"}).text

    assert "1 matching passage" in html
    assert '<mark title="alpha">' in html
    assert 'value="alpha"' in html
    assert client.get("/ui", params={"q": "alpha", "top_k": 0}).status_code == 422


def test_web_ui_ask_renders_the_answer_report(client, docs):
    client.post("/index", json={"targets": [str(docs)]})

    response = client.get("/ui/ask", params={"q": "what is alpha?"})

    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>what is alpha?</h1>" in response.text
    assert '<a class="cite" href="#source-1">[1]</a>' in response.text


def test_web_ui_links_citations_to_the_served_source(client, docs):
    from urllib.parse import quote

    client.post("/index", json={"targets": [str(docs)]})
    href = f"/ui/source?path={quote(str(docs / 'a.md'), safe='')}"

    search = client.get("/ui", params={"q": "alpha"}).text
    answer = client.get("/ui/ask", params={"q": "what is alpha?"}).text

    assert f'href="{href}"' in search
    assert f'href="{href}"' in answer


def test_web_ui_serves_an_indexed_file_as_sandboxed_text(client, docs):
    client.post("/index", json={"targets": [str(docs)]})

    response = client.get("/ui/source", params={"path": str(docs / "a.md")})

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-security-policy"] == "sandbox"
    assert "alpha notes about retrieval" in response.text


def test_web_ui_refuses_files_that_are_not_indexed(client, docs, tmp_path):
    client.post("/index", json={"targets": [str(docs / "a.md")]})
    secret = tmp_path / "secret.txt"
    secret.write_text("do not serve", encoding="utf-8")

    assert client.get("/ui/source", params={"path": str(secret)}).status_code == 404
    assert client.get("/ui/source", params={"path": str(docs / "b.md")}).status_code == 404


def test_web_ui_says_when_an_indexed_file_is_gone(client, docs):
    client.post("/index", json={"targets": [str(docs)]})
    (docs / "a.md").unlink()

    response = client.get("/ui/source", params={"path": str(docs / "a.md")})

    assert response.status_code == 404
    assert "no longer on disk" in response.json()["detail"]


def test_web_ui_ask_without_a_question_goes_back_to_the_search_page(client):
    response = client.get("/ui/ask", params={"q": "  "}, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/ui"


def test_web_ui_dashboard_renders_the_index_overview(client, docs):
    client.post("/index", json={"targets": [str(docs)]})

    response = client.get("/ui/dashboard")

    assert response.status_code == 200
    assert response.text.startswith("<!doctype html>")
    assert "a.md" in response.text
