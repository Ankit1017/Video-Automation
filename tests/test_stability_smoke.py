from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

if "groq" not in sys.modules:
    groq_stub = types.ModuleType("groq")

    class _GroqStub:
        def __init__(self, *args, **kwargs):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **_kwargs: types.SimpleNamespace(choices=[])))

    groq_stub.Groq = _GroqStub
    sys.modules["groq"] = groq_stub

from main_app.app import runtime
from main_app.constants import PRESET_MODELS, TAB_TITLES
from main_app.models import GroqSettings, WebSourcingSettings
from main_app.ui import sidebar as sidebar_module
from main_app.ui.sidebar import SidebarRenderResult
from main_app.ui.tabs import main_tabs


class _SessionState(dict):
    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - parity with dict behavior.
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


class _FakeContextManager:
    def __init__(self, owner: object) -> None:
        self._owner = owner

    def __enter__(self) -> object:
        return self._owner

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False


class _FakeRuntimeStreamlit:
    def __init__(self) -> None:
        self.session_state = _SessionState()
        self.page_config_calls: list[dict[str, object]] = []
        self.titles: list[str] = []
        self.writes: list[str] = []

    def set_page_config(self, **kwargs) -> None:  # noqa: ANN003
        self.page_config_calls.append(dict(kwargs))

    def title(self, value: str) -> None:
        self.titles.append(str(value))

    def write(self, value: str) -> None:
        self.writes.append(str(value))


class _FakeTabContainer:
    def __enter__(self) -> "_FakeTabContainer":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False


class _FakeTabsStreamlit:
    def __init__(self) -> None:
        self.warning_messages: list[str] = []
        self.tab_calls: list[list[str]] = []

    def warning(self, message: str) -> None:
        self.warning_messages.append(str(message))

    def tabs(self, titles: list[str]) -> list[_FakeTabContainer]:
        self.tab_calls.append([str(title) for title in titles])
        return [_FakeTabContainer() for _ in titles]


class _FakeSidebarStreamlit:
    def __init__(self, seed_state: dict[str, object] | None = None) -> None:
        self.session_state = _SessionState(seed_state or {})
        self.sidebar = _FakeContextManager(self)

    def _pick(self, *, key: str | None, default: object) -> object:
        if key is None:
            return default
        if key in self.session_state:
            return self.session_state[key]
        self.session_state[key] = default
        return default

    def header(self, _label: str) -> None:
        return

    def subheader(self, _label: str) -> None:
        return

    def markdown(self, _value: str) -> None:
        return

    def text_input(self, _label: str, value: str = "", key: str | None = None, **kwargs) -> str:  # noqa: ANN003
        result = str(self._pick(key=key, default=value))
        if key:
            self.session_state[key] = result
        return result

    def radio(self, _label: str, options: list[str], index: int = 0, key: str | None = None, **kwargs) -> str:  # noqa: ANN003
        default = options[index]
        candidate = str(self._pick(key=key, default=default))
        result = candidate if candidate in options else default
        if key:
            self.session_state[key] = result
        return result

    def selectbox(self, _label: str, options: list[str], index: int = 0, key: str | None = None, **kwargs) -> str:  # noqa: ANN003
        default = options[index]
        candidate = str(self._pick(key=key, default=default))
        result = candidate if candidate in options else default
        if key:
            self.session_state[key] = result
        return result

    def slider(self, _label: str, min_value: float, max_value: float, value: float, key: str | None = None, **kwargs) -> float:  # noqa: ANN003
        candidate = self._pick(key=key, default=value)
        try:
            result = float(candidate)
        except (TypeError, ValueError):
            result = float(value)
        result = min(max(result, float(min_value)), float(max_value))
        if key:
            self.session_state[key] = result
        return result

    def number_input(self, _label: str, min_value: int, max_value: int, value: int, key: str | None = None, **kwargs) -> int:  # noqa: ANN003
        candidate = self._pick(key=key, default=value)
        try:
            result = int(candidate)
        except (TypeError, ValueError):
            result = int(value)
        result = min(max(result, int(min_value)), int(max_value))
        if key:
            self.session_state[key] = result
        return result

    def multiselect(self, _label: str, options: list[str], default: list[str], key: str | None = None, **kwargs) -> list[str]:  # noqa: ANN003
        candidate = self._pick(key=key, default=default)
        values = candidate if isinstance(candidate, list) else default
        result = [item for item in values if item in options]
        if key:
            self.session_state[key] = list(result)
        return list(result)

    def checkbox(self, _label: str, value: bool = False, key: str | None = None, **kwargs) -> bool:  # noqa: ANN003
        result = bool(self._pick(key=key, default=value))
        if key:
            self.session_state[key] = result
        return result

    def text_area(self, _label: str, value: str = "", key: str | None = None, **kwargs) -> str:  # noqa: ANN003
        result = str(self._pick(key=key, default=value))
        if key:
            self.session_state[key] = result
        return result

    def expander(self, _label: str, **kwargs) -> _FakeContextManager:  # noqa: ANN003
        return _FakeContextManager(self)


