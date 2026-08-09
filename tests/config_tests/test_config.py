"""Bug 198：配置层单元测试（pytest 风格，兼容 unittest runner）。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestSettings(unittest.TestCase):
    def test_defaults_present(self):
        from config import settings
        # 所有配置函数都有默认值（不因缺 env 崩溃）
        self.assertIsInstance(settings.qwen_base_url(), str)
        self.assertIsInstance(settings.qwen_model(), str)
        self.assertIsInstance(settings.qwen_vlm_analyze_model(), str)
        self.assertIsInstance(settings.default_map(), str)
        self.assertTrue(settings.knowledge_root().is_absolute())
        self.assertTrue(settings.march7_root().is_absolute())

    def test_reload(self):
        from config import settings
        # Bug 97：reload 不崩且返回新 env 字典
        env = settings.reload_config()
        self.assertIsInstance(env, dict)

    def test_validate_config(self):
        from config import settings
        ok, problems = settings.validate_config()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(problems, list)

    def test_redact_secrets(self):
        from config.settings import redact_secrets
        out = redact_secrets("Bearer sk-abc123xyz456 SESSDATA=xyz123456")
        self.assertNotIn("sk-abc123xyz456", out)
        self.assertNotIn("xyz123456", out)


class TestVersion(unittest.TestCase):
    def test_version_single_source(self):
        # Bug 194：版本号单点——模块导入不崩
        from config.version import APP_VERSION, KNOWLEDGE_SCHEMA_VERSION
        self.assertTrue(APP_VERSION)
        self.assertEqual(KNOWLEDGE_SCHEMA_VERSION, 1)


if __name__ == "__main__":
    unittest.main()
