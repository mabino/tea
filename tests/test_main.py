from unittest.mock import patch

from tea import __main__


def test_main_invokes_uvicorn():
    with patch("tea.runtime.uvicorn.run") as run_mock, patch("tea.runtime.get_settings") as settings_mock, patch("tea.runtime.create_app") as create_app_mock:
        settings_mock.return_value = type(
            "Settings",
            (),
            {
                "app_host": "0.0.0.0",
                "app_port": 8000,
                "debug": False,
                "novnc_enabled": True,
                "noVNC_password_required": False,
                "novnc_password": None,
                "novnc_display": ":0",
                "novnc_geometry": "1280x800x24",
                "novnc_vnc_port": 5900,
                "novnc_web_port": 6080,
            },
        )()
        app_instance = object()
        create_app_mock.return_value = app_instance

        __main__.main()

        create_app_mock.assert_called_once_with(settings_mock.return_value)
        run_mock.assert_called_once_with(app_instance, host="0.0.0.0", port=8000, log_level="info")