class TestStabilitySmoke(unittest.TestCase):
    def test_app_boot_with_valid_defaults(self) -> None:
        fake_st = _FakeRuntimeStreamlit()
        fake_st.session_state.llm_cache = {}
        storage_bundle = SimpleNamespace(cache_store=SimpleNamespace(load=lambda: {}), cache_label=".cache/llm_cache.json")
        sidebar_result = SidebarRenderResult(
            settings=GroqSettings(api_key="", model=PRESET_MODELS[0], temperature=0.4, max_tokens=1400),
            cache_count_placeholder=SimpleNamespace(caption=lambda *_: None),
            web_sourcing_settings=WebSourcingSettings(),
            enabled_tab_titles=list(TAB_TITLES),
        )

        with (
            patch.object(runtime, "st", fake_st),
            patch.object(runtime, "clear_request_id"),
            patch.object(runtime, "build_storage_bundle", return_value=storage_bundle),
            patch.object(runtime, "initialize_session_state"),
            patch.object(runtime, "ObservabilityService", return_value=object()),
            patch.object(runtime, "GroqChatCompletionClient", return_value=object()),
            patch.object(runtime, "CachedLLMService", return_value=object()),
            patch.object(runtime, "build_app_container", return_value=object()),
            patch.object(runtime, "render_sidebar", return_value=sidebar_result),
            patch.object(runtime, "BackgroundJobManager", return_value=object()),
            patch.object(runtime, "build_main_registrations", return_value=[]),
            patch.object(runtime, "render_main_tabs") as render_main_tabs_mock,
        ):
            runtime.run_streamlit_app()

        self.assertTrue(fake_st.page_config_calls)
        self.assertIn("observability_service", fake_st.session_state)
        render_main_tabs_mock.assert_called_once_with([], enabled_tab_titles=list(TAB_TITLES))

    def test_tab_enablement_zero_then_reenable(self) -> None:
        fake_st = _FakeTabsStreamlit()
        rendered: list[str] = []
        registrations = [
            main_tabs.TabRegistration(title="Detailed Description", render=lambda: rendered.append("Detailed Description")),
            main_tabs.TabRegistration(title="Quiz", render=lambda: rendered.append("Quiz")),
        ]

        with patch.object(main_tabs, "st", fake_st):
            main_tabs.render_main_tabs(registrations, enabled_tab_titles=[])
            self.assertTrue(fake_st.warning_messages)
            self.assertEqual(rendered, [])

            main_tabs.render_main_tabs(registrations, enabled_tab_titles=["Quiz"])

        self.assertEqual(rendered, ["Quiz"])
        self.assertEqual(fake_st.tab_calls, [["Quiz"]])

    def test_web_sourcing_toggle_and_provider_switch(self) -> None:
        fake_st = _FakeSidebarStreamlit(
            seed_state={
                "enabled_tab_titles": list(TAB_TITLES),
                "web_sourcing_enabled": True,
                "web_sourcing_provider": "serper",
                "web_sourcing_secondary_provider_key": "duckduckgo",
            }
        )

        with patch.object(sidebar_module, "st", fake_st):
            first = sidebar_module.render_sidebar()
            self.assertTrue(first.web_sourcing_settings.enabled)
            self.assertEqual(first.web_sourcing_settings.provider_key, "serper")

            fake_st.session_state["web_sourcing_enabled"] = False
            fake_st.session_state["web_sourcing_provider"] = "duckduckgo"
            fake_st.session_state["web_sourcing_secondary_provider_key"] = "serper"

            second = sidebar_module.render_sidebar()

        self.assertFalse(second.web_sourcing_settings.enabled)
        self.assertEqual(second.web_sourcing_settings.provider_key, "duckduckgo")


if __name__ == "__main__":
    unittest.main()
