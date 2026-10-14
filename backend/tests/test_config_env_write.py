"""后台配置读写单测：write_env 行级替换/追加、非法键忽略（.env 单源）。"""

import os
import tempfile
import unittest

from config import app_config


class EnvWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = os.path.join(self.tmp, ".env")
        with open(self.env, "w", encoding="utf-8") as f:
            f.write("LLM_MODEL=old\n")
        self._orig = app_config._dotenv_file
        app_config._dotenv_file = self.env

    def tearDown(self):
        app_config._dotenv_file = self._orig
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_replace_and_append(self):
        changed = app_config.write_env({"LLM_MODEL": "new", "RETRIEVAL_TOP_K": 7})
        self.assertTrue(changed)
        text = open(self.env, encoding="utf-8").read()
        self.assertIn("LLM_MODEL=new\n", text)          # 替换原行
        self.assertIn("RETRIEVAL_TOP_K=7\n", text)      # 追加新行

    def test_invalid_key_ignored(self):
        self.assertFalse(app_config.write_env({"NOT_A_KEY": 1}))

    def test_config_env_dict_keys_are_env_names(self):
        app_config._dotenv_file = self._orig          # 读真实 .env（含必填项）
        d = app_config.config_env_dict()
        self.assertIn("LLM_MODEL", d)
        self.assertIn("CACHE_BACKEND", d)


if __name__ == "__main__":
    unittest.main()
