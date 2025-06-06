# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import dataclasses
import importlib
from typing import Optional
from unittest import mock

from google import auth
import vertexai
from google.cloud.aiplatform import initializer
from vertexai.preview import reasoning_engines
from vertexai.reasoning_engines import _utils
import pytest


_DEFAULT_PLACE_TOOL_ACTIVITY = "museums"
_DEFAULT_PLACE_TOOL_PAGE_SIZE = 3
_DEFAULT_PLACE_PHOTO_MAXWIDTH = 400
_TEST_LOCATION = "us-central1"
_TEST_PROJECT = "test-project"
_TEST_MODEL = "gemini-1.0-pro"
_TEST_RUNNABLE_NAME = "test-runnable"
_TEST_SYSTEM_INSTRUCTION = "You are a helpful bot."


def place_tool_query(
    city: str,
    activity: str = _DEFAULT_PLACE_TOOL_ACTIVITY,
    page_size: int = _DEFAULT_PLACE_TOOL_PAGE_SIZE,
):
    """Searches the city for recommendations on the activity."""
    return {"city": city, "activity": activity, "page_size": page_size}


def place_photo_query(
    photo_reference: str,
    maxwidth: int = _DEFAULT_PLACE_PHOTO_MAXWIDTH,
    maxheight: Optional[int] = None,
):
    """Returns the photo for a given reference."""
    result = {"photo_reference": photo_reference, "maxwidth": maxwidth}
    if maxheight:
        result["maxheight"] = maxheight
    return result


@pytest.fixture(scope="module")
def google_auth_mock():
    with mock.patch.object(auth, "default") as google_auth_mock:
        credentials_mock = mock.Mock()
        credentials_mock.with_quota_project.return_value = None
        google_auth_mock.return_value = (
            credentials_mock,
            _TEST_PROJECT,
        )
        yield google_auth_mock


@pytest.fixture
def vertexai_init_mock():
    with mock.patch.object(vertexai, "init") as vertexai_init_mock:
        yield vertexai_init_mock


@pytest.fixture
def dataclasses_asdict_mock():
    with mock.patch.object(dataclasses, "asdict") as dataclasses_asdict_mock:
        dataclasses_asdict_mock.return_value = {}
        yield dataclasses_asdict_mock


@pytest.fixture
def cloud_trace_exporter_mock():
    with mock.patch.object(
        _utils,
        "_import_cloud_trace_exporter_or_warn",
    ) as cloud_trace_exporter_mock:
        yield cloud_trace_exporter_mock


@pytest.fixture
def tracer_provider_mock():
    with mock.patch("opentelemetry.sdk.trace.TracerProvider") as tracer_provider_mock:
        yield tracer_provider_mock


@pytest.fixture
def simple_span_processor_mock():
    with mock.patch(
        "opentelemetry.sdk.trace.export.SimpleSpanProcessor"
    ) as simple_span_processor_mock:
        yield simple_span_processor_mock


@pytest.fixture
def autogen_instrumentor_mock():
    with mock.patch.object(
        _utils,
        "_import_openinference_autogen_or_warn",
    ) as autogen_instrumentor_mock:
        yield autogen_instrumentor_mock


@pytest.fixture
def autogen_instrumentor_none_mock():
    with mock.patch.object(
        _utils,
        "_import_openinference_autogen_or_warn",
    ) as autogen_instrumentor_mock:
        autogen_instrumentor_mock.return_value = None
        yield autogen_instrumentor_mock


@pytest.fixture
def autogen_tools_mock():
    with mock.patch.object(
        _utils,
        "_import_autogen_tools_or_warn",
    ) as autogen_tools_mock:
        autogen_tools_mock.return_value = mock.MagicMock()
        yield autogen_tools_mock


