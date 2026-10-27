import os
import unittest
from unittest.mock import patch
import i18n
import backends


class Languages(unittest.TestCase):
    def setUp(self):
        self.old = i18n.language()

    def tearDown(self):
        i18n.set_language(self.old)

    def test_labels_and_formatted_statuses_in_both_languages(self):
        i18n.set_language('en')
        self.assertEqual(i18n.tr('新对话'),'New chat')
        self.assertEqual(i18n.tr('检查更新 · v0.3.0'),'Check for updates · v0.3.0')
        self.assertEqual(i18n.tr('完成 · 2 轮 · 14 秒'),'Completed · 2 turn(s) · 14s')
        self.assertEqual(i18n.tr('正在处理… · model · 推理 high'),'Working… · model · effort high')
        self.assertEqual(i18n.tr('执行了 {n} 步',n=3),'3 steps')
        i18n.set_language('zh_CN')
        self.assertEqual(i18n.tr('新对话'),'新对话')
        self.assertEqual(i18n.tr('执行了 {n} 步',n=3),'执行了 3 步')

    def test_response_language_and_mcp_environment(self):
        for language, expected in [('en','English'),('zh_CN','简体中文')]:
            i18n.set_language(language)
            self.assertIn('Response language: '+expected,backends.context_note(None))
            backend=backends.ClaudeCodeBackend(None)
            import json
            config=json.loads(backend._mcp_config())
            self.assertEqual(config['mcpServers']['mac']['env']['MAC_CTRL_LANGUAGE'],language)

    def test_unknown_strings_and_model_ids_are_unchanged(self):
        i18n.set_language('en')
        for value in ('custom-model-id','Project notes / 客户记录','2026-10-27　测试对话'):
            self.assertEqual(i18n.tr(value),value)
        self.assertEqual(i18n.tr('新对话（点击打开）'),'新对话 (click to open)')
