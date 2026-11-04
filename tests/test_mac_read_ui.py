import unittest
from unittest.mock import patch

try:
    import mac_tools as tools
except ImportError:
    tools = None


@unittest.skipIf(tools is None, "macOS/PyObjC required")
class ReadUITests(unittest.TestCase):
    def read(self, window, menu=None):
        app = {"AXWindows": [window], "AXMenuBar": menu}
        with patch.object(tools.AX, "AXIsProcessTrusted", return_value=True), \
                patch.object(tools, "_find_running", return_value={"name": "Example", "pid": 42}), \
                patch.object(tools, "_app_element", return_value=app), \
                patch.object(tools, "_screen_size", return_value=(1920, 1080)), \
                patch.object(tools, "_frame", return_value=None), \
                patch.object(tools, "_attr", side_effect=lambda el, key: el.get(key)):
            return tools.t_read_ui(app="Example", include_menu_bar=menu is not None)

    def test_window_buttons_and_menus_do_not_imply_readable_body(self):
        window = {"AXRole": "AXWindow", "AXChildren": [
            {"AXRole": "AXButton", "AXSubrole": subrole}
            for subrole in ("AXCloseButton", "AXMinimizeButton", "AXZoomButton")]}
        menu = {"AXRole": "AXMenuBar", "AXChildren": [
            {"AXRole": "AXMenuItem", "AXTitle": "File"}]}
        self.assertIn("未读到窗口内的内容", self.read(window, menu))

    def test_navigation_children_expose_body_when_children_empty(self):
        window = {"AXRole": "AXWindow", "AXChildren": [], "AXChildrenInNavigationOrder": [
            {"AXRole": "AXStaticText", "AXValue": "Readable message"}]}
        output = self.read(window)
        self.assertIn("Readable message", output)
        self.assertNotIn("未读到窗口内的内容", output)

    def test_contents_fallback_and_primary_children_precedence(self):
        text = {"AXRole": "AXStaticText", "AXValue": "Fallback message"}
        self.assertIn("Fallback message", self.read({"AXRole": "AXWindow", "AXContents": [text]}))
        window = {"AXRole": "AXWindow", "AXChildren": [text],
                  "AXChildrenInNavigationOrder": [text], "AXContents": [text]}
        self.assertEqual(self.read(window).count("Fallback message"), 1)

    def test_application_requests_both_accessibility_switches(self):
        with patch.object(tools.AX, "AXUIElementCreateApplication", return_value="app"), \
                patch.object(tools.AX, "AXUIElementSetMessagingTimeout"), \
                patch.object(tools.AX, "AXUIElementSetAttributeValue", return_value=-25205) as set_attr:
            self.assertEqual(tools._app_element(42), "app")
        self.assertEqual([call.args[1] for call in set_attr.call_args_list],
                         ["AXManualAccessibility", "AXEnhancedUserInterface"])


if __name__ == "__main__":
    unittest.main()