@pytest.mark.usefixtures("google_auth_mock")
class TestAG2Agent:
    def setup_method(self):
        importlib.reload(initializer)
        importlib.reload(vertexai)
        vertexai.init(
            project=_TEST_PROJECT,
            location=_TEST_LOCATION,
        )

    def teardown_method(self):
        initializer.global_pool.shutdown(wait=True)

    def test_initialization(self):
        agent = reasoning_engines.AG2Agent(
            model=_TEST_MODEL, runnable_name=_TEST_RUNNABLE_NAME
        )
        assert agent._model_name == _TEST_MODEL
        assert agent._runnable_name == _TEST_RUNNABLE_NAME
        assert agent._project == _TEST_PROJECT
        assert agent._location == _TEST_LOCATION
        assert agent._runnable is None

    def test_initialization_with_tools(self, autogen_tools_mock):
        tools = [
            place_tool_query,
            place_photo_query,
        ]
        agent = reasoning_engines.AG2Agent(
            model=_TEST_MODEL,
            runnable_name=_TEST_RUNNABLE_NAME,
            system_instruction=_TEST_SYSTEM_INSTRUCTION,
            tools=tools,
            runnable_builder=lambda **kwargs: kwargs,
        )
        assert agent._runnable is None
        assert agent._tools
        assert not agent._ag2_tool_objects
        agent.set_up()
        assert agent._runnable is not None
        assert agent._ag2_tool_objects

    def test_set_up(self):
        agent = reasoning_engines.AG2Agent(
            model=_TEST_MODEL,
            runnable_name=_TEST_RUNNABLE_NAME,
            runnable_builder=lambda **kwargs: kwargs,
        )
        assert agent._runnable is None
        agent.set_up()
        assert agent._runnable is not None

    def test_clone(self):
        agent = reasoning_engines.AG2Agent(
            model=_TEST_MODEL,
            runnable_name=_TEST_RUNNABLE_NAME,
            runnable_builder=lambda **kwargs: kwargs,
        )
        agent.set_up()
        assert agent._runnable is not None
        agent_clone = agent.clone()
        assert agent._runnable is not None
        assert agent_clone._runnable is None
        agent_clone.set_up()
        assert agent_clone._runnable is not None

    def test_query(self, dataclasses_asdict_mock):
        agent = reasoning_engines.AG2Agent(
            model=_TEST_MODEL,
            runnable_name=_TEST_RUNNABLE_NAME,
        )
        agent._runnable = mock.Mock()
        mocks = mock.Mock()
        mocks.attach_mock(mock=agent._runnable, attribute="run")
        agent.query(input="test query")
        mocks.assert_has_calls(
            [
                mock.call.run.run(
                    {"content": "test query"},
                    user_input=False,
                    tools=[],
                    max_turns=None,
                )
            ]
        )

    @pytest.mark.usefixtures("caplog")
    def test_enable_tracing(
        self,
        caplog,
        cloud_trace_exporter_mock,
        tracer_provider_mock,
        simple_span_processor_mock,
        autogen_instrumentor_mock,
    ):
        agent = reasoning_engines.AG2Agent(
            model=_TEST_MODEL,
            runnable_name=_TEST_RUNNABLE_NAME,
            enable_tracing=True,
        )
        assert agent._instrumentor is None
        # TODO(b/384730642): Re-enable this test once the parent issue is fixed.
        # agent.set_up()
        # assert agent._instrumentor is not None
        # assert "enable_tracing=True but proceeding with tracing disabled" in caplog.text

    @pytest.mark.usefixtures("caplog")
    def test_enable_tracing_warning(self, caplog, autogen_instrumentor_none_mock):
        agent = reasoning_engines.AG2Agent(
            model=_TEST_MODEL,
            runnable_name=_TEST_RUNNABLE_NAME,
            enable_tracing=True,
        )
        assert agent._instrumentor is None
        # TODO(b/384730642): Re-enable this test once the parent issue is fixed.
        # agent.set_up()
        # assert "enable_tracing=True but proceeding with tracing disabled" in caplog.text


def _return_input_no_typing(input_):
    """Returns input back to user."""
    return input_


class TestConvertToolsOrRaiseErrors:
    def test_raise_untyped_input_args(self, vertexai_init_mock):
        with pytest.raises(TypeError, match=r"has untyped input_arg"):
            reasoning_engines.AG2Agent(
                model=_TEST_MODEL,
                runnable_name=_TEST_RUNNABLE_NAME,
                tools=[_return_input_no_typing],
            )
