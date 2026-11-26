import mongomock
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from advisor.graph.deps import build_deps
from advisor.graph.runner import ResearchService
from advisor.harness import Policy
from advisor.settings import ROOT
from advisor.storage import Repository
from tests.fakes import FakeLLM, FakeSource, FakeWebTools


@pytest.fixture
def repo():
    r = Repository(mongomock.MongoClient(tz_aware=True)["advisor_test"])
    r.ensure_indexes()
    return r


@pytest.fixture
def policy():
    return Policy.load(ROOT / "config")


@pytest.fixture
def fakes():
    return {"source": FakeSource(), "web": FakeWebTools(), "llm": FakeLLM()}


@pytest.fixture
def deps(repo, policy, fakes):
    return build_deps(repo, fakes["llm"], policy, source=fakes["source"], web_tools=fakes["web"])


@pytest.fixture
def service(deps):
    return ResearchService(deps, InMemorySaver())
